# app/api/list.py
from fastapi import APIRouter, Query, HTTPException
from app.core import ENCRYPTED_DIR, API_KEYS
from pathlib import Path
import os

router = APIRouter()

@router.get("/list")
async def list_files(api_key: str = Query(..., alias="x-api-key")):
    """Получить список зашифрованных файлов"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    print(f"📋 Запрос списка файлов из {ENCRYPTED_DIR}")
    
    files = []
    if ENCRYPTED_DIR.exists():
        for file_path in ENCRYPTED_DIR.iterdir():
            if file_path.is_file() and file_path.suffix == '.age':
                try:
                    stat = file_path.stat()
                    files.append({
                        "name": file_path.name,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "original_name": file_path.name.replace('.age', '')
                    })
                except Exception as e:
                    print(f"Ошибка чтения файла {file_path}: {e}")
    
    # Сортируем по времени изменения (новые сверху)
    files.sort(key=lambda x: x["modified"], reverse=True)
    
    print(f"📋 Найдено {len(files)} файлов")
    
    return {
        "count": len(files),
        "files": files
    }