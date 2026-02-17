# app/core/rate_limiter.py
import asyncio
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from redis.asyncio import Redis, RedisError
from app.core.config import settings

logger = logging.getLogger(__name__)

redis_url = settings.redis_url or "redis://redis:6379/0"

# Создаём клиента
redis_client = Redis.from_url(redis_url, decode_responses=True)

# Жёсткая проверка на старте модуля НЕ делаем — переносим в startup
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=redis_url,          # slowapi сам использует redis
    default_limits=["100/minute"]   # если нужно дефолтное ограничение
)

async def check_redis_connection():
    """Вызывается в startup_event. Redis обязателен — если нет, крашим приложение."""
    try:
        pong = await redis_client.ping()
        if pong:
            logger.info("✅ Redis подключён для rate limiter (ping OK)")
            return
    except RedisError as e:
        logger.critical(f"❌ Redis НЕДОСТУПЕН для rate limiter: {str(e)}")
        raise RuntimeError(f"Redis connection failed: {e}. Rate limiter требует Redis.")
    except Exception as e:
        logger.critical(f"Неизвестная ошибка Redis: {str(e)}")
        raise RuntimeError(f"Redis init failed: {e}")

async def reset_rate_limit_cache():
    try:
        await redis_client.flushdb()
        logger.info("🧹 Кеш rate limiter сброшен")
    except RedisError as e:
        logger.error(f"Ошибка сброса кеша: {e}")

__all__ = [
    "limiter",
    "get_remote_address",
    "check_redis_connection",
    "reset_rate_limit_cache"
]