import datetime
from datetime import datetime, timezone
from time import time
from fastapi import APIRouter, HTTPException, Depends, Query
from app.core import DECRYPTED_DIR, file_storage, audit_logger
from app.core.auth import get_current_admin
from pathlib import Path
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cleanup", tags=["Cleanup"])

@router.get("/stats")
async def get_cleanup_stats(current_user=Depends(get_current_admin)):
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
        raise HTTPException(500, "Ошибка получения статистики")


@router.post("/force")
async def force_cleanup(current_user=Depends(get_current_admin)):
    """Принудительно очистить ВСЕ файлы (decrypted + encrypted)"""
    deleted = {"decrypted": 0, "encrypted": 0}
    errors = []

    # 1. Очистка decrypted (временные)
    try:
        result_dec = file_storage.force_cleanup()
        deleted["decrypted"] = result_dec.get("deleted", 0)
    except Exception as e:
        errors.append(f"decrypted: {str(e)}")

    # 2. Очистка encrypted (зашифрованные файлы)
    encrypted_dir = Path("/app/encrypted")  # или из constants.ENCRYPTED_DIR
    if encrypted_dir.exists():
        for file_path in encrypted_dir.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    deleted["encrypted"] += 1
                    audit_logger.log_operation(
                        action="force_cleanup_encrypted",
                        filename=file_path.name,
                        user=current_user.sub,
                        reason="Полная очистка encrypted по запросу админа",
                        success=True
                    )
                except Exception as e:
                    errors.append(f"encrypted/{file_path.name}: {str(e)}")
                    audit_logger.log_operation(
                        action="force_cleanup_encrypted_error",
                        filename=file_path.name,
                        user=current_user.sub,
                        reason=str(e),
                        success=False
                    )

    audit_logger.log_operation(
        action="cleanup_force_all",
        filename="",
        user=current_user.sub,
        reason=f"Удалено decrypted: {deleted['decrypted']}, encrypted: {deleted['encrypted']}",
        success=True,
        metadata={"deleted": deleted}
    )

    return {
        "status": "ok",
        "deleted": deleted,
        "errors": errors
    }


@router.get("/files")
async def list_temp_files(
    current_user=Depends(get_current_admin),
    limit: int = Query(100, ge=1, le=1000, description="Макс. количество файлов в ответе")
):
    """Список временных файлов (с лимитом)"""
    files: List[Dict] = []
    
    if not DECRYPTED_DIR.exists():
        return {"count": 0, "directory": str(DECRYPTED_DIR), "files": []}

    try:
        for file_path in DECRYPTED_DIR.iterdir():
            if len(files) >= limit:
                break
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    age_hours = (time() - stat.st_mtime) / 3600
                    files.append({
                        "name": file_path.name,
                        "size_bytes": stat.st_size,
                        "modified_iso": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "age_hours": round(age_hours, 2)
                    })
                except (FileNotFoundError, PermissionError) as e:
                    logger.warning(f"Не удалось получить stat для {file_path}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Неизвестная ошибка stat {file_path}: {e}")
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
            "total_scanned": len(list(DECRYPTED_DIR.iterdir())),  # для информации
            "directory": str(DECRYPTED_DIR),
            "files": sorted(files, key=lambda x: x["modified_iso"], reverse=True)
        }
    except Exception as e:
        logger.error(f"Ошибка в list_temp_files: {e}")
        audit_logger.log_operation(
            action="cleanup_files_error",
            filename="",
            user=current_user.sub,
            reason=str(e),
            success=False
        )
        raise HTTPException(500, "Ошибка при получении списка файлов")