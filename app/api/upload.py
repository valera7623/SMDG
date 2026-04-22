# app/api/upload.py
from typing import Optional
from fastapi import APIRouter, UploadFile, HTTPException, Depends, Form, Request
from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationError
import magic
import uuid
import asyncio
import json
from pathlib import Path
import logging

from app.core import (
    UPLOAD_DIR,
    ENCRYPTED_DIR,
    audit_logger,
    get_public_key,
    settings,
    encrypted_storage,
)
from app.core.webhook import webhook_dispatcher
from app.core.rate_limiter import limiter
from app.core.tracing import get_tracer

try:
    from opentelemetry import trace  # type: ignore
except ImportError:  # pragma: no cover - tracing is optional
    trace = None  # type: ignore[assignment]
from app.crypto.crypto import crypto_manager
from app.core.utils import calculate_hash_async, sanitize_filename
from app.core.auth import get_current_user, TokenData
from app.core.database import get_db
from app.core.database import execute_with_timeout as execute_db_with_timeout
from app.models.file import File
from app.models.file_link import FileLink
from app.models.user import User
from app.core.tenant import require_tenant, assert_tenant_access
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from app.core.timeout import TimeoutError, timeout
from app.services.clamav_service import scan_file as clamav_scan_file

logger = logging.getLogger(__name__)
router = APIRouter()

# Отдельный tracer для upload-пути. Безопасен даже при отключённом tracing:
# :func:`get_tracer` возвращает no-op при недоступности OpenTelemetry.
tracer = get_tracer(__name__)


# ==================== Константы (для тестов) ====================

ALLOWED_MIME_PREFIXES = [
    "application/pdf",
    "image/",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/dicom",
    "application/json",
    "application/xml"
]

ALLOWED_EXTENSIONS = {
    '.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.gif',
    '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv', '.rtf',
    '.dcm', '.dicom'
}

DANGEROUS_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.scr', '.js', '.vbs', '.ps1', '.dll',
    '.jar', '.apk', '.msi', '.sh', '.php', '.py', '.pyc', '.pif'
}


# ==================== Pydantic V2 Модель ====================

class UploadParams(BaseModel):
    ttl_days: int = Field(30, ge=1, le=90)
    max_downloads: int = Field(1, ge=1, le=50)
    patient_id: Optional[str] = Field(None, max_length=100)
    medical_metadata_json: Optional[str] = Field(None)

    @field_validator('medical_metadata_json')
    @classmethod
    def validate_metadata_json(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError('Некорректный JSON в medical_metadata_json')
        return v

    model_config = ConfigDict(extra='ignore')


# ==================== Валидация ====================

def validate_file_safety(
    original_filename: str,
    content_preview: bytes,
    full_size: int = 0
) -> tuple[str, str]:
    path = Path(original_filename)
    orig_ext = path.suffix.lower()

    if orig_ext in DANGEROUS_EXTENSIONS:
        raise HTTPException(400, f"Запрещённое расширение: {orig_ext}")

    if orig_ext and orig_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Недопустимое расширение: {orig_ext}. "
            f"Разрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    mime_detector = magic.Magic(mime=True)
    detected_mime = mime_detector.from_buffer(content_preview)

    is_dicom_by_header = len(content_preview) >= 132 and content_preview[128:132] == b'DICM'

    if orig_ext in {'.dcm', '.dicom'}:
        if not is_dicom_by_header:
            raise HTTPException(400, "Файл .dcm/.dicom не является валидным DICOM (отсутствует сигнатура DICM)")
        detected_mime = "application/dicom"

    if detected_mime == "application/octet-stream":
        if is_dicom_by_header:
            detected_mime = "application/dicom"
        elif orig_ext == '.pdf':
            detected_mime = "application/pdf"
        elif orig_ext in {'.jpg', '.jpeg'}:
            detected_mime = "image/jpeg"

    allowed = any(
        detected_mime == mime_type or detected_mime.startswith(mime_type.rstrip('*'))
        for mime_type in ALLOWED_MIME_PREFIXES
    )

    if not allowed:
        raise HTTPException(400, f"Недопустимый тип содержимого: {detected_mime}")

    return detected_mime, orig_ext


# ==================== Основной эндпоинт ====================

@router.post("/upload")
@limiter.limit("10/minute")
@timeout(60.0, "File upload timed out after 60 seconds", service="api", operation="upload_file")
async def upload_file(
    request: Request,
    file: UploadFile = Form(...),
    ttl_days: int = Form(30),
    max_downloads: int = Form(1),
    patient_id: Optional[str] = Form(None),
    medical_metadata_json: Optional[str] = Form(None),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    temp_upload_path: Optional[Path] = None
    original_filename = file.filename or "unnamed_file"
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)

    # Внешний серверный span создаётся FastAPIInstrumentor автоматически.
    # Мы добавляем кастомные вложенные спаны для ключевых фаз upload-пайплайна.
    # В атрибуты НЕ кладём PII (имя файла, patient_id) — только безопасные
    # метаданные (размер, mime, tenant_id, расширение).
    current_span = trace.get_current_span() if trace is not None else None
    if current_span is not None:
        try:
            current_span.set_attribute("tenant.id", str(tenant.id))
            current_span.set_attribute(
                "file.extension", Path(original_filename).suffix.lower() or "unknown"
            )
        except Exception:
            pass

    try:
        params = UploadParams(
            ttl_days=ttl_days,
            max_downloads=max_downloads,
            patient_id=patient_id,
            medical_metadata_json=medical_metadata_json
        )

        safe_filename = sanitize_filename(original_filename)

        with tracer.start_as_current_span("upload.validate_mime"):
            preview = await file.read(8192)
            await file.seek(0)
            mime_type, _ = validate_file_safety(original_filename, preview, 0)

        file_content = await file.read()
        if current_span is not None:
            try:
                current_span.set_attribute("file.size_bytes", len(file_content))
                current_span.set_attribute("file.mime_type", mime_type)
            except Exception:
                pass

        if len(file_content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(413, f"Файл слишком большой (макс. {settings.MAX_UPLOAD_SIZE_MB}MB)")

        # Вторая проверка MIME (для octet-stream image fallback)
        mime = magic.Magic(mime=True)
        detected_mime = mime.from_buffer(file_content)

        orig_ext = Path(original_filename).suffix.lower()

        allowed = any(
            detected_mime == mime_type or detected_mime.startswith(mime_type.rstrip('*'))
            for mime_type in ALLOWED_MIME_PREFIXES
        )

        if not allowed and detected_mime == "application/octet-stream":
            if len(file_content) >= 132 and file_content[128:132] == b'DICM':
                detected_mime = "application/dicom"
                allowed = True
            elif orig_ext in {'.jpg', '.jpeg', '.png', '.gif'}:
                allowed = True

        if not allowed:
            raise HTTPException(400, f"Недопустимый тип файла: {detected_mime}")

        temp_upload_path = UPLOAD_DIR / f"{uuid.uuid4()}_{safe_filename}"
        with open(temp_upload_path, "wb") as buffer:
            buffer.write(file_content)

        # ClamAV (c Circuit Breaker)
        virus_detected = False
        virus_name = None
        with tracer.start_as_current_span("upload.clamav_scan") as scan_span:
            from app.core.circuit_breaker import (
                CircuitBreakerOpenError,
                get_circuit_breaker,
            )
            from app.core.circuit_breaker_metrics import record_rejected_call

            clamav_cb = get_circuit_breaker("clamav")

            try:
                scan_result = await clamav_cb.call(clamav_scan_file, temp_upload_path)
                if scan_result.get("status") == "infected":
                    virus_detected = True
                    virus_name = scan_result.get("virus_name", "unknown")
                if scan_result.get("status") == "skipped":
                    audit_logger.log_operation(
                        action="clamav_skipped_timeout",
                        filename=original_filename,
                        user=current_user.sub,
                        reason="ClamAV scan timeout",
                        success=False,
                    )
                try:
                    scan_span.set_attribute("clamav.virus_detected", bool(virus_detected))
                except Exception:
                    pass
            except CircuitBreakerOpenError:
                # Брейкер открыт — ClamAV считаем «всё ещё лежит». Чтобы не
                # блокировать весь upload-канал, пропускаем проверку: это
                # осознанный availability vs security trade-off (см. ТЗ).
                record_rejected_call("clamav")
                logger.warning(
                    "ClamAV circuit breaker is OPEN — skipping virus scan "
                    "for upload by user=%s",
                    current_user.sub,
                )
                try:
                    scan_span.set_attribute("clamav.skipped", True)
                    scan_span.set_attribute("clamav.skip_reason", "circuit_breaker_open")
                except Exception:
                    pass
                audit_logger.log_operation(
                    action="clamav_skipped_cb_open",
                    filename=original_filename,
                    user=current_user.sub,
                    reason="ClamAV circuit breaker is OPEN",
                    success=False,
                )
            except Exception as e:
                try:
                    scan_span.set_attribute("clamav.error", type(e).__name__)
                    scan_span.record_exception(e)
                except Exception:
                    pass
                logger.error(f"ClamAV error: {e}")
                audit_logger.log_operation(
                    action="clamav_error",
                    filename=original_filename,
                    user=current_user.sub,
                    reason=str(e),
                    success=False
                )
                if not settings.dev_mode:
                    raise HTTPException(503, "Антивирусный сервис недоступен")

        if virus_detected:
            audit_logger.log_operation(
                action="upload_virus_detected",
                filename=original_filename,
                user=current_user.sub,
                reason=f"Обнаружен вирус: {virus_name}",
                success=False
            )
            raise HTTPException(400, f"Обнаружен вредоносный код: {virus_name}")

        # Шифрование
        final_encrypted_name = f"{uuid.uuid4()}_{safe_filename}.age"

        # Для локального режима используем старый путь, для S3 — ключ объекта
        final_encrypted_path = ENCRYPTED_DIR / final_encrypted_name

        with tracer.start_as_current_span("upload.age_encrypt") as enc_span:
            try:
                enc_span.set_attribute("crypto.algorithm", "age")
            except Exception:
                pass
            await crypto_manager.encrypt_file(
                input_path=temp_upload_path,
                public_key=get_public_key(),
                output_path=final_encrypted_path
            )

        with tracer.start_as_current_span("upload.hash_original"):
            original_hash = await calculate_hash_async(temp_upload_path)

        # Загрузка в хранилище (S3 или локальное)
        storage_key = final_encrypted_name  # S3 key или относительный путь
        with tracer.start_as_current_span("upload.storage_save") as storage_span:
            try:
                storage_span.set_attribute("storage.backend", type(encrypted_storage).__name__)
            except Exception:
                pass
            metadata = await encrypted_storage.upload(
                key=storage_key,
                file_path=final_encrypted_path,
                content_type="application/octet-stream"
            )

        encrypted_size = metadata.size
        if current_span is not None:
            try:
                current_span.set_attribute("file.encrypted_size_bytes", encrypted_size)
            except Exception:
                pass

        user_id = None
        result = await execute_db_with_timeout(
            db.execute(
                select(User).where(User.username == current_user.sub, User.tenant_id == tenant.id)
            ),
            operation="upload_select_user",
        )
        db_user = result.scalar_one_or_none()
        if db_user:
            user_id = db_user.id
        else:
            audit_logger.log_operation(
                action="upload_warning",
                filename=original_filename,
                user=current_user.sub,
                reason="Пользователь test_user не найден в БД",
                success=True
            )

        medical_metadata_dict = json.loads(params.medical_metadata_json) if params.medical_metadata_json else {}

        new_file = File(
            user_id=user_id,
            tenant_id=tenant.id,
            original_name=original_filename,
            encrypted_name=final_encrypted_name,
            encrypted_path=storage_key,  # Теперь хранит S3 key или относительный путь
            original_size=len(file_content),
            encrypted_size=encrypted_size,
            original_hash=original_hash,
            mime_type=mime_type,
            patient_id=params.patient_id,
            medical_metadata=medical_metadata_dict,
            uploaded_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=params.ttl_days)
        )

        with tracer.start_as_current_span("upload.db_save_file"):
            db.add(new_file)
            await execute_db_with_timeout(db.commit(), operation="upload_commit_file")
            await execute_db_with_timeout(db.refresh(new_file), operation="upload_refresh_file")

        token = str(uuid.uuid4())
        link = FileLink(
            token=token,
            file_id=new_file.id,
            max_downloads=params.max_downloads,
            expires_at=datetime.now(timezone.utc) + timedelta(days=params.ttl_days)
        )
        with tracer.start_as_current_span("upload.db_save_link"):
            db.add(link)
            await execute_db_with_timeout(db.commit(), operation="upload_commit_link")

        download_url = str(request.url_for('download_by_token')) + f"?token={token}"

        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user=current_user.sub,
            reason="Успешная загрузка и шифрование",
            success=True,
            metadata={
                "mime_type": mime_type,
                "size": len(file_content),
                "encrypted_name": final_encrypted_name,
                "ttl_days": params.ttl_days
            }
        )

        # Отправляем webhook-уведомление
        asyncio.create_task(
            webhook_dispatcher.dispatch(
                event="file.uploaded",
                data={
                    "file_id": new_file.id,
                    "original_name": original_filename,
                    "encrypted_name": final_encrypted_name,
                    "size": len(file_content),
                    "mime_type": mime_type,
                    "patient_id": params.patient_id,
                    "download_url": download_url,
                    "uploaded_by": current_user.sub,
                }
            )
        )

        logger.info(f"✅ Файл успешно загружен: {original_filename}")

        return {
            "message": "Файл успешно загружен и зашифрован",
            "original_name": original_filename,
            "encrypted_file": final_encrypted_name,
            "download_url": download_url,
            "expires_at": link.expires_at.isoformat(),
            "max_downloads": link.max_downloads
        }

    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except HTTPException:
        raise
    except ValidationError:
        raise HTTPException(status_code=400, detail="Некорректный JSON в medical_metadata_json")
    except Exception as e:
        logger.error(f"Ошибка загрузки '{original_filename}': {e}", exc_info=True)
        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user=current_user.sub if current_user else "api_user",
            reason=f"Upload failed: {str(e)}",
            success=False,
            metadata={"error": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    finally:
        if temp_upload_path and temp_upload_path.exists():
            try:
                temp_upload_path.unlink()
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл: {e}")