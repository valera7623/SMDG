"""Replication monitoring metrics for read replicas."""

from __future__ import annotations

import asyncio
import logging

from prometheus_client import Gauge, Info

from app.core.database_router import get_db_router

logger = logging.getLogger(__name__)

replication_lag_bytes = Gauge(
    "smdg_replication_lag_bytes",
    "Replication lag in bytes",
    ["replica"],
)

replication_lag_seconds = Gauge(
    "smdg_replication_lag_seconds",
    "Replication lag in seconds",
    ["replica"],
)

replication_status = Info(
    "smdg_replication_status",
    "Replication status",
    ["replica"],
)


async def monitor_replication(interval_seconds: int = 30) -> None:
    """Background task to export replication health into Prometheus metrics."""
    while True:
        try:
            router = get_db_router()
            if router is not None and router.read_replicas_enabled:
                lag = await router.get_replica_lag()
                for replica_name, data in lag.items():
                    if "lag_bytes" in data:
                        lag_bytes = float(data["lag_bytes"])
                        lag_seconds = float(data.get("lag_seconds", 0.0))
                        healthy = bool(data.get("healthy", False))
                        replication_lag_bytes.labels(replica=replica_name).set(lag_bytes)
                        replication_lag_seconds.labels(replica=replica_name).set(lag_seconds)
                        replication_status.labels(replica=replica_name).info(
                            {
                                "status": "healthy" if healthy else "lagging",
                                "lag_mb": str(round(lag_bytes / (1024 * 1024), 3)),
                            }
                        )
        except Exception as exc:  # noqa: BLE001
            logger.error("Replication monitor error: %s", exc)

        await asyncio.sleep(interval_seconds)
