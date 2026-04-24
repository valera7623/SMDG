"""Read/write database router for PostgreSQL primary + replicas."""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.metrics import read_distribution_total

logger = logging.getLogger(__name__)


class DatabaseRouter:
    """Routes writes to master and reads to healthy replicas with fallback."""

    def __init__(
        self,
        master_url: str,
        replica_urls: list[str] | None = None,
        max_replica_lag_bytes: int = 100 * 1024 * 1024,
        health_ttl_seconds: float = 5.0,
    ) -> None:
        self.master_url = master_url
        self.replica_urls = replica_urls or []
        self.max_replica_lag_bytes = max_replica_lag_bytes
        self.health_ttl_seconds = health_ttl_seconds
        self.read_replicas_enabled = bool(self.replica_urls)
        self._rr_index = 0

        self.master_engine = create_async_engine(
            self.master_url,
            pool_size=20,
            max_overflow=40,
            pool_pre_ping=True,
            echo=False,
        )
        self.master_session_factory = async_sessionmaker(
            self.master_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self.replica_engines = [
            create_async_engine(
                url,
                pool_size=30,
                max_overflow=60,
                pool_pre_ping=True,
                echo=False,
            )
            for url in self.replica_urls
        ]
        self.replica_session_factories = [
            async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            for engine in self.replica_engines
        ]

        self._read_distribution: dict[str, int] = {
            f"replica_{idx}": 0 for idx in range(len(self.replica_session_factories))
        }
        self._read_distribution["master_fallback"] = 0

        self._replica_snapshot_cached_at: float = 0.0
        self._replica_snapshot: dict[str, Any] = {}

        logger.info(
            "DatabaseRouter initialized: replicas=%s lag_threshold_bytes=%s",
            len(self.replica_session_factories),
            self.max_replica_lag_bytes,
        )

    async def _collect_replica_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}

        for idx, engine in enumerate(self.replica_engines):
            name = f"replica_{idx}"
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                    bytes_result = await conn.execute(
                        text(
                            """
                            SELECT COALESCE(
                                pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()),
                                0
                            )::bigint
                            """
                        )
                    )
                    time_result = await conn.execute(
                        text(
                            """
                            SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
                            """
                        )
                    )

                lag_bytes = int(bytes_result.scalar() or 0)
                lag_seconds_raw = time_result.scalar()
                lag_seconds = float(lag_seconds_raw) if lag_seconds_raw is not None else 0.0
                healthy = lag_bytes <= self.max_replica_lag_bytes

                snapshot[name] = {
                    "id": idx,
                    "healthy": healthy,
                    "lag_bytes": lag_bytes,
                    "lag_seconds": round(lag_seconds, 3),
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001
                snapshot[name] = {
                    "id": idx,
                    "healthy": False,
                    "lag_bytes": None,
                    "lag_seconds": None,
                    "error": str(exc),
                }

        return snapshot

    async def _get_replica_snapshot(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        is_stale = (now - self._replica_snapshot_cached_at) > self.health_ttl_seconds
        if force_refresh or is_stale or not self._replica_snapshot:
            self._replica_snapshot = await self._collect_replica_snapshot()
            self._replica_snapshot_cached_at = now
        return self._replica_snapshot

    async def get_read_session(self) -> AsyncSession:
        """Return replica session or fallback to master if replicas are unhealthy/lagging."""
        if not self.replica_session_factories:
            self._read_distribution["master_fallback"] += 1
            read_distribution_total.labels(target="master_fallback").inc()
            return self.master_session_factory()

        snapshot = await self._get_replica_snapshot()
        healthy_indexes = [
            data["id"]
            for data in snapshot.values()
            if data.get("healthy") and data.get("id") is not None
        ]

        if not healthy_indexes:
            self._read_distribution["master_fallback"] += 1
            read_distribution_total.labels(target="master_fallback").inc()
            logger.warning("All replicas are unhealthy/lagging. Falling back to master for reads")
            return self.master_session_factory()

        selected_idx = healthy_indexes[self._rr_index % len(healthy_indexes)]
        self._rr_index += 1
        replica_name = f"replica_{selected_idx}"
        self._read_distribution[replica_name] = self._read_distribution.get(replica_name, 0) + 1
        read_distribution_total.labels(target=replica_name).inc()
        return self.replica_session_factories[selected_idx]()

    async def get_write_session(self) -> AsyncSession:
        """Return master session for write operations."""
        return self.master_session_factory()

    async def health_check(self) -> dict[str, Any]:
        """Check connectivity and lag status for master and replicas."""
        result: dict[str, Any] = {"master": False, "replicas": []}

        try:
            async with self.master_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            result["master"] = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Master health check failed: %s", exc)

        snapshot = await self._get_replica_snapshot(force_refresh=True)
        for name in sorted(snapshot.keys()):
            item = snapshot[name]
            result["replicas"].append(
                {
                    "id": item["id"],
                    "name": name,
                    "status": bool(item["healthy"]),
                    "lag_bytes": item["lag_bytes"],
                    "lag_seconds": item["lag_seconds"],
                    "error": item["error"],
                }
            )

        return result

    async def get_replica_lag(self) -> dict[str, Any]:
        """Collect replication lag details for each replica."""
        snapshot = await self._get_replica_snapshot(force_refresh=True)
        lag: dict[str, Any] = {}
        for name, data in snapshot.items():
            lag[name] = {
                "lag_bytes": data.get("lag_bytes"),
                "lag_seconds": data.get("lag_seconds"),
                "healthy": data.get("healthy"),
                "error": data.get("error"),
            }
        return lag

    def get_read_distribution(self) -> dict[str, Any]:
        total_reads = sum(self._read_distribution.values())
        return {
            "total_reads": total_reads,
            "counters": dict(self._read_distribution),
            "lag_threshold_bytes": self.max_replica_lag_bytes,
        }

    async def dispose(self) -> None:
        await self.master_engine.dispose()
        for engine in self.replica_engines:
            await engine.dispose()


db_router: DatabaseRouter | None = None


async def init_db_router(
    master_url: str,
    replica_urls: list[str] | None = None,
    max_replica_lag_bytes: int = 100 * 1024 * 1024,
    health_ttl_seconds: float = 5.0,
) -> DatabaseRouter:
    global db_router
    db_router = DatabaseRouter(
        master_url=master_url,
        replica_urls=replica_urls,
        max_replica_lag_bytes=max_replica_lag_bytes,
        health_ttl_seconds=health_ttl_seconds,
    )
    return db_router


def get_db_router() -> DatabaseRouter | None:
    return db_router
