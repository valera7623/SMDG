"""Stateless session management for horizontal scaling."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import redis.asyncio as redis

from app.core.config import settings


class SessionManager:
    """Redis-backed session manager shared between app replicas."""

    def __init__(self) -> None:
        self.redis_client: Optional[redis.Redis] = None
        self._initialized = False

    def _require_redis(self) -> redis.Redis:
        if self.redis_client is None:
            raise RuntimeError("SessionManager is not initialized")
        return self.redis_client

    async def init(self) -> None:
        if self._initialized:
            return
        self.redis_client = redis.from_url(
            settings.SESSION_REDIS_URL,
            decode_responses=True,
        )
        await self.redis_client.ping()
        self._initialized = True

    async def close(self) -> None:
        if self.redis_client is not None:
            await self.redis_client.close()
        self._initialized = False

    async def create_session(self, user_id: int, data: Dict[str, Any]) -> str:
        rc = self._require_redis()
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        session_data = {
            "user_id": str(user_id),
            "created_at": now,
            "last_accessed": now,
            "data": json.dumps(data),
        }
        key = f"session:{session_id}"
        await rc.hset(key, mapping=session_data)
        await rc.expire(key, settings.SESSION_TTL_SECONDS)
        return session_id

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        rc = self._require_redis()
        key = f"session:{session_id}"
        session_data = await rc.hgetall(key)
        if not session_data:
            return None
        await rc.hset(
            key,
            "last_accessed",
            datetime.now(timezone.utc).isoformat(),
        )
        await rc.expire(key, settings.SESSION_TTL_SECONDS)
        session_data["data"] = json.loads(session_data.get("data", "{}"))
        return session_data

    async def delete_session(self, session_id: str) -> None:
        rc = self._require_redis()
        await rc.delete(f"session:{session_id}")

    async def touch_session(self, session_id: str) -> None:
        rc = self._require_redis()
        await rc.expire(f"session:{session_id}", settings.SESSION_TTL_SECONDS)

    async def get_active_sessions_count(self) -> int:
        rc = self._require_redis()
        count = 0
        async for _ in rc.scan_iter(match="session:*", count=500):
            count += 1
        return count

    async def cleanup_expired_sessions(self) -> None:
        # Redis evicts expired keys automatically.
        return None


session_manager = SessionManager()
