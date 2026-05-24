# app/api/delete.py
from fastapi import APIRouter, HTTPException, Form, Request, Depends
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core import ENCRYPTED_DIR, audit_logger, encrypted_storage
from app.core.webhook import webhook_dispatcher
from app.core.auth import get_current_admin, TokenData
from app.core.demo_guard import assert_demo_file_deletable
from app.core.utils import calculate_hash_async, sanitize_filename
from app.core.database import get_db
from app.core.tenant import require_tenant, assert_tenant_access
from app.models.file import File
from pathlib import Path
import asyncio

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
    current_user: TokenData,
    tenant_id: int,
    db: AsyncSession,
):
    print(f"🗑️ Запрос на удаление: {filename} от {current_user.sub} ({current_user.role})")

    safe_filename = sanitize_filename(filename)

    stmt = select(File).where(File.tenant_id == tenant_id, File.encrypted_name == safe_filename)
    if not safe_filename.endswith(".age"):
        stmt = select(File).where(
            File.tenant_id == tenant_id,
            File.encrypted_name.in_([safe_filename, f"{safe_filename}.age"]),
        )
    file_row = (await db.execute(stmt)).scalars().first()
    if not file_row:
        raise HTTPException(status_code=404, detail=f"Файл не найден: {safe_filename}")
    assert_demo_file_deletable(file_row)
    storage_key = file_row.encrypted_path
    safe_filename = file_row.encrypted_name

    # Информация для аудита
    file_info = {
        "filename": safe_filename,
        "path": storage_key,
        "size": 0,
        "hash": "unknown"
    }

    try:
        metadata = await encrypted_storage.stat(storage_key)
        if metadata:
            file_info["size"] = metadata.size
            # Для хэша скачиваем и считаем
            temp_path = ENCRYPTED_DIR / f"temp_hash_{safe_filename}"
            await encrypted_storage.download(storage_key, temp_path)
            file_info["hash"] = await calculate_hash_async(temp_path)
            temp_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"⚠️ Не удалось получить информацию о файле: {e}")

    # Требуется подтверждение
    if not confirm:
        hash_val = file_info["hash"]
        truncated_hash = (hash_val[:20] + "...") if isinstance(hash_val, str) and len(hash_val) > 20 else hash_val
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "file_info": {
                "name": safe_filename,
                "size": file_info["size"],
                "hash": truncated_hash,
                "requires_confirmation": True
            },
            "confirmation_required": True
        }

    try:
        await encrypted_storage.delete(storage_key)
        await db.delete(file_row)
        await db.commit()

        audit_logger.log_operation(
            action="delete",
            filename=safe_filename,
            user=current_user.sub,
            reason=reason or "Ручное удаление администратором",
            metadata=file_info,
            success=True
        )

        # Отправляем webhook-уведомление
        asyncio.create_task(
            webhook_dispatcher.dispatch(
                event="file.deleted",
                data={
                    "filename": safe_filename,
                    "size": file_info["size"],
                    "deleted_by": current_user.sub,
                    "reason": reason or "Ручное удаление администратором",
                },
                tenant_id=tenant_id,
            )
        )

        return {
            "message": "✅ Файл успешно удален",
            "filename": safe_filename,
            "size": file_info["size"],
            "hash": file_info["hash"],
            "audit_logged": True,
            "timestamp": None,
        }

    except Exception as e:
        audit_logger.log_operation(
            action="delete",
            filename=safe_filename,
            user=current_user.sub,
            reason=reason or f"Ручное удаление администратором (ошибка: {str(e)})",
            metadata=file_info,
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


# ==================== Эндпоинты ====================

@router.post("/delete")
async def delete_file(
    request: Request,
    filename: str = Form(...),
    confirm: str = Form("false"),
    reason: str = Form(""),
    current_user: TokenData = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Удаление файла администратором (POST)"""
    confirm_bool = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    return await _delete_file(filename, confirm_bool, reason, current_user, tenant.id, db)

