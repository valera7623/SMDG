# app/api/cleanup.py
from time import time
from fastapi import APIRouter, HTTPException, Query
from app.core import DECRYPTED_DIR, API_KEYS, file_storage
from pathlib import Path
import os

router = APIRouter()

@router.get("/cleanup/stats")
async def get_cleanup_stats(api_key: str = Query(..., alias="x-api-key")):
    """Получить статистику по временным файлам"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    return file_storage.get_stats()

@router.post("/cleanup/force")
async def force_cleanup(api_key: str = Query(..., alias="x-api-key")):
    """Принудительно очистить все временные файлы"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    result = file_storage.force_cleanup()
    return result

@router.get("/cleanup/files")
async def list_temp_files(api_key: str = Query(..., alias="x-api-key")):
    """Список временных файлов"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    files = []
    if DECRYPTED_DIR.exists():
        for file_path in DECRYPTED_DIR.iterdir():
            if file_path.is_file():
                files.append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                    "age_hours": (time.time() - file_path.stat().st_mtime) / 3600
                })
    
    return {
        "count": len(files),
        "directory": str(DECRYPTED_DIR),
        "files": sorted(files, key=lambda x: x["modified"], reverse=True)
    }