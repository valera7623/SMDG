# app/core/rate_limiter.py
import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from redis.asyncio import Redis, RedisError
from app.core.config import settings

logger = logging.getLogger(__name__)

# Асинхронный клиент Redis — используется только для check/reset, НЕ для rate limiter
redis_url = settings.redis_url or "redis://redis:6379/0"
redis_client = Redis.from_url(redis_url, decode_responses=True)


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


# Rate limiter работает в режиме in-memory (MemoryStorage)
# Redis НЕ используется для лимитов — только для других задач проекта
limiter = Limiter(
    key_func=custom_key_func,
    default_limits=["100/minute"]  # глобальный дефолт
)

print("Rate limiter запущен в режиме: MemoryStorage (in-memory)")
logger.info("Rate limiter: используется in-memory хранилище (Redis не задействован)")


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
    "check_redis_connection",
    "reset_rate_limit_cache"
]