"""Distributed cache for horizontally scaled SMDG replicas."""
from __future__ import annotations

import hashlib
import json
from functools import wraps
from typing import Any, Callable, Optional

import redis.asyncio as redis

from app.core.config import settings


class DistributedCache:
    """Redis-backed shared cache for all API instances."""

    def __init__(self) -> None:
        self.redis_client: Optional[redis.Redis] = None

    def _require_redis(self) -> redis.Redis:
        if self.redis_client is None:
            raise RuntimeError("DistributedCache is not initialized")
        return self.redis_client

    async def init(self) -> None:
        if self.redis_client is not None:
            return
        self.redis_client = redis.from_url(
            settings.CACHE_REDIS_URL,
            decode_responses=True,
        )
        await self.redis_client.ping()

    async def close(self) -> None:
        if self.redis_client is not None:
            await self.redis_client.close()
        self.redis_client = None

    async def get(self, key: str) -> Optional[Any]:
        rc = self._require_redis()
        value = await rc.get(f"cache:{key}")
        return json.loads(value) if value is not None else None

    async def set(self, key: str, value: Any, ttl: int = settings.CACHE_TTL_SECONDS) -> None:
        rc = self._require_redis()
        await rc.setex(f"cache:{key}", ttl, json.dumps(value))

    async def delete(self, key: str) -> None:
        rc = self._require_redis()
        await rc.delete(f"cache:{key}")

    async def delete_pattern(self, pattern: str) -> None:
        rc = self._require_redis()
        keys = [key async for key in rc.scan_iter(match=f"cache:{pattern}", count=500)]
        if keys:
            await rc.delete(*keys)

    async def clear(self) -> None:
        await self.delete_pattern("*")

    async def get_size(self) -> int:
        rc = self._require_redis()
        return sum([1 async for _ in rc.scan_iter(match="cache:*", count=500)])

    def cached(self, ttl: int = settings.CACHE_TTL_SECONDS) -> Callable:
        """Decorator for caching async function results."""

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                key_data = f"{func.__module__}.{func.__name__}:{args}:{kwargs}"
                cache_key = hashlib.sha256(key_data.encode("utf-8")).hexdigest()
                cached_result = await self.get(cache_key)
                if cached_result is not None:
                    return cached_result
                result = await func(*args, **kwargs)
                await self.set(cache_key, result, ttl)
                return result

            return wrapper

        return decorator


distributed_cache = DistributedCache()
