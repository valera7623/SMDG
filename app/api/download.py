# app/api/download.py
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks, Depends, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated
from pathlib import Path
import uuid
import logging

from app.core import ENCRYPTED_DIR, DECRYPTED_DIR, PRIVATE_KEY_PATH, audit_logger, encrypted_storage
from app.core.rate_limiter import limiter
from app.crypto.crypto import crypto_manager
from app.core.utils import sanitize_filename
from app.core.auth import get_current_user, get_current_doctor, TokenData
from app.core.database import get_db
from app.models.file import File
from app.models.file_link import FileLink
from datetime import datetime, timezone

router = APIRouter()
logger = logging.getLogger(__name__)


def delete_file_after_response(path: Path):
    """Безопасное удаление временного файла ПОСЛЕ отправки ответа"""
    try:
        if path.exists():
            path.unlink()
            logger.info(f"🗑️ Временный файл удалён: {path.name}")
        else:
            logger.debug(f"Файл уже отсутствует: {path.name}")
    except Exception as e:
        logger.error(f"Не удалось удалить временный файл {path}: {e}")


@router.get("/download")
@limiter.limit("10/minute")
async def download_by_token(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str = Query(..., description="Одноразовый токен"),
    db: AsyncSession = Depends(get_db)
):
    """Скачивание файла по токену"""
    logger.info(f"[DOWNLOAD TOKEN] Запрос с токеном: '{token}'")

    # Поиск токена
    result = await db.execute(select(FileLink).where(FileLink.token == token))
    link = result.scalar_one_or_none()

    if not link:
        logger.warning(f"[DOWNLOAD TOKEN] ❌ Токен не найден: {token}")
        raise HTTPException(status_code=404, detail="Ссылка не найдена или уже использована")

    logger.info(f"[DOWNLOAD TOKEN] ✅ Токен найден (file_id={link.file_id})")

    # Проверка срока и лимита
    now = datetime.now(timezone.utc)
    if link.expires_at and link.expires_at < now:
        logger.warning("[DOWNLOAD TOKEN] ❌ Ссылка истекла")
        await db.delete(link)
        await db.commit()
        raise HTTPException(status_code=410, detail="Ссылка истекла")

    if link.downloads_count >= link.max_downloads:
        logger.warning("[DOWNLOAD TOKEN] ❌ Лимит скачиваний исчерпан")
        await db.delete(link)
        await db.commit()
        raise HTTPException(status_code=410, detail="Лимит скачиваний исчерпан")

    # Поиск файла
    result = await db.execute(select(File).where(File.id == link.file_id))
    file_record = result.scalar_one_or_none()

    if not file_record:
        logger.error(f"[DOWNLOAD TOKEN] ❌ Файл с ID {link.file_id} не найден")
        raise HTTPException(status_code=404, detail="Файл не найден")

    # encrypted_path теперь может быть S3 key или локальным путём
    storage_key = file_record.encrypted_path
    decrypted_path = DECRYPTED_DIR / f"{uuid.uuid4()}_{file_record.original_name}"

    logger.info(f"[DOWNLOAD TOKEN] Расшифровываем: {file_record.original_name}")

    try:
        # Скачиваем из хранилища во временную директорию для расшифровки
        encrypted_local_path = DECRYPTED_DIR / f"enc_{uuid.uuid4()}_{file_record.encrypted_name}"

        await encrypted_storage.download(
            key=storage_key,
            destination_path=encrypted_local_path
        )

        await crypto_manager.decrypt_file(
            encrypted_path=encrypted_local_path,
            private_key_path=PRIVATE_KEY_PATH,
            output_path=decrypted_path
        )

        # Удаляем временный зашифрованный файл сразу после расшифровки
        try:
            if encrypted_local_path.exists():
                encrypted_local_path.unlink()
        except Exception as e:
            logger.warning(f"Не удалось удалить временный зашифрованный файл: {e}")

        # Увеличиваем счётчик
        link.downloads_count += 1
        if link.downloads_count >= link.max_downloads:
            await db.delete(link)
        await db.commit()

        # Добавляем удаление файла **после** отправки ответа
        background_tasks.add_task(delete_file_after_response, decrypted_path)

        logger.info(f"[DOWNLOAD TOKEN] ✅ Файл успешно расшифрован и отправляется")

        return FileResponse(
            path=str(decrypted_path),
            filename=file_record.original_name,
            media_type="application/octet-stream"
        )

    except Exception as e:
        logger.error(f"[DOWNLOAD TOKEN] ❌ Ошибка расшифровки: {e}")
        raise HTTPException(status_code=500, detail="Ошибка расшифровки файла")


@router.post("/download")
@limiter.limit("10/minute")
async def download_file_post(
    request: Request,
    background_tasks: BackgroundTasks,
    filename: str = Form(...),
    current_user: TokenData = Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db)
):
    """Скачивание для авторизованных пользователей"""
    logger.info(f"[DOWNLOAD POST] Запрос от {current_user.sub} на файл: {filename}")

    safe_filename = sanitize_filename(filename)
    if not safe_filename.endswith('.age'):
        safe_filename += '.age'

    result = await db.execute(select(File).where(File.encrypted_name == safe_filename))
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(status_code=404, detail="Файл не найден в базе")

    decrypted_path = DECRYPTED_DIR / f"{uuid.uuid4()}_{file_record.original_name}"

    try:
        # Скачиваем из хранилища
        storage_key = file_record.encrypted_path
        encrypted_local_path = DECRYPTED_DIR / f"enc_{uuid.uuid4()}_{safe_filename}"

        await encrypted_storage.download(
            key=storage_key,
            destination_path=encrypted_local_path
        )

        await crypto_manager.decrypt_file(
            encrypted_path=encrypted_local_path,
            private_key_path=PRIVATE_KEY_PATH,
            output_path=decrypted_path
        )

        # Удаляем временный зашифрованный файл
        try:
            if encrypted_local_path.exists():
                encrypted_local_path.unlink()
        except Exception as e:
            logger.warning(f"Не удалось удалить временный зашифрованный файл: {e}")

        background_tasks.add_task(delete_file_after_response, decrypted_path)

        audit_logger.log_operation(
            action="download",
            filename=safe_filename,
            user=current_user.sub,
            reason="Скачивание авторизованным пользователем",
            success=True
        )

        return FileResponse(
            path=str(decrypted_path),
            filename=file_record.original_name,
            media_type="application/octet-stream"
        )

    except Exception as e:
        logger.error(f"[DOWNLOAD POST] Ошибка: {e}")
        raise HTTPException(status_code=500, detail="Ошибка расшифровки файла")
