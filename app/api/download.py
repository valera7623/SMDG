# app/api/download.py
from fastapi import APIRouter, Query, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from app.core.utils import sanitize_filename
from app.core import (
    ENCRYPTED_DIR, DECRYPTED_DIR, PRIVATE_KEY_PATH,
    crypto_manager, API_KEYS, audit_logger
)
from pathlib import Path
import uuid
import urllib.parse
import os

router = APIRouter()



async def _download_file(filename: str, api_key: str, background_tasks: BackgroundTasks):
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    # Используем унифицированную функцию вместо локальной
    safe_filename = sanitize_filename(filename)
    
    # Проверка на path traversal
    if Path(safe_filename).resolve().name != safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    encrypted_path = ENCRYPTED_DIR / f"{safe_filename}.age"  
    
    

@router.get("/download")
async def download_file_get(
    filename: str = Query(...),
    api_key: str = Query(..., alias="x-api-key")
):
    return await _download_file(filename, api_key)

@router.post("/download")
async def download_file_post(
    filename: str = Form(...),
    api_key: str = Form(..., alias="x-api-key")
):
    return await _download_file(filename, api_key)

async def _download_file(filename: str, api_key: str):
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    safe_filename = Path(filename).name
    if '..' in safe_filename or safe_filename.startswith('/'):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    encrypted_path = ENCRYPTED_DIR / safe_filename
    if not encrypted_path.exists() or not safe_filename.endswith('.age'):
        raise HTTPException(status_code=404, detail="File not found")
    
    temp_id = uuid.uuid4().hex
    decrypted_path = DECRYPTED_DIR / f"decrypted_{temp_id}_{safe_filename[:-4]}"
    
    try:
        await crypto_manager.decrypt_file(
            encrypted_path=encrypted_path,
            output_path=decrypted_path,
            private_key_path=PRIVATE_KEY_PATH
        )
        
        original_name = decrypted_path.name[len(f"decrypted_{temp_id}_"):]
        
        audit_logger.log_operation(
            action="download",
            filename=safe_filename,
            user="api_user",
            reason="File downloaded and decrypted",
            success=True,
            metadata={"original_name": original_name}
        )
        
        # === НОВОЕ: Создаём StreamingResponse с генератором ===
        def file_generator():
            try:
                with open(decrypted_path, "rb") as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Гарантированное удаление сразу после отправки всех чанков
                try:
                    if decrypted_path.exists():
                        decrypted_path.unlink()
                        print(f"   Удалён временный файл: {decrypted_path.name}")
                except Exception as e:
                    print(f"   Ошибка удаления временного файла: {e}")
        
        return StreamingResponse(
            file_generator(),
            media_type='application/octet-stream',
            headers={"Content-Disposition": f'attachment; filename="{original_name}"'}
        )
        
    except Exception as e:
        print(f"Ошибка при скачивании {safe_filename}: {e}")
        audit_logger.log_operation(
            action="download",
            filename=safe_filename,
            user="api_user",
            reason=str(e),
            success=False
        )
        # Удаляем файл даже при ошибке
        if decrypted_path.exists():
            try:
                decrypted_path.unlink()
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
