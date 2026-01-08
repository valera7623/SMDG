# app/api/cleanup.py
from time import time
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core import DECRYPTED_DIR, file_storage
from app.core.auth import get_current_admin
from pathlib import Path
import os

router = APIRouter()

@router.get("/cleanup/stats")
async def get_cleanup_stats(current_user: str = Depends(get_current_admin)):
    """Получить статистику по временным файлам"""
    return file_storage.get_stats()

@router.post("/cleanup/force")
async def force_cleanup(current_user: str = Depends(get_current_admin)):
    """Принудительно очистить все временные файлы"""
    result = file_storage.force_cleanup()
    return result

@router.get("/cleanup/files")
async def list_temp_files(current_user: str = Depends(get_current_admin)):
    """Список временных файлов"""
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