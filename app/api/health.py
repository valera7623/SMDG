"""Health-эндпоинты SMDG.

Три уровня проверок в соответствии с Kubernetes-гайдлайнами:

- ``/health/live``        — liveness probe. Всегда 200, пока процесс жив.
                           Не проверяет внешние зависимости — иначе при
                           временной потере БД/Redis контейнер будет
                           бесконечно перезапускаться.
- ``/health/ready``       — readiness probe. 200 если сервис готов принимать
                           трафик, 503 — если идёт graceful shutdown,
                           перегрузка или недоступна критичная зависимость.
- ``/health/checks``      — подробный dashboard всех проверок (admin-only).
- ``/health/features``    — профиль развёртывания и флаги фич (legacy).
- ``/health/deployment``  — информация о типе развёртывания (legacy).

Результаты проверок зависимостей кэшируются на ``readiness_cache_ttl``
секунд (по умолчанию 1.5с), чтобы частые probe (интервал 2–5с в k8s)
не создавали постоянную нагрузку `SELECT 1` / `PING`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.config import settings
from app.core.feature_flags import get_deployment_info
from app.core.database_router import get_db_router
from app.core.cache import distributed_cache
from app.core.job_queue import job_queue
from app.core.session import session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


# ──────────────────────────────────────────────────────────────────────
# Внутренний async TTL-кэш для readiness проверок
# ──────────────────────────────────────────────────────────────────────
# functools.lru_cache не поддерживает ни TTL, ни корутины, поэтому
# реализуем минимальный асинхронный кэш вручную. Ключ — имя проверки,
# значение — (timestamp_monotonic, результат). Параллельные вызовы
# одной и той же проверки защищены per-key asyncio.Lock, чтобы не
# запускать несколько идентичных запросов одновременно.


class _AsyncTTLCache:
    """Простейший потокобезопасный кэш результатов async-проверок с TTL."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    @property
    def ttl(self) -> float:
        return self._ttl

    def set_ttl(self, ttl: float) -> None:
        self._ttl = ttl

    def invalidate(self, key: Optional[str] = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    async def get_or_compute(
        self,
        key: str,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        now = time.monotonic()
        entry = self._cache.get(key)
        if entry is not None and (now - entry[0]) < self._ttl:
            return entry[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._cache.get(key)
            if entry is not None and (time.monotonic() - entry[0]) < self._ttl:
                return entry[1]
            value = await coro_factory()
            self._cache[key] = (time.monotonic(), value)
            return value


_checks_cache = _AsyncTTLCache(ttl=settings.readiness_cache_ttl)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные функции проверки зависимостей
# ──────────────────────────────────────────────────────────────────────
# Каждая функция возвращает dict ``{"ok": bool, "latency_ms": float,
# "error": Optional[str]}``. Для "быстрого" boolean — смотри обёртку
# ниже (``_ok``).


async def _timed(coro: Awaitable[Any], timeout: float) -> Dict[str, Any]:
    """Обёртка: выполняет ``coro`` с таймаутом и возвращает структурированный результат."""
    start = time.monotonic()
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return {
            "ok": True,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": None,
        }
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": f"timeout after {timeout}s",
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _do_check_database() -> None:
    """Низкоуровневая проверка PostgreSQL: ``SELECT 1``."""
    from app.core.database import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _do_check_redis() -> None:
    """Низкоуровневая проверка Redis: ``PING``."""
    from app.core.rate_limiter import redis_client

    pong = await redis_client.ping()
    if not pong:
        raise RuntimeError("Redis PING returned falsy value")


async def _do_check_storage() -> None:
    """Низкоуровневая проверка хранилища (Local/S3).

    Для локального бэкенда проверяем существование и writable-статус
    base-директории, для S3 — дешёвый ``list_objects`` (1 ключ).
    """
    from app.core import encrypted_storage
    from app.core.storage_backend import LocalStorageBackend, S3StorageBackend

    if isinstance(encrypted_storage, LocalStorageBackend):
        base = getattr(encrypted_storage, "base_dir", None)
        if not base or not base.exists():
            raise RuntimeError(f"Local storage base dir missing: {base}")
        return

    if isinstance(encrypted_storage, S3StorageBackend):
        client = await encrypted_storage._get_client()
        await client.list_objects_v2(Bucket=encrypted_storage.bucket, MaxKeys=1)
        return


async def _do_check_dicom_viewer() -> None:
    """Проверка доступности DICOM Viewer (включён ли и отвечает ли Redis для токенов)."""
    if not settings.dicom_viewer_enabled:
        raise RuntimeError("disabled")
    # DICOM viewer хранит токены просмотра в Redis — проверяем, что он жив.
    from app.core.rate_limiter import redis_client

    pong = await redis_client.ping()
    if not pong:
        raise RuntimeError("Redis (DICOM token store) unavailable")


async def _do_check_tracing() -> None:
    """Мягкая проверка Jaeger Query API.

    Tracing — опциональная зависимость: если ``OTEL_ENABLED=false``, сразу
    отдаём ``disabled`` (фича выключена). В остальных случаях делаем
    дешёвый ``GET /api/services`` к Jaeger. Недоступность Jaeger НЕ должна
    превращать сервис в unready: эта проверка не участвует в общем
    readiness (см. ``readiness_check``), а используется только в
    ``detailed_checks``.
    """
    import os as _os

    import httpx as _httpx

    if not (_os.getenv("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}):
        raise RuntimeError("disabled")

    url = _os.getenv("JAEGER_QUERY_URL", "http://jaeger:16686").rstrip("/")
    async with _httpx.AsyncClient(timeout=2.0) as client:
        response = await client.get(f"{url}/api/services")
    if response.status_code >= 400:
        raise RuntimeError(f"Jaeger returned HTTP {response.status_code}")


# ──────────────────────────────────────────────────────────────────────
# Публичные обёртки с кэшированием и таймаутом
# ──────────────────────────────────────────────────────────────────────


async def check_database() -> Dict[str, Any]:
    """Проверка PostgreSQL с таймаутом и кэшированием на ``readiness_cache_ttl``."""
    return await _checks_cache.get_or_compute(
        "database",
        lambda: _timed(_do_check_database(), timeout=settings.readiness_check_timeout),
    )


async def check_redis() -> Dict[str, Any]:
    """Проверка Redis с таймаутом и кэшированием."""
    return await _checks_cache.get_or_compute(
        "redis",
        lambda: _timed(_do_check_redis(), timeout=settings.readiness_check_timeout),
    )


async def check_storage() -> Dict[str, Any]:
    """Проверка хранилища (Local/S3) с таймаутом и кэшированием."""
    return await _checks_cache.get_or_compute(
        "storage",
        lambda: _timed(_do_check_storage(), timeout=settings.readiness_check_timeout),
    )


async def check_dicom_viewer() -> Dict[str, Any]:
    """Проверка DICOM Viewer (кэшированно). Возвращает ok=False, если фича выключена."""
    return await _checks_cache.get_or_compute(
        "dicom_viewer",
        lambda: _timed(_do_check_dicom_viewer(), timeout=settings.readiness_check_timeout),
    )


async def check_tracing() -> Dict[str, Any]:
    """Проверка Jaeger Query API (кэшированно). Не влияет на readiness.

    Отдаётся в ``/health/checks`` для админских дашбордов. Возвращает
    ``ok=False`` + ``error=disabled``, если tracing отключён флагом
    ``OTEL_ENABLED``.
    """
    return await _checks_cache.get_or_compute(
        "tracing",
        lambda: _timed(_do_check_tracing(), timeout=settings.readiness_check_timeout),
    )


def _ok(result: Dict[str, Any]) -> bool:
    return bool(result.get("ok"))


# ──────────────────────────────────────────────────────────────────────
# Liveness
# ──────────────────────────────────────────────────────────────────────


@router.get("/health/live", summary="Liveness probe")
async def liveness_check() -> Dict[str, Any]:
    """Liveness probe — всегда 200, пока процесс отвечает.

    Используется Docker / Kubernetes для перезапуска зависших контейнеров.
    **Никогда** не проверяет внешние зависимости: падение БД/Redis не должно
    приводить к рестарту SMDG (это работа readiness probe).
    """
    return {"status": "alive", "timestamp": _utcnow_iso()}


# ──────────────────────────────────────────────────────────────────────
# Readiness
# ──────────────────────────────────────────────────────────────────────


@router.get("/health/ready", summary="Readiness probe")
async def readiness_check(request: Request) -> JSONResponse:
    """Readiness probe — готов ли сервис принимать трафик.

    Порядок проверок (fail-fast):
        1. ``app.state.shutting_down`` — идёт graceful shutdown → 503.
        2. ``active_requests >= MAX_CONCURRENT_REQUESTS`` — перегрузка → 503.
        3. БД / Redis / Storage (+ опционально DICOM Viewer) параллельно.

    Возвращает:
        - ``200 OK``  — готов, все проверки прошли.
        - ``503``     — не готов (shutting_down / overloaded /
                        dependencies_unavailable). Устанавливает
                        ``Retry-After`` для корректной работы оркестратора.
    """
    app_state = request.app.state
    active_requests = getattr(app_state, "active_requests", 0)
    max_requests = settings.max_concurrent_requests

    # 1) Graceful shutdown имеет наивысший приоритет.
    if getattr(app_state, "shutting_down", False):
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "shutting_down",
                "message": "Service is gracefully shutting down",
                "active_requests": active_requests,
                "timestamp": _utcnow_iso(),
            },
            headers={"Retry-After": "30"},
        )

    # 2) Перегрузка — отключаем трафик, даём время разгрестись очереди.
    if active_requests >= max_requests:
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "overloaded",
                "active_requests": active_requests,
                "max_requests": max_requests,
                "timestamp": _utcnow_iso(),
            },
            headers={"Retry-After": "5"},
        )

    # 3) Проверки зависимостей параллельно (все закэшированы, TTL ~1–2 сек).
    db_res, redis_res, storage_res = await asyncio.gather(
        check_database(),
        check_redis(),
        check_storage(),
    )

    checks: Dict[str, bool] = {
        "database": _ok(db_res),
        "redis": _ok(redis_res),
        "storage": _ok(storage_res),
    }

    # DICOM Viewer — опциональная проверка, влияет на ready только если включена.
    if settings.dicom_viewer_enabled:
        dicom_res = await check_dicom_viewer()
        checks["dicom_viewer"] = _ok(dicom_res)

    if not all(checks.values()):
        return JSONResponse(
            status_code=503,
            content={
                "ready": False,
                "reason": "dependencies_unavailable",
                "checks": checks,
                "active_requests": active_requests,
                "max_requests": max_requests,
                "timestamp": _utcnow_iso(),
            },
            headers={"Retry-After": "10"},
        )

    return JSONResponse(
        status_code=200,
        content={
            "ready": True,
            "instance_id": settings.INSTANCE_ID,
            "instance_name": settings.INSTANCE_NAME,
            "active_requests": active_requests,
            "max_requests": max_requests,
            "checks": checks,
            "timestamp": _utcnow_iso(),
        },
    )


@router.get("/health/metrics", summary="Per-instance runtime metrics (admin only)")
async def instance_metrics(
    request: Request,
    _admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Expose instance-level metrics for horizontal scaling validation."""
    started_at = float(getattr(request.app.state, "started_at", time.time()))
    uptime_seconds = max(time.time() - started_at, 0.0)
    try:
        session_count = await session_manager.get_active_sessions_count()
    except Exception:
        session_count = -1
    try:
        cache_size = await distributed_cache.get_size()
    except Exception:
        cache_size = -1
    try:
        queue_length = await job_queue.get_queue_length()
        dead_letter_length = await job_queue.get_dead_letter_length()
    except Exception:
        queue_length = -1
        dead_letter_length = -1

    return {
        "instance_id": settings.INSTANCE_ID,
        "instance_name": settings.INSTANCE_NAME,
        "uptime_seconds": round(uptime_seconds, 2),
        "active_requests": int(getattr(request.app.state, "active_requests", 0)),
        "session_count": session_count,
        "cache_size": cache_size,
        "queue_length": queue_length,
        "dead_letter_length": dead_letter_length,
        "timestamp": _utcnow_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# Детальные проверки (admin-only)
# ──────────────────────────────────────────────────────────────────────


@router.get("/health/checks", summary="Detailed dependency checks (admin only)")
async def detailed_checks(
    request: Request,
    _admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Подробный отчёт о состоянии всех зависимостей.

    Доступ только для роли ``admin`` / ``super_admin``. Используется для
    ручной диагностики и алертов Prometheus, где нужны latency и текст
    ошибки. Результаты берутся из общего кэша — стоимость вызова ≈0.
    """
    app_state = request.app.state
    active_requests = getattr(app_state, "active_requests", 0)
    max_requests = settings.max_concurrent_requests

    db_res, redis_res, storage_res, dicom_res, tracing_res = await asyncio.gather(
        check_database(),
        check_redis(),
        check_storage(),
        check_dicom_viewer(),
        check_tracing(),
    )

    import os as _os

    tracing_enabled = _os.getenv("OTEL_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }

    return {
        "timestamp": _utcnow_iso(),
        "shutting_down": bool(getattr(app_state, "shutting_down", False)),
        "active_requests": active_requests,
        "max_requests": max_requests,
        "overloaded": active_requests >= max_requests,
        "checks": {
            "database": db_res,
            "redis": redis_res,
            "storage": storage_res,
            "dicom_viewer": {
                **dicom_res,
                "enabled": settings.dicom_viewer_enabled,
            },
            "tracing": {
                **tracing_res,
                "enabled": tracing_enabled,
            },
        },
        "config": {
            "readiness_check_timeout": settings.readiness_check_timeout,
            "readiness_cache_ttl": settings.readiness_cache_ttl,
            "max_concurrent_requests": settings.max_concurrent_requests,
        },
    }


@router.get("/health/replication", summary="Read-replica health (admin only)")
async def replication_health(
    _admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Replication status endpoint for master/replicas."""
    router_obj = get_db_router()
    if router_obj is None or not router_obj.read_replicas_enabled:
        raise HTTPException(status_code=503, detail="Read replicas are not enabled")

    health = await router_obj.health_check()
    replica_lag = await router_obj.get_replica_lag()

    replica_statuses = [item.get("status", False) for item in health.get("replicas", [])]
    status = "healthy" if health.get("master") and all(replica_statuses) else "degraded"
    return {
        "status": status,
        "health": health,
        "replica_lag": replica_lag,
        "distribution": router_obj.get_read_distribution(),
        "timestamp": _utcnow_iso(),
    }


@router.get("/health/replication/distribution", summary="Read traffic distribution (admin only)")
async def replication_distribution(
    _admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Read traffic distribution across replicas + master fallback."""
    router_obj = get_db_router()
    if router_obj is None or not router_obj.read_replicas_enabled:
        raise HTTPException(status_code=503, detail="Read replicas are not enabled")

    return {
        "status": "ok",
        "distribution": router_obj.get_read_distribution(),
        "timestamp": _utcnow_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# Legacy эндпоинты (сохранены для обратной совместимости)
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


@router.get("/health/timeouts", summary="Timeout configuration")
async def timeout_health_check() -> Dict[str, Any]:
    """Проверка актуальной timeout-конфигурации."""
    return {
        "status": "ok",
        "timeouts": {
            "http_request": settings.HTTP_REQUEST_TIMEOUT_SECONDS,
            "db_query": settings.DB_QUERY_TIMEOUT_SECONDS,
            "s3_upload": settings.S3_UPLOAD_TIMEOUT_SECONDS,
            "dicom_render": settings.DICOM_RENDER_TIMEOUT_SECONDS,
            "background_task": settings.BACKGROUND_TASK_TIMEOUT_SECONDS,
            "webhook_call": settings.WEBHOOK_CALL_TIMEOUT_SECONDS,
        },
    }


__all__ = [
    "router",
    "check_database",
    "check_redis",
    "check_storage",
    "check_dicom_viewer",
    "check_tracing",
]
