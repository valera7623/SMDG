# app/api/upload.py
from fastapi import APIRouter, UploadFile, HTTPException, Depends, Form, Request
from app.models.user import User
import magic
import uuid
import clamd
import asyncio
from app.core import (
    UPLOAD_DIR,
    ENCRYPTED_DIR,
    audit_logger,
    get_public_key
)
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.rate_limiter import limiter  
from app.crypto.crypto import crypto_manager
from app.core.utils import sanitize_filename, calculate_hash
from app.core.config import settings
from app.core.auth import get_current_user, TokenData
from app.core.database import get_db
from app.models.file import File
from app.models.file_link import FileLink
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone

router = APIRouter()

# Разрешённые mime-типы (можно расширить под нужды медицинских файлов)
ALLOWED_MIME_PREFIXES = [
    "application/pdf",                                           # PDF
    "image/",                                                    # Все изображения (jpeg, png, tiff, dicom и т.д.)
    "text/plain",                                                # Текстовые файлы
    "application/msword",                                        # DOC
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    "application/dicom",                                         # DICOM файлы
    "application/json",                                          # JSON
    "application/xml"                                            # XML
]

@router.post("/upload")
@limiter.limit("10/minute")
async def upload_file(
    request: Request,
    file: UploadFile = Form(...),
    ttl_days: int = Form(30),
    max_downloads: int = Form(1),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    temp_upload_path = None

    try:
        original_filename = file.filename
        safe_filename = sanitize_filename(original_filename)

        # 1. Чтение файла
        file_content = await file.read()

        # 2. Ограничение размера
        if len(file_content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(413, f"Файл слишком большой (макс. {settings.MAX_UPLOAD_SIZE_MB}MB)")

        # 3. Проверка MIME-типа
        mime = magic.Magic(mime=True)
        mime_type = mime.from_buffer(file_content)

        if mime_type not in settings.ALLOWED_MIME_TYPES:
            if mime_type.startswith("application/octet-stream"):
                # Для DICOM иногда mime = octet-stream → проверяем заголовок
                if len(file_content) > 132 and file_content[128:132] == settings.DICOM_MAGIC:
                    mime_type = "application/dicom"
                else:
                    raise HTTPException(400, f"Недопустимый тип файла: {mime_type}")
            else:
                raise HTTPException(400, f"Недопустимый тип файла: {mime_type}")

        # 4. Сохранение во временный файл
        temp_upload_path = UPLOAD_DIR / f"{uuid.uuid4()}_{safe_filename}"
        with open(temp_upload_path, "wb") as buffer:
            buffer.write(file_content)

       
        # 5. Проверка на вирусы через ClamAV
        # 5. Проверка на вирусы через ClamAV
        virus_detected = False
        virus_name = None

        try:
            import clamd
            print(f"[ClamAV] Пытаемся подключиться: {settings.CLAMAV_HOST}:{settings.CLAMAV_PORT}")

            cd = clamd.ClamdNetworkSocket(
                host=settings.CLAMAV_HOST,
                port=settings.CLAMAV_PORT,
                timeout=settings.CLAMAV_TIMEOUT
            )

            # Проверка пинга
            ping_result = cd.ping()
            print(f"[ClamAV] ping OK: {ping_result}")

            # Сканируем файл - передаем открытый файл в бинарном режиме
            loop = asyncio.get_running_loop()
            with open(temp_upload_path, "rb") as file_to_scan:
                scan_result = await loop.run_in_executor(None, cd.instream, file_to_scan)
            print(f"[ClamAV] scan_result: {scan_result}")

            # Обработка результата
            if scan_result:
                scan_result = scan_result.get('stream') if isinstance(scan_result, dict) else scan_result
                if scan_result and len(scan_result) > 0:
                    result_type = scan_result[0]
                    if result_type == "FOUND":
                        virus_name = scan_result[1] if len(scan_result) > 1 else "unknown"
                        virus_detected = True
                        print(f"[ClamAV] ВИРУС ОБНАРУЖЕН: {virus_name}")
                elif result_type == "OK":
                    print("[ClamAV] Файл чист")
                else:
                    print(f"[ClamAV] Неожиданный результат: {scan_result}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"[ClamAV] ОШИБКА СКАНИРОВАНИЯ: {error_msg}")
            audit_logger.log_operation(
                action="clamav_error",
                filename=original_filename,
                user=current_user.sub if current_user else "system",
                reason=error_msg,
                success=False
            )
            if not settings.dev_mode:
                raise HTTPException(503, "Антивирусный сервис временно недоступен. Загрузка запрещена.")

        if virus_detected:
            audit_logger.log_operation(
                action="upload_virus_detected",
                filename=original_filename,
                user=current_user.sub if current_user else "api_user",
                reason=f"Обнаружен вирус: {virus_name}",
                success=False
            )
            raise HTTPException(400, f"Обнаружен вредоносный код: {virus_name or 'неизвестный'}")
        else:
            print("[ClamAV] Файл чист")

        final_encrypted_name = f"{uuid.uuid4()}_{safe_filename}.age"
        final_encrypted_path = ENCRYPTED_DIR / final_encrypted_name

        # Шифрование (убеждаемся, что пути - Path)
        encrypted_hash = await crypto_manager.encrypt_file(
            input_path=temp_upload_path,
            public_key=get_public_key(),
            output_path=final_encrypted_path
        )

        # Хэш оригинального файла
        original_hash = calculate_hash(temp_upload_path)

        # Получаем user_id из БД по current_user.sub (если пользователь авторизован)
        user_id = None
        if current_user:
            result = await db.execute(select(User).where(User.username == current_user.sub))
            db_user = result.scalar_one_or_none()
            if db_user:
                user_id = db_user.id
            else:
                print(f"Предупреждение: пользователь {current_user.sub} не найден в БД")
                audit_logger.log_operation(
                    action="upload_warning",
                    filename=original_filename,
                    user=current_user.sub,
                    reason=f"Пользователь {current_user.sub} не найден в БД",
                    success=True
                )

        # Создаём запись в БД для файла
        new_file = File(
            user_id=user_id,
            original_name=original_filename,
            encrypted_name=final_encrypted_name,
            encrypted_path=str(final_encrypted_path),
            original_size=len(file_content),
            encrypted_size=final_encrypted_path.stat().st_size,
            original_hash=original_hash,
            mime_type=mime_type,
            uploaded_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days)
        )
        db.add(new_file)
        await db.commit()
        await db.refresh(new_file)

        # Создаём одноразовую ссылку
        token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        
        link = FileLink(
            token=token,
            file_id=new_file.id,
            max_downloads=max_downloads,
            expires_at=expires_at
        )
        db.add(link)
        await db.commit()
        await db.refresh(link)
        print(f"Создана ссылка: token={link.token}, file_id={link.file_id}, expires_at={link.expires_at}")

        # Формируем URL для скачивания
        base_url = request.url_for('download_by_token') if request else "/api/download"
        download_url = f"{base_url}?token={token}"

        # Логируем успешную загрузку
        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user=current_user.sub if current_user else "api_user",
            reason="Успешная загрузка и шифрование",
            success=True,
            metadata={
                "mime_type": mime_type,
                "size": len(file_content),
                "encrypted_name": final_encrypted_name,
                "ttl_days": ttl_days
            }
        )

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

    except Exception as e:
        print(f"Ошибка загрузки файла '{original_filename}': {e}")
        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user=current_user.sub if current_user else "api_user",
            reason=f"Upload failed: {str(e)}",
            success=False,
            metadata={"mime_type": mime_type if 'mime_type' in locals() else "unknown"}
        )
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    finally:
        if temp_upload_path is not None and temp_upload_path.exists():
            try:
                temp_upload_path.unlink()
            except Exception as cleanup_error:
                print(f"Не удалось удалить временный файл {temp_upload_path}: {cleanup_error}")