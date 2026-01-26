# app/api/upload.py
from fastapi import APIRouter, UploadFile, HTTPException, Depends, Form, Request
from app.models.user import User
import magic
import uuid

from app.core import (
    UPLOAD_DIR,
    ENCRYPTED_DIR,
    audit_logger,
    get_public_key
)
from app.crypto.crypto import crypto_manager
from app.core.utils import sanitize_filename, calculate_hash
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
async def upload_file(
    file: UploadFile = Form(...),
    ttl_days: int = Form(30),
    max_downloads: int = Form(1),
    request: Request = None,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Загрузка и шифрование файла"""
    temp_upload_path = None  # Инициализируем как None для безопасной очистки в finally

    try:
        original_filename = file.filename

        # Безопасное имя
        safe_filename = sanitize_filename(original_filename)

        # Проверяем MIME-тип
        mime = magic.Magic(mime=True)
        file_content = await file.read()
        MAX_SIZE_MB = 50
        if len(file_content) > MAX_SIZE_MB * 1024 * 1024:
            raise HTTPException(413, f"Файл слишком большой (макс. {MAX_SIZE_MB}MB)")
        mime_type = mime.from_buffer(file_content)

        if not any(mime_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
            raise HTTPException(status_code=400, detail=f"Недопустимый тип файла: {mime_type}")

        # Сохраняем файл во временную директорию
        temp_upload_path = UPLOAD_DIR / f"{uuid.uuid4()}_{safe_filename}"
        with open(temp_upload_path, "wb") as buffer:
            buffer.write(file_content)

        # Уникальное имя для зашифрованного файла
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