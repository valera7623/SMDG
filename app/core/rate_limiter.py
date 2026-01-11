# app/core/rate_limiter.py
import asyncio
from slowapi import Limiter
from slowapi.util import get_remote_address
from redis.asyncio import Redis, RedisError
from redis.exceptions import ConnectionError as RedisConnectionError
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

redis_url = settings.redis_url or "redis://localhost:6379/0"
redis_client = None
storage_backend = "memory"  # По умолчанию

try:
    # Создаём синхронный клиент только для проверки подключения
    from redis import Redis as SyncRedis
    sync_redis = SyncRedis.from_url(redis_url, decode_responses=True, socket_timeout=2)
    
    # Пинг синхронно
    sync_redis.ping()
    
    # Если пинг прошёл — используем асинхронный клиент
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    storage_backend = "redis"
    logger.info("✅ Redis успешно подключён для rate limiting")
    
except (RedisError, RedisConnectionError, Exception) as e:
    logger.warning(f"⚠️ Redis недоступен ({e}) → rate limiting в памяти")
    logger.warning("ℹ️  ВНИМАНИЕ: In-memory rate limiting может некорректно работать с --reload!")
    storage_backend = "memory"
    redis_client = None

# Для in-memory используем более надежную конфигурацию
if storage_backend == "memory":
    # Используем специальный URI для in-memory с улучшенной обработкой
    storage_uri = "memory://"
    # Альтернатива: использовать локальный файл для синхронизации
    # storage_uri = "file:///tmp/rate_limit_storage.json"
else:
    storage_uri = redis_url

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=storage_uri,
    default_limits=["300/day"],
    # Добавляем стратегию для лучшей работы с памятью
    strategy="fixed-window",  # или "moving-window"
    # Добавляем автоматическую очистку устаревших записей
    auto_check=True
)

# Функция для ручного сброса кеша (для тестирования)
async def reset_rate_limit_cache():
    """Сбрасывает кеш rate limiter (для тестирования)"""
    if hasattr(limiter, '_storage'):
        try:
            if storage_backend == "redis" and redis_client:
                await redis_client.flushdb()
                logger.info("🧹 Кеш Redis сброшен")
            elif storage_backend == "memory":
                # Для in-memory пытаемся очистить внутреннее хранилище
                if hasattr(limiter._storage, 'storage'):
                    limiter._storage.storage.clear()
                    logger.info("🧹 In-memory кеш rate limiter сброшен")
        except Exception as e:
            logger.error(f"❌ Ошибка при сбросе кеша: {e}")
            
# app/core/rate_limiter.py - ДОБАВИТЬ ЭТУ ФУНКЦИЮ
async def wait_for_rate_limit_reset(seconds=10):
    """Ожидание сброса rate limit с прогресс-баром"""
    import sys
    for i in range(seconds, 0, -1):
        sys.stdout.write(f"\r⏳ Rate limit сбросится через {i} секунд...")
        sys.stdout.flush()
        await asyncio.sleep(1)
    sys.stdout.write("\r✅ Rate limit должен сброситься            \n")

__all__ = ["limiter", "get_remote_address", "reset_rate_limit_cache", "storage_backend", "wait_for_rate_limit_reset"]