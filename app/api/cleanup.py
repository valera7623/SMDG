# app/api/cleanup.py
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from typing import Annotated, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from time import time

from app.core import DECRYPTED_DIR, file_storage, audit_logger, cleanup_manager, encrypted_storage
from app.core.auth import get_current_admin, TokenData
from app.core.constants import ENCRYPTED_DIR
from app.core.database import get_db
from app.core.tenant import require_tenant, assert_tenant_access
import logging

router = APIRouter(prefix="/cleanup", tags=["Cleanup"])
logger = logging.getLogger(__name__)


# ==================== Pydantic V2 Модели ====================

class ForceCleanupResponse(BaseModel):
    status: str
    deleted: dict
    errors: list = Field(default_factory=list)

    model_config = ConfigDict(extra='ignore')


# ==================== Эндпоинты ====================

@router.get("/stats")
async def get_cleanup_stats(
    request: Request,
    current_user: TokenData = Depends(get_current_admin)
):
    """Получить статистику по временным файлам"""
    try:
        tenant = require_tenant(request)
        assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
        stats = file_storage.get_stats()

        audit_logger.log_operation(
            action="cleanup_stats_viewed",
            filename="",
            user=current_user.sub,
            reason="Просмотр статистики временных файлов",
            success=True
        )

        return stats

    except Exception as e:
        logger.error(f"Ошибка получения статистики cleanup: {e}")
        audit_logger.log_operation(
            action="cleanup_stats_error",
            filename="",
            user=current_user.sub,
            reason=str(e),
            success=False
        )
        raise HTTPException(status_code=500, detail="Ошибка получения статистики")


@router.get("/files")
async def list_temp_files(
    request: Request,
    current_user: TokenData = Depends(get_current_admin),
    limit: int = Query(100, ge=1, le=1000, description="Максимальное количество файлов в ответе")
):
    """Список временных файлов (decrypted)"""
    files = []

    if not DECRYPTED_DIR.exists():
        return {
            "count": 0,
            "directory": str(DECRYPTED_DIR),
            "files": []
        }

    try:
        tenant = require_tenant(request)
        assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
        for file_path in DECRYPTED_DIR.iterdir():
            if len(files) >= limit:
                break
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    age_hours = round((time() - stat.st_mtime) / 3600, 2)
                    files.append({
                        "name": file_path.name,
                        "size_bytes": stat.st_size,
                        "modified_iso": stat.st_mtime,
                        "age_hours": age_hours
                    })
                except Exception as e:
                    logger.warning(f"Не удалось получить stat для {file_path}: {e}")
                    continue

        audit_logger.log_operation(
            action="cleanup_files_listed",
            filename="",
            user=current_user.sub,
            reason=f"Просмотр списка временных файлов (limit={limit})",
            success=True,
            metadata={"count_returned": len(files)}
        )

        return {
            "count": len(files),
            "total_scanned": len(list(DECRYPTED_DIR.iterdir())),
            "directory": str(DECRYPTED_DIR),
            "files": sorted(files, key=lambda x: x["modified_iso"], reverse=True)
        }

    except Exception as e:
        logger.error(f"Ошибка при получении списка временных файлов: {e}")
        audit_logger.log_operation(
            action="cleanup_files_error",
            filename="",
            user=current_user.sub,
            reason=str(e),
            success=False
        )
        raise HTTPException(status_code=500, detail="Ошибка при получении списка файлов")


@router.post("/force")
async def force_cleanup(
    request: Request,
    current_user: TokenData = Depends(get_current_admin)
):
    """Принудительная полная очистка всех временных и зашифрованных файлов"""
    deleted = {"decrypted": 0, "encrypted": 0}
    errors = []

    logger.info(f"[FORCE CLEANUP] Запущена принудительная очистка пользователем {current_user.sub}")
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)

    # 1. Очистка decrypted (временные файлы)
    try:
        result_dec = file_storage.force_cleanup()
        deleted["decrypted"] = result_dec.get("deleted", 0)
        if result_dec.get("errors"):
            errors.extend(result_dec["errors"])
    except Exception as e:
        errors.append(f"decrypted: {str(e)}")
        logger.error(f"Ошибка очистки decrypted: {e}")

    # 2. Очистка encrypted (зашифрованные файлы через StorageBackend)
    try:
        objects = await encrypted_storage.list_objects()
        keys_to_delete = [obj.key for obj in objects]

        if keys_to_delete:
            result_enc = await encrypted_storage.delete_many(keys_to_delete)
            deleted["encrypted"] = result_enc.get("deleted_count", 0)
            if result_enc.get("errors"):
                errors.extend(result_enc["errors"])
    except Exception as e:
        errors.append(f"encrypted: {str(e)}")
        logger.error(f"Ошибка очистки encrypted: {e}")

    # Логирование в аудит
    audit_logger.log_operation(
        action="cleanup_force_all",
        filename="",
        user=current_user.sub,
        reason=f"Принудительная очистка: decrypted={deleted['decrypted']}, encrypted={deleted['encrypted']}",
        success=len(errors) == 0,
        metadata={"deleted": deleted, "errors": errors}
    )

    return ForceCleanupResponse(
        status="ok" if len(errors) == 0 else "partial",
        deleted=deleted,
        errors=errors
    )