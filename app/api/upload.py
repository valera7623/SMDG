# app/api/upload.py
from fastapi import APIRouter, UploadFile, HTTPException, Depends, Form
from app.models.user import User
import magic  
import uuid

from app.core import (
    UPLOAD_DIR,
    ENCRYPTED_DIR,
    crypto_manager,
    audit_logger,
    get_public_key
)
from app.core.utils import sanitize_filename, calculate_hash
from app.core.auth import get_current_user, TokenData
from app.core.database import get_db
from app.models.file import File
from app.models.file_link import FileLink
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta

router = APIRouter()

# Разрешённые mime-типы (можно расширить под нужды медицинских файлов)
ALLOWED_MIME_PREFIXES = [
    "application/pdf",                                           # PDF
    "image/",                                                    # Все изображения (jpeg, png, tiff, dicom и т.д.)
    "text/plain",                                                # Текстовые файлы
    "application/msword",                                        # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.ms-excel",                                  # .xls
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",       # .xlsx
    "application/dicom"                                          # DICOM файлы
]

@router.post("/upload")
async def upload_file(
    file: UploadFile,  # ← Убрали File(...), оставили только тип
    max_downloads: int = Form(1, ge=1, le=10),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    original_filename = sanitize_filename(file.filename)

    # Чтение буфера для MIME (async)
    buffer = await file.read(2048)
    mime_type = magic.from_buffer(buffer, mime=True)
    await file.seek(0)  # async seek назад

    if not any(mime_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail=f"Недопустимый тип файла: {mime_type}")

    temp_upload_path = UPLOAD_DIR / f"{uuid.uuid4()}_{original_filename}"

    try:
        with open(temp_upload_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # async read
                f.write(chunk)

        original_size = temp_upload_path.stat().st_size

        if original_size == 0:
            raise HTTPException(status_code=400, detail="Пустой файл")

        file_hash = calculate_hash(temp_upload_path)

        final_encrypted_name = f"{uuid.uuid4()}_{original_filename}.age"
        encrypted_path = ENCRYPTED_DIR / final_encrypted_name

        await crypto_manager.encrypt_file(temp_upload_path, encrypted_path, get_public_key())

        encrypted_size = encrypted_path.stat().st_size

        # Создание записи File в БД
        user_id = None
        if current_user:
            stmt = select(User.id).where(User.username == current_user.sub)
            result = await db.execute(stmt)
            user_id = result.scalar_one_or_none()

            if user_id is None:
                raise HTTPException(status_code=401, detail="Пользователь не найден в БД")

        file_record = File(
            user_id=user_id,
            original_name=original_filename,
            encrypted_name=final_encrypted_name,
            encrypted_path=str(encrypted_path),
            original_size=original_size,
            encrypted_size=encrypted_size,
            original_hash=file_hash,
            mime_type=mime_type,
            uploaded_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.add(file_record)
        await db.commit()
        await db.refresh(file_record)

        # Создание FileLink
        link = FileLink(
            file_id=file_record.id,
            token=str(uuid.uuid4()),
            max_downloads=max_downloads,
            downloads_count=0,
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        db.add(link)
        await db.commit()
        await db.refresh(link)

        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user=current_user.sub if current_user else "api_user",
            reason="Файл успешно загружен и зашифрован",
            success=True,
            metadata={
                "original_name": original_filename,
                "encrypted_file": final_encrypted_name,
                "original_size": original_size,
                "encrypted_size": encrypted_size,
                "hash": file_hash
            }
        )

        return {
            "status": "success",
            "file_id": file_record.id,
            "original_name": original_filename,
            "encrypted_file": final_encrypted_name,
            "download_url": f"/api/download?token={link.token}",
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
        if temp_upload_path.exists():
            try:
                temp_upload_path.unlink()
            except Exception as cleanup_error:
                print(f"Не удалось удалить временный файл {temp_upload_path}: {cleanup_error}")