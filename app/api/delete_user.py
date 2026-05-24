# app/api/delete_user.py
from fastapi import APIRouter, HTTPException, Form, Depends, status, Path, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from typing import Annotated, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import asyncio

from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import get_current_user, TokenData
from app.core.demo_guard import assert_demo_file_deletable
from app.core.utils import calculate_hash_async, sanitize_filename
from app.core.database import get_db
from app.models.file import File
from app.models.user import User
from app.core.tenant import require_tenant, assert_tenant_access
from pathlib import Path as PathlibPath   # ← алиас для работы с файловой системой
import os

router = APIRouter()


async def _find_file_by_encrypted_name(
    db: AsyncSession, tenant_id: int, filename: str
) -> File | None:
    """Resolve File row by encrypted_name (exact match, then optional .age suffix)."""
    safe_filename = sanitize_filename(filename)
    result = await db.execute(
        select(File).where(
            File.tenant_id == tenant_id,
            File.encrypted_name == safe_filename,
        )
    )
    db_file = result.scalar_one_or_none()
    if db_file:
        return db_file
    if not safe_filename.endswith(".age"):
        result = await db.execute(
            select(File).where(
                File.tenant_id == tenant_id,
                File.encrypted_name == f"{safe_filename}.age",
            )
        )
        return result.scalar_one_or_none()
    return None


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
    from app.core import encrypted_storage
    print(f"🗑️ Пользователь {current_user.sub} запрашивает удаление файла: {filename}")

    safe_filename = sanitize_filename(filename)

    # Ищем запись в БД по encrypted_name (без принудительного .age — demo/legacy имена)
    db_file = await _find_file_by_encrypted_name(db, current_user.tenant_id, safe_filename)

    if not db_file:
        raise HTTPException(status_code=404, detail=f"Файл не найден в БД: {safe_filename}")

    assert_demo_file_deletable(db_file)
    safe_filename = db_file.encrypted_name

    # Проверяем наличие файла через storage backend (S3 или локальная ФС)
    storage_key = db_file.encrypted_path
    file_exists = await encrypted_storage.exists(storage_key)

    if not file_exists:
        raise HTTPException(status_code=404, detail=f"Файл не найден в хранилище: {safe_filename}")

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
        "storage_key": storage_key,
        "size": db_file.encrypted_size or 0,
        "hash": db_file.original_hash or "unknown"
    }

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
        # Удаляем из хранилища (S3 или локальная ФС)
        await encrypted_storage.delete(storage_key)

        # Удаляем запись из БД
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
    request: Request,
    filename: str = Form(...),
    confirm: str = Form("false"),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Удаление своего файла по имени"""
    confirm_bool = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    return await _delete_user_file_by_name(filename, confirm_bool, current_user, db)


@router.delete("/delete-user-file/{file_id}")
async def delete_user_file_by_id(
    request: Request,
    file_id: Annotated[int, Path(..., description="ID файла")],
    confirm: bool = Query(False),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Удаление своего файла по ID"""
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    # 1. Ищем запись в БД
    result = await db.execute(select(File).where(File.id == file_id, File.tenant_id == tenant.id))
    db_file = result.scalar_one_or_none()

    if not db_file:
        raise HTTPException(status_code=404, detail=f"Файл с ID {file_id} не найден")

    assert_demo_file_deletable(db_file)

    # 2. Проверка прав владельца
    if db_file.user_id:
        result = await db.execute(
            select(User).where(User.username == current_user.sub, User.tenant_id == tenant.id)
        )
        user = result.scalar_one_or_none()
        if not user or user.id != db_file.user_id:
            if current_user.role != "admin":
                raise HTTPException(status_code=403, detail="У вас нет прав на удаление этого файла")

    # 3. Проверяем наличие файла на диске
    file_path = ENCRYPTED_DIR / db_file.encrypted_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл на диске не найден")

    # 4. Требуется подтверждение
    if not confirm:
        try:
            size = file_path.stat().st_size
        except Exception:
            size = 0
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "file_info": {
                "id": file_id,
                "name": db_file.encrypted_name,
                "size": size,
                "requires_confirmation": True,
            },
            "confirmation_required": True
        }

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