# app/api/download.py
from fastapi import APIRouter, Query, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from app.core import (
    ENCRYPTED_DIR,
    DECRYPTED_DIR,
    PRIVATE_KEY_PATH,
    crypto_manager,
    audit_logger
)
from app.core.utils import sanitize_filename
from app.core.auth import verify_api_key
from pathlib import Path
import uuid

router = APIRouter()

def delete_file_after_response(path: Path):
    try:
        if path.exists():
            path.unlink()
            print(f"🗑️ Удалён временный файл: {path.name}")
    except Exception as e:
        print(f"Ошибка удаления {path}: {e}")

# ПРАВИЛЬНЫЙ ПОРЯДОК: сначала без дефолта, потом с дефолтом
@router.get("/download")
async def download_file_get(
    background_tasks: BackgroundTasks,          # ← сначала (без дефолта)
    filename: str = Query(...),                 # ← потом с дефолтом
    current_key: str = Depends(verify_api_key)  # ← с дефолтом
):
    return await _download_file(filename, background_tasks)

@router.post("/download")
async def download_file_post(
    background_tasks: BackgroundTasks,          # ← сначала
    filename: str = Form(...),                  # ← потом с дефолтом
    current_key: str = Depends(verify_api_key)  # ← с дефолтом
):
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
        await crypto_manager.decrypt_file(
            encrypted_path=encrypted_path,
            output_path=decrypted_path,
            private_key_path=PRIVATE_KEY_PATH
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
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Ошибка скачивания: {str(e)}")
