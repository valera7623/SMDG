# app/api/delete.py
from fastapi import APIRouter, HTTPException, Form, Query, Request, Depends, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import get_current_admin, TokenData
from app.core.utils import calculate_hash_async, sanitize_filename
from app.core.database import get_db
from pathlib import Path
import os

router = APIRouter()


# ==================== Pydantic V2 Модель ====================

class DeleteRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    confirm: bool = Field(False, description="Подтверждение удаления")
    reason: str = Field("", description="Причина удаления (опционально)")

    model_config = ConfigDict(extra='ignore')


# ==================== Общая логика удаления ====================

async def _delete_file(
    filename: str,
    confirm: bool,
    reason: str,
    current_user: TokenData
):
    print(f"🗑️ Запрос на удаление: {filename} от {current_user.sub} ({current_user.role})")

    safe_filename = sanitize_filename(filename)
    file_path = ENCRYPTED_DIR / safe_filename

    # Автоматически добавляем .age, если не указано
    if not file_path.exists() and not safe_filename.endswith('.age'):
        file_path = ENCRYPTED_DIR / f"{safe_filename}.age"
        safe_filename = f"{safe_filename}.age"

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {safe_filename}")

    # Информация для аудита
    file_info = {
        "filename": safe_filename,
        "path": str(file_path),
        "size": 0,
        "hash": "unknown"
    }

    try:
        stat = file_path.stat()
        file_info["size"] = stat.st_size
        file_info["hash"] = await calculate_hash_async(file_path)
    except Exception as e:
        print(f"⚠️ Не удалось получить информацию о файле: {e}")

    # Требуется подтверждение
    if not confirm:
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "file_info": {
                "name": safe_filename,
                "size": file_info["size"],
                "requires_confirmation": True
            },
            "confirmation_required": True
        }

    try:
        os.remove(file_path)

        audit_logger.log_operation(
            action="delete",
            filename=safe_filename,
            user=current_user.sub,
            reason=reason or "Ручное удаление администратором",
            metadata=file_info,
            success=True
        )

        return {
            "message": "✅ Файл успешно удален",
            "filename": safe_filename,
            "size": file_info["size"]
        }

    except Exception as e:
        audit_logger.log_operation(
            action="delete",
            filename=safe_filename,
            user=current_user.sub,
            reason=f"Ошибка удаления: {str(e)}",
            metadata=file_info,
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


# ==================== Эндпоинты ====================

@router.post("/delete")
async def delete_file(
    filename: str = Form(...),
    confirm: str = Form("false"),
    reason: str = Form(""),
    current_user: TokenData = Depends(get_current_admin)
):
    """Удаление файла администратором (POST)"""
    confirm_bool = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    return await _delete_file(filename, confirm_bool, reason, current_user)


@router.get("/delete")
async def delete_file_get(
    filename: str = Query(...),
    confirm: str = Query("false"),
    reason: str = Query(""),
    current_user: TokenData = Depends(get_current_admin)
):
    """Удаление файла администратором (GET — для совместимости)"""
    confirm_bool = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    return await _delete_file(filename, confirm_bool, reason, current_user)



