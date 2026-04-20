"""Health-эндпоинты SMDG.

- ``/health/live``     — liveness probe: процесс жив.
- ``/health/ready``    — readiness probe: готов принимать трафик
                         (проверка БД, Redis, объектного хранилища).
                         Возвращает 503, если идёт graceful shutdown.
- ``/health/features`` — фичи и профиль развёртывания (прежний API).
- ``/health/deployment`` — информация о типе развёртывания (прежний API).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.feature_flags import get_deployment_info

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────
# Liveness / Readiness
# ──────────────────────────────────────────────────────────────────────

@router.get("/health/live", summary="Liveness probe")
async def liveness_check() -> Dict[str, Any]:
    """Liveness probe — всегда 200, пока процесс жив.

    Используется Docker/Kubernetes для перезапуска зависших контейнеров.
    Не проверяет внешние зависимости (БД/Redis), так как их падение
    не должно приводить к рестарту SMDG.
    """
    return {"status": "alive", "timestamp": _utcnow_iso()}


@router.get("/health/ready", summary="Readiness probe")
async def readiness_check(request: Request) -> JSONResponse:
    """Readiness probe — готов ли сервис принимать трафик.

    Возвращает:
    - ``200 OK``    — все проверки зависимостей прошли успешно.
    - ``503``       — идёт graceful shutdown или одна из зависимостей
                      недоступна (оркестратор снимет трафик).
    """
    app_state = request.app.state

    if getattr(app_state, "shutting_down", False):
        active = getattr(app_state, "active_requests", 0)
        return JSONResponse(
            status_code=503,
            content={
                "status": "shutting_down",
                "message": "Service is gracefully shutting down",
                "active_requests": active,
                "timestamp": _utcnow_iso(),
            },
            headers={"Retry-After": "30"},
        )

    db_ok, redis_ok, storage_ok = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_storage(),
        return_exceptions=False,
    )

    checks = {
        "database": db_ok,
        "redis": redis_ok,
        "storage": storage_ok,
    }

    all_ok = all(checks.values())
    status_code = 200 if all_ok else 503
    payload: Dict[str, Any] = {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
        "timestamp": _utcnow_iso(),
    }
    return JSONResponse(status_code=status_code, content=payload)


# ──────────────────────────────────────────────────────────────────────
# Зависимости (БД / Redis / Storage)
# ──────────────────────────────────────────────────────────────────────

async def _check_database() -> bool:
    """Проверка доступности PostgreSQL (``SELECT 1``)."""
    try:
        from app.core.database import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("Readiness: база данных недоступна: %s", e)
        return False


async def _check_redis() -> bool:
    """Проверка доступности Redis (``PING``)."""
    try:
        from app.core.rate_limiter import redis_client

        pong = await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        return bool(pong)
    except Exception as e:
        logger.warning("Readiness: Redis недоступен: %s", e)
        return False


async def _check_storage() -> bool:
    """Проверка доступности хранилища (локальное/S3).

    Для локального бэкенда — проверяем существование директории.
    Для S3 — дешёвый ``list_objects`` (1 элемент).
    """
    try:
        from app.core import encrypted_storage
        from app.core.storage_backend import LocalStorageBackend, S3StorageBackend

        if isinstance(encrypted_storage, LocalStorageBackend):
            base = getattr(encrypted_storage, "base_dir", None)
            return bool(base and base.exists())

        if isinstance(encrypted_storage, S3StorageBackend):
            client = await encrypted_storage._get_client()
            await asyncio.wait_for(
                client.list_objects_v2(Bucket=encrypted_storage.bucket, MaxKeys=1),
                timeout=3.0,
            )
            return True

        return True
    except Exception as e:
        logger.warning("Readiness: хранилище недоступно: %s", e)
        return False


# ──────────────────────────────────────────────────────────────────────
# Совместимость со старым API
# ──────────────────────────────────────────────────────────────────────

@router.get("/health/features", summary="Feature flags")
async def health_features() -> Dict[str, Any]:
    """Список фич и их состояние для текущего ``DEPLOYMENT_TYPE``."""
    info = get_deployment_info()
    return {
        "deployment_type": info["deployment_type"],
        "features": info["features"],
        "features_enabled": info["features_enabled"],
    }


@router.get("/health/deployment", summary="Deployment profile")
async def health_deployment() -> Dict[str, Any]:
    """Информация о типе развёртывания и связанных параметрах."""
    return get_deployment_info()
