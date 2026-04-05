# app/api/delete_user.py
from fastapi import APIRouter, HTTPException, Form, Depends, status, Path, Query
from pydantic import BaseModel, Field, ConfigDict
from typing import Annotated, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import asyncio

from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import get_current_user, TokenData
from app.core.utils import calculate_hash_async, sanitize_filename
from app.core.database import get_db
from app.models.file import File
from app.models.user import User
from pathlib import Path as PathlibPath   # ← алиас для работы с файловой системой
import os

router = APIRouter()


# ==================== Pydantic V2 Модели ====================

class DeleteUserFileRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    confirm: bool = Field(False, description="Подтверждение удаления")

    model_config = ConfigDict(extra='ignore')


# ==================== Общая логика удаления по имени ====================

async def _delete_user_file_by_name(
    filename: str,
    confirm: bool,
    current_user: TokenData,
    db: AsyncSession
):
    print(f"🗑️ Пользователь {current_user.sub} запрашивает удаление файла: {filename}")

    safe_filename = sanitize_filename(filename)
    file_path = ENCRYPTED_DIR / safe_filename

    # Автоматически добавляем .age, если не указано
    if not file_path.exists() and not safe_filename.endswith('.age'):
        file_path = ENCRYPTED_DIR / f"{safe_filename}.age"
        safe_filename = f"{safe_filename}.age"

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {safe_filename}")

    # Находим запись в БД
    result = await db.execute(select(File).where(File.encrypted_name == safe_filename))
    db_file = result.scalar_one_or_none()

    # Проверка прав владельца
    if db_file and db_file.user_id:
        result = await db.execute(select(User).where(User.username == current_user.sub))
        user = result.scalar_one_or_none()

        if not user or user.id != db_file.user_id:
            if current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас нет прав на удаление этого файла"
                )

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
        print(f"⚠️ Ошибка получения информации о файле: {e}")

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

        if db_file:
            await db.delete(db_file)
            await db.commit()

        audit_logger.log_operation(
            action="user_delete_file",
            filename=safe_filename,
            user=current_user.sub,
            reason="Удаление файла пользователем",
            metadata=file_info,
            success=True
        )

        return {
            "message": "✅ Файл успешно удален",
            "filename": safe_filename,
            "success": True
        }

    except Exception as e:
        audit_logger.log_operation(
            action="user_delete_file",
            filename=safe_filename,
            user=current_user.sub,
            reason=f"Ошибка удаления: {str(e)}",
            metadata=file_info,
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Ошибка удаления: {str(e)}")


# ==================== Эндпоинты ====================

@router.post("/delete-user-file")
async def delete_user_file(
    filename: str = Form(...),
    confirm: str = Form("false"),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Удаление своего файла по имени"""
    confirm_bool = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    return await _delete_user_file_by_name(filename, confirm_bool, current_user, db)


@router.delete("/delete-user-file/{file_id}")
async def delete_user_file_by_id(
    file_id: Annotated[int, Path(..., description="ID файла")],
    confirm: bool = Query(False),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Удаление своего файла по ID"""
    if not confirm:
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "requires_confirmation": True
        }

    result = await db.execute(select(File).where(File.id == file_id))
    db_file = result.scalar_one_or_none()

    if not db_file:
        raise HTTPException(status_code=404, detail=f"Файл с ID {file_id} не найден")

    # Проверка прав
    if db_file.user_id:
        result = await db.execute(select(User).where(User.username == current_user.sub))
        user = result.scalar_one_or_none()
        if not user or user.id != db_file.user_id:
            if current_user.role != "admin":
                raise HTTPException(status_code=403, detail="У вас нет прав на удаление этого файла")

    file_path = ENCRYPTED_DIR / db_file.encrypted_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл на диске не найден")

    try:
        os.remove(file_path)
        await db.delete(db_file)
        await db.commit()

        audit_logger.log_operation(
            action="user_delete_file",
            filename=db_file.encrypted_name,
            user=current_user.sub,
            reason=f"Удаление файла по ID {file_id}",
            success=True
        )

        return {
            "message": "✅ Файл успешно удален",
            "id": file_id,
            "original_name": db_file.original_name,
            "success": True
        }

    except Exception as e:
        audit_logger.log_operation(
            action="user_delete_file",
            filename=db_file.encrypted_name,
            user=current_user.sub,
            reason=f"Ошибка удаления: {str(e)}",
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Ошибка удаления: {str(e)}")