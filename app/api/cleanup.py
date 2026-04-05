# app/api/cleanup.py
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, ConfigDict
from typing import Annotated, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import DECRYPTED_DIR, file_storage, audit_logger, cleanup_manager
from app.core.auth import get_current_admin, TokenData
from app.core.constants import ENCRYPTED_DIR
from app.core.database import get_db
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
    current_user: TokenData = Depends(get_current_admin)
):
    """Получить статистику по временным файлам"""
    try:
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
        for file_path in DECRYPTED_DIR.iterdir():
            if len(files) >= limit:
                break
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    age_hours = (stat.st_mtime - stat.st_ctime) / 3600 if stat.st_ctime else 0
                    files.append({
                        "name": file_path.name,
                        "size_bytes": stat.st_size,
                        "modified_iso": stat.st_mtime,
                        "age_hours": round(age_hours, 2)
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
    current_user: TokenData = Depends(get_current_admin)
):
    """Принудительная полная очистка всех временных и зашифрованных файлов"""
    deleted = {"decrypted": 0, "encrypted": 0}
    errors = []

    logger.info(f"[FORCE CLEANUP] Запущена принудительная очистка пользователем {current_user.sub}")

    # 1. Очистка decrypted (временные файлы)
    try:
        result_dec = file_storage.force_cleanup()
        deleted["decrypted"] = result_dec.get("deleted", 0)
        if result_dec.get("errors"):
            errors.extend(result_dec["errors"])
    except Exception as e:
        errors.append(f"decrypted: {str(e)}")
        logger.error(f"Ошибка очистки decrypted: {e}")

    # 2. Очистка encrypted (зашифрованные файлы)
    try:
        for file_path in ENCRYPTED_DIR.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    deleted["encrypted"] += 1
                    logger.info(f"🗑️ Удалён зашифрованный файл: {file_path.name}")
                except Exception as e:
                    errors.append(f"encrypted/{file_path.name}: {str(e)}")
                    logger.error(f"Не удалось удалить {file_path}: {e}")
    except Exception as e:
        errors.append(f"encrypted directory error: {str(e)}")
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