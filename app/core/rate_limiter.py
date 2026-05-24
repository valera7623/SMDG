# app/core/rate_limiter.py
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from redis.asyncio import Redis, RedisError
from app.core.config import build_redis_url, settings

logger = logging.getLogger(__name__)

# Асинхронный клиент Redis — используется только для check/reset, НЕ для rate limiter
redis_url = settings.redis_url or "redis://redis:6379/0"
redis_client = Redis.from_url(redis_url, decode_responses=True)

T = TypeVar("T")

REDIS_CIRCUIT_BREAKER_NAME = "redis"


def _get_redis_circuit_breaker():
    """Ленивый импорт + общий брейкер на все Redis-операции."""
    from app.core.circuit_breaker import get_circuit_breaker

    return get_circuit_breaker(REDIS_CIRCUIT_BREAKER_NAME)


async def redis_call_with_fallback(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    fallback: Optional[T] = None,
    **kwargs: Any,
) -> Optional[T]:
    """Выполнить Redis-операцию с fallback при открытом Circuit Breaker.

    Redis в SMDG используется для rate limiter'а и кэша — это НЕ критичные
    зависимости. При деградации Redis'а мы предпочитаем работать в
    degraded-режиме (без rate-limit / без кэша) вместо отказа запроса.

    Пример использования::

        from app.core.rate_limiter import redis_call_with_fallback, redis_client

        value = await redis_call_with_fallback(redis_client.get, "key", fallback=None)
    """
    from app.core.circuit_breaker import CircuitBreakerOpenError
    from app.core.circuit_breaker_metrics import record_rejected_call

    cb = _get_redis_circuit_breaker()
    try:
        return await cb.call(func, *args, **kwargs)
    except CircuitBreakerOpenError:
        record_rejected_call(REDIS_CIRCUIT_BREAKER_NAME)
        logger.debug(
            "Redis circuit breaker is OPEN — using fallback (value=%r)", fallback
        )
        return fallback
    except RedisError as exc:
        # CircuitBreaker уже зафиксировал ошибку внутри call(); здесь мы просто
        # гасим её и отдаём fallback, чтобы не ронять bus-критичный запрос.
        logger.warning("Redis call failed, using fallback: %s", exc)
        return fallback


def custom_key_func(request: Request) -> str:
    """
    Ключ rate limit:
    1. Если есть авторизованный пользователь → user:sub
    2. Иначе — IP
    """
    user = request.scope.get("user")
    if user and hasattr(user, "sub"):
        key = f"rate_limit:user:{user.sub}"
        logger.debug(f"Rate limit key: {key} (авторизованный пользователь)")
        return key

    ip = get_remote_address(request)
    key = f"rate_limit:ip:{ip}"
    logger.debug(f"Rate limit key: {key} (аноним / fallback на IP)")
    return key


def register_rate_limit_key(request: Request) -> str:
    """IP-scoped key for POST /auth/register (isolated from global limits)."""
    ip = get_remote_address(request)
    key = f"rate_limit:register:ip:{ip}"
    logger.debug("Register rate limit key: %s", key)
    return key


def retry_after_seconds(exc: RateLimitExceeded) -> int:
    """Seconds until the rate-limit window resets (for Retry-After header)."""
    try:
        limit_item = exc.limit.limit if exc.limit else None
        if limit_item is not None:
            return max(1, int(limit_item.get_expiry()))
    except Exception:
        pass
    return 60


def rate_limit_exceeded_response(exc: RateLimitExceeded) -> tuple[dict[str, str], dict[str, str]]:
    """JSON body and headers for HTTP 429 rate-limit responses."""
    detail = exc.detail if isinstance(exc.detail, str) else "Too many requests. Please try again later."
    retry_after = str(retry_after_seconds(exc))
    return (
        {"detail": detail},
        {"Retry-After": retry_after},
    )


default_limit = settings.rate_limit_default
if settings.load_test_mode and default_limit == "100/minute":
    # Safe pre-prod default override for load tests (can be overridden via RATE_LIMIT_DEFAULT)
    default_limit = "5000/minute"

limiter_kwargs: dict[str, Any] = {
    "key_func": custom_key_func,
    "default_limits": [default_limit],
}
rate_limit_storage = settings.RATE_LIMIT_STORAGE
if rate_limit_storage == "redis://redis:6379/2":
    rate_limit_storage = build_redis_url(2)

if not settings.load_test_mode and (not settings.dev_mode or settings.demo_mode):
    limiter_kwargs["storage_uri"] = rate_limit_storage

limiter = Limiter(**limiter_kwargs)

if "storage_uri" in limiter_kwargs:
    logger.info("Rate limiter: используется Redis storage (%s)", rate_limit_storage)
else:
    logger.warning("Rate limiter: используется in-memory хранилище (dev/load-test mode)")


async def check_redis_connection():
    """Проверка подключения к Redis (для других частей проекта)"""
    try:
        pong = await redis_client.ping()
        if pong:
            logger.info("✅ Redis подключён (для rate limiter не используется, но доступен)")
            return
    except RedisError as e:
        logger.critical(f"❌ Redis НЕДОСТУПЕН: {str(e)}")
        raise RuntimeError(f"Redis connection failed: {e}")
    except Exception as e:
        logger.critical(f"Неизвестная ошибка Redis: {str(e)}")
        raise RuntimeError(f"Redis init failed: {e}")


async def reset_rate_limit_cache():
    """Сброс кеша Redis (не влияет на rate limiter, т.к. он in-memory)"""
    try:
        await redis_client.flushdb()
        logger.info("🧹 Кеш Redis полностью сброшен")
    except RedisError as e:
        logger.error(f"Ошибка сброса кеша Redis: {e}")


__all__ = [
    "limiter",
    "custom_key_func",
    "register_rate_limit_key",
    "retry_after_seconds",
    "rate_limit_exceeded_response",
    "check_redis_connection",
    "reset_rate_limit_cache",
    "redis_call_with_fallback",
    "REDIS_CIRCUIT_BREAKER_NAME",
]