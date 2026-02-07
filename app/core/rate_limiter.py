# app/core/rate_limiter.py
import asyncio
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from redis.asyncio import Redis, RedisError
from app.core.config import settings

logger = logging.getLogger(__name__)

redis_url = settings.redis_url or "redis://redis:6379/0"

# Глобальные переменные
redis_client = None
storage_backend = "memory"  # дефолт

limiter = Limiter(key_func=get_remote_address)

# Инициализируем клиента, но не проверяем здесь
try:
    redis_client = Redis.from_url(redis_url, decode_responses=True)
except Exception as e:
    logger.warning(f"Ошибка создания Redis клиента: {e}. Будет fallback на memory.")

async def check_redis_connection():
    """Асинхронная проверка подключения к Redis. Вызывается в startup."""
    global storage_backend

    if redis_client is None:
        logger.warning("Redis клиент не создан → fallback на memory")
        return False

    try:
        pong = await redis_client.ping()
        if pong:
            storage_backend = "redis"
            logger.info("✅ Redis подключён успешно (ping OK)")
            return True
        else:
            raise RuntimeError("Redis ping вернул не True")
    except RedisError as e:
        logger.warning(f"Redis недоступен: {e} → fallback на memory")
        storage_backend = "memory"
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при проверке Redis: {e}")
        storage_backend = "memory"
        return False

async def reset_rate_limit_cache():
    """Сброс кеша лимитов (если Redis доступен)"""
    if storage_backend == "redis" and redis_client:
        try:
            await redis_client.flushdb()
            logger.info("🧹 Кеш rate limiter (Redis) сброшен")
        except RedisError as e:
            logger.error(f"Ошибка сброса Redis кеша: {e}")
    else:
        logger.info("Rate limiter на memory → кеш не сбрасывается")

__all__ = [
    "limiter",
    "get_remote_address",
    "check_redis_connection",
    "reset_rate_limit_cache",
    "storage_backend",          # экспортируем для main.py
]