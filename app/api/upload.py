# app/api/upload.py
from typing import Optional
from fastapi import APIRouter, UploadFile, HTTPException, Depends, Form, Request
from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationError
import magic
import uuid
import clamd
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
from app.core.rate_limiter import limiter
from app.crypto.crypto import crypto_manager
from app.core.utils import calculate_hash_async, sanitize_filename
from app.core.auth import get_current_user, TokenData
from app.core.database import get_db
from app.models.file import File
from app.models.file_link import FileLink
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
router = APIRouter()


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

    try:
        params = UploadParams(
            ttl_days=ttl_days,
            max_downloads=max_downloads,
            patient_id=patient_id,
            medical_metadata_json=medical_metadata_json
        )

        safe_filename = sanitize_filename(original_filename)

        preview = await file.read(8192)
        await file.seek(0)

        mime_type, _ = validate_file_safety(original_filename, preview, 0)

        file_content = await file.read()

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

        # ClamAV
        virus_detected = False
        virus_name = None
        try:
            cd = clamd.ClamdNetworkSocket(
                host=settings.CLAMAV_HOST,
                port=settings.CLAMAV_PORT,
                timeout=settings.CLAMAV_TIMEOUT
            )
            loop = asyncio.get_running_loop()
            with open(temp_upload_path, "rb") as f:
                scan_result = await loop.run_in_executor(None, cd.instream, f)

            if scan_result and isinstance(scan_result, dict):
                stream_result = scan_result.get('stream')
                if stream_result and stream_result[0] == "FOUND":
                    virus_detected = True
                    virus_name = stream_result[1] if len(stream_result) > 1 else "unknown"
        except Exception as e:
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

        await crypto_manager.encrypt_file(
            input_path=temp_upload_path,
            public_key=get_public_key(),
            output_path=final_encrypted_path
        )

        original_hash = await calculate_hash_async(temp_upload_path)

        # Загрузка в хранилище (S3 или локальное)
        storage_key = final_encrypted_name  # S3 key или относительный путь
        metadata = await encrypted_storage.upload(
            key=storage_key,
            file_path=final_encrypted_path,
            content_type="application/octet-stream"
        )

        encrypted_size = metadata.size

        user_id = None
        result = await db.execute(select(User).where(User.username == current_user.sub))
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

        db.add(new_file)
        await db.commit()
        await db.refresh(new_file)

        token = str(uuid.uuid4())
        link = FileLink(
            token=token,
            file_id=new_file.id,
            max_downloads=params.max_downloads,
            expires_at=datetime.now(timezone.utc) + timedelta(days=params.ttl_days)
        )
        db.add(link)
        await db.commit()

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

        logger.info(f"✅ Файл успешно загружен: {original_filename}")

        return {
            "message": "Файл успешно загружен и зашифрован",
            "original_name": original_filename,
            "encrypted_file": final_encrypted_name,
            "download_url": download_url,
            "expires_at": link.expires_at.isoformat(),
            "max_downloads": link.max_downloads
        }

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