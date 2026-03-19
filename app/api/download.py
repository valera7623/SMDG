# app/api/download.py
import logging
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks, Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from fastapi.responses import FileResponse
from sqlalchemy import select
from datetime import datetime, timezone
from app.core import (
    ENCRYPTED_DIR,
    DECRYPTED_DIR,
    PRIVATE_KEY_PATH,
    audit_logger
)
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.rate_limiter import limiter
from app.crypto.crypto import crypto_manager
from app.core.utils import sanitize_filename
from app.core.auth import get_current_user, get_current_admin, get_current_doctor
from pathlib import Path
import uuid

from app.models.file import File
from app.models.file_link import FileLink

logger = logging.getLogger(__name__)

router = APIRouter()

def delete_file_after_response(path: Path):
    try:
        if path.exists():
            path.unlink()
            print(f"🗑️ Удалён временный файл: {path.name}")
    except Exception as e:
        print(f"Ошибка удаления {path}: {e}")

@router.get("/download")
@limiter.limit("10/minute")
async def download_by_token(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    print(f"Запрос скачивания по токену: {token}")

    stmt = select(FileLink).where(FileLink.token == token)
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()

    if not link:
        print("Ссылка не найдена")
        raise HTTPException(404, "Ссылка не найдена или уже использована")

    print(f"Ссылка найдена: downloads_count={link.downloads_count}/{link.max_downloads}, expires_at={link.expires_at}")

    if link.expires_at and link.expires_at < datetime.now(timezone.utc):
        print("Ссылка истекла")
        await db.delete(link)
        await db.commit()
        raise HTTPException(410, "Ссылка истекла")

    if link.downloads_count >= link.max_downloads:
        print("Лимит исчерпан")
        await db.delete(link)
        await db.commit()
        raise HTTPException(410, "Лимит скачиваний исчерпан")

    stmt = select(File).where(File.id == link.file_id)
    result = await db.execute(stmt)
    file = result.scalar_one_or_none()

    if not file:
        print("Файл не найден")
        raise HTTPException(404, "Файл не найден")

    encrypted_path = Path(file.encrypted_path)
    decrypted_path = DECRYPTED_DIR / f"{uuid.uuid4()}_{file.original_name}"
    print(f"Расшифровка в {decrypted_path}")

    # ИСПРАВЛЕНИЕ: правильный порядок аргументов
    await crypto_manager.decrypt_file(
        encrypted_path=encrypted_path,          # 1: зашифрованный файл
        private_key_path=PRIVATE_KEY_PATH,      # 2: приватный ключ
        output_path=decrypted_path              # 3: куда писать расшифрованный
    )

    link.downloads_count += 1
    print(f"Обновлено: downloads_count = {link.downloads_count}")

    if link.downloads_count >= link.max_downloads:
        print("Удаляем ссылку — лимит достигнут")
        await db.delete(link)

    await db.commit()

    background_tasks.add_task(delete_file_after_response, decrypted_path)

    return FileResponse(
        path=str(decrypted_path),
        filename=file.original_name,
        media_type="application/octet-stream"
    )

@router.post("/download")
@limiter.limit("10/minute")
async def download_file_post(
    request: Request,
    background_tasks: BackgroundTasks,         
    filename: str = Form(...),                  
    current_user: str = Depends(get_current_doctor)  
):
    print(f"Upload от пользователя: {current_user.sub} ({current_user.role})")
    return await _download_file(filename, background_tasks)

# В общей функции порядок тоже важен — без дефолта первым
async def _download_file(
    filename: str,
    background_tasks: BackgroundTasks
):
    # проверка ключа уже сделана через Depends
    safe_filename = sanitize_filename(filename)
    
    if not safe_filename.endswith('.age'):
        raise HTTPException(status_code=400, detail="Имя файла должно заканчиваться на .age")
    
    if Path(safe_filename).name != safe_filename:
        raise HTTPException(status_code=400, detail="Недопустимые символы в имени файла")
    
    encrypted_path = ENCRYPTED_DIR / safe_filename
    
    if not encrypted_path.exists() or not encrypted_path.is_file():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {safe_filename}")
    
    temp_id = uuid.uuid4().hex[:12]
    original_name = safe_filename[:-4]
    decrypted_path = DECRYPTED_DIR / f"dec_{temp_id}_{original_name}"
    
    try:
        # ИСПРАВЛЕНИЕ: правильный порядок аргументов
        await crypto_manager.decrypt_file(
            encrypted_path=encrypted_path,
            private_key_path=PRIVATE_KEY_PATH,
            output_path=decrypted_path
        )
        
        if not decrypted_path.exists() or decrypted_path.stat().st_size == 0:
            raise Exception("Расшифровка не удалась")
        
        audit_logger.log_operation(
            action="download",
            filename=safe_filename,
            user="api_user",
            reason="Успешное скачивание и расшифровка",
            success=True,
            metadata={"original_name": original_name}
        )
        
        background_tasks.add_task(delete_file_after_response, decrypted_path)
        
        return FileResponse(
            path=str(decrypted_path),
            filename=original_name,
            media_type="application/octet-stream"
        )
        
    except Exception as e:
        print(f"Ошибка скачивания {safe_filename}: {e}")
        audit_logger.log_operation(
            action="download",
            filename=safe_filename,
            user="api_user",
            reason=str(e),
            success=False
        )
        if decrypted_path.exists():
            try:
                decrypted_path.unlink()
            except Exception as e:
                logger.warning(f"Не удалось удалить decrypted файл {decrypted_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка скачивания: {str(e)}")
