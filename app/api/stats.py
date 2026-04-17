# app/api/stats.py
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict, Any
import logging
from datetime import datetime
import platform
import psutil
import time
from pathlib import Path

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.tenant import require_tenant, assert_tenant_access
from app.core import (
    ENCRYPTED_DIR, DECRYPTED_DIR, UPLOAD_DIR,
    file_storage, cleanup_manager, audit_logger,
    encrypted_storage
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Вспомогательные функции ====================

def _safe_directory_stats(directory: Path) -> Dict[str, Any]:
    if not directory.exists():
        return {"exists": False, "size_bytes": 0, "file_count": 0}

    total_size = 0
    file_count = 0
    try:
        for item in directory.rglob("*"):
            if item.is_file():
                stat = item.stat()
                total_size += stat.st_size
                file_count += 1
    except Exception as e:
        logger.warning(f"Ошибка подсчёта {directory}: {e}")

    return {
        "exists": True,
        "path": str(directory.absolute()),
        "size_bytes": total_size,
        "file_count": file_count,
    }


def _get_system_stats() -> Dict[str, Any]:
    stats = {
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
    }

    try:
        stats["cpu"] = {
            "percent": psutil.cpu_percent(interval=0.1),
            "count": psutil.cpu_count(logical=True),
        }
    except Exception:
        stats["cpu"] = {"status": "unavailable_in_container"}

    try:
        mem = psutil.virtual_memory()
        stats["memory"] = {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent": mem.percent,
        }
    except Exception:
        stats["memory"] = {"status": "unavailable_in_container"}

    try:
        disk = psutil.disk_usage('/')
        stats["disk"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": disk.percent,
        }
    except Exception:
        stats["disk"] = {"status": "unavailable_in_container"}

    try:
        stats["uptime_seconds"] = round(time.time() - psutil.boot_time(), 0)
    except Exception:
        stats["uptime_seconds"] = "unavailable"

    return stats


async def _get_storage_stats() -> Dict[str, Any]:
    """Получить статистику хранилища (async версия)."""
    try:
        storage_backend_stats = await encrypted_storage.get_storage_stats()
    except Exception as e:
        logger.warning(f"Ошибка получения статистики хранилища: {e}")
        storage_backend_stats = {"error": str(e)}

    dirs = {
        "decrypted": DECRYPTED_DIR,
        "uploads": UPLOAD_DIR,
        "keys": Path("keys"),
        "audit_logs": Path("audit_logs"),
    }
    storage = {}
    total_size = 0

    storage["encrypted"] = storage_backend_stats
    if isinstance(storage_backend_stats, dict):
        total_size += storage_backend_stats.get("total_size_bytes", 0)

    for name, path in dirs.items():
        d = _safe_directory_stats(path)
        storage[name] = d
        total_size += d.get("size_bytes", 0)

    return {
        "directories": storage,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "total_size_gb": round(total_size / (1024**3), 3),
    }


def _get_storage_stats_sync() -> Dict[str, Any]:
    """Синхронная обёртка для обратной совместимости (тесты)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return {"directories": {}, "total_size_bytes": 0, "total_size_mb": 0, "total_size_gb": 0}
        return loop.run_until_complete(_get_storage_stats())
    except RuntimeError:
        return asyncio.run(_get_storage_stats())


async def _get_files_stats() -> Dict[str, Any]:
    """Получить статистику файлов (async версия)."""
    encrypted = []
    try:
        objects = await encrypted_storage.list_objects()
        for obj in objects:
            encrypted.append({
                "name": obj.key,
                "size": obj.size,
                "modified": datetime.fromtimestamp(obj.last_modified).isoformat() if obj.last_modified else "unknown",
            })
    except Exception as e:
        logger.warning(f"Ошибка получения списка зашифрованных файлов: {e}")

    return {
        "encrypted": {
            "count": len(encrypted),
            "total_size_bytes": sum(f["size"] for f in encrypted),
            "files": sorted(encrypted, key=lambda x: x["modified"], reverse=True)[:10] if encrypted else [],
        },
        "temporary": file_storage.get_stats() if hasattr(file_storage, "get_stats") else {},
    }


def _get_files_stats_sync() -> Dict[str, Any]:
    """Синхронная обёртка для обратной совместимости (тесты)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return {"encrypted": {"count": 0, "total_size_bytes": 0, "files": []}, "temporary": {}}
        return loop.run_until_complete(_get_files_stats())
    except RuntimeError:
        return asyncio.run(_get_files_stats())


def _get_cleanup_stats() -> Dict[str, Any]:
    try:
        return {
            "cleanup_manager": cleanup_manager.get_cleanup_stats() if hasattr(cleanup_manager, "get_cleanup_stats") else {},
            "temporary_files": file_storage.get_stats() if hasattr(file_storage, "get_stats") else {},
        }
    except Exception as e:
        logger.error(f"Cleanup stats error: {e}")
        return {"error": str(e)}


# ==================== Основной эндпоинт ====================

@router.get("/stats")
async def get_system_stats(
    request: Request,
    current_user: TokenData = Depends(get_current_admin),
):
    """Полная статистика системы"""
    logger.info(f"📊 Запрос статистики от {current_user.sub} (роль: {current_user.role})")
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)

    try:
        stats = {
            "timestamp": datetime.now().isoformat(),
            "system": _get_system_stats(),
            "storage": await _get_storage_stats(),
            "files": await _get_files_stats(),
            "cleanup": _get_cleanup_stats(),
        }

        stats["summary"] = {
            "total_files": stats["files"]["encrypted"]["count"],
            "total_size_mb": stats["storage"]["total_size_mb"],
            "health": "healthy",
        }

        audit_logger.log_operation(
            action="system_stats_viewed",
            filename="",
            user=current_user.sub,
            reason="Просмотр статистики системы",
            success=True
        )

        return stats

    except Exception as e:
        logger.error(f"❌ Критическая ошибка статистики: {e}", exc_info=True)
        audit_logger.log_operation(
            action="system_stats_error",
            filename="",
            user=current_user.sub,
            reason=str(e),
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Failed to collect stats: {str(e)}")


@router.get("/stats/summary")
async def get_stats_summary(
    request: Request,
    current_user: TokenData = Depends(get_current_admin),
):
    """Краткая сводка"""
    try:
        full = await get_system_stats(request=request, current_user=current_user)
        return {
            "timestamp": full["timestamp"],
            "total_files": full["summary"]["total_files"],
            "total_size_mb": full["summary"]["total_size_mb"],
            "health": "healthy"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
