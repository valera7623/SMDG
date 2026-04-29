"""Bulkhead pattern implementation for SMDG."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BulkheadState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    DRAINING = "draining"


@dataclass
class BulkheadMetrics:
    active_requests: int = 0
    queued_requests: int = 0
    total_completed: int = 0
    total_rejected: int = 0
    total_timeout: int = 0
    avg_wait_time_ms: float = 0.0
    p99_wait_time_ms: float = 0.0


class BulkheadRejectedError(Exception):
    """Raised when request is rejected due to saturation."""


class BulkheadTimeoutError(Exception):
    """Raised when waiting for queue/slot exceeded timeout."""


class Bulkhead:
    """Isolates a component using dedicated concurrency and queue limits."""

    def __init__(
        self,
        name: str,
        max_concurrent: int,
        queue_size: int = 0,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.timeout_seconds = timeout_seconds

        self._state = BulkheadState.OPEN
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue = asyncio.Queue(maxsize=queue_size) if queue_size > 0 else None
        self._metrics = BulkheadMetrics()
        self._wait_times: deque[float] = deque(maxlen=1000)
        self._lock = asyncio.Lock()
        self._last_reported_rejected = 0
        self._last_reported_timeout = 0

        logger.info(
            "Bulkhead '%s' created: max_concurrent=%s queue_size=%s timeout=%ss",
            name,
            max_concurrent,
            queue_size,
            timeout_seconds,
        )

    def _publish_metrics(self) -> None:
        try:
            from app.core.bulkhead_metrics import (
                bulkhead_active,
                bulkhead_queued,
                bulkhead_rejected_total,
                bulkhead_timeout_total,
                bulkhead_utilization,
            )
        except Exception:
            return

        utilization = (
            self._metrics.active_requests / self.max_concurrent * 100
            if self.max_concurrent > 0
            else 0
        )
        bulkhead_active.labels(name=self.name).set(self._metrics.active_requests)
        bulkhead_queued.labels(name=self.name).set(self._metrics.queued_requests)
        bulkhead_utilization.labels(name=self.name).set(utilization)

        rejected_delta = self._metrics.total_rejected - self._last_reported_rejected
        timeout_delta = self._metrics.total_timeout - self._last_reported_timeout
        if rejected_delta > 0:
            bulkhead_rejected_total.labels(name=self.name).inc(rejected_delta)
            self._last_reported_rejected = self._metrics.total_rejected
        if timeout_delta > 0:
            bulkhead_timeout_total.labels(name=self.name).inc(timeout_delta)
            self._last_reported_timeout = self._metrics.total_timeout

    async def execute(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        if self._state == BulkheadState.CLOSED:
            async with self._lock:
                self._metrics.total_rejected += 1
                self._publish_metrics()
            raise BulkheadRejectedError(f"Bulkhead '{self.name}' is CLOSED")

        start_wait = time.time()
        queue_ticket = False

        # No queue mode: reject fast when all workers are busy.
        if self._queue is None and self._semaphore.locked():
            async with self._lock:
                self._metrics.total_rejected += 1
                self._publish_metrics()
            raise BulkheadRejectedError(
                f"Bulkhead '{self.name}' saturated: {self.max_concurrent} active and queue disabled"
            )

        if self._queue is not None:
            try:
                self._queue.put_nowait(None)
                queue_ticket = True
            except asyncio.QueueFull:
                async with self._lock:
                    self._metrics.total_rejected += 1
                    self._metrics.queued_requests = self._queue.qsize()
                    self._publish_metrics()
                raise BulkheadRejectedError(
                    f"Bulkhead '{self.name}' queue is full ({self.queue_size})"
                )

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            if queue_ticket and self._queue is not None:
                _ = self._queue.get_nowait()
            async with self._lock:
                self._metrics.total_timeout += 1
                self._metrics.queued_requests = self._queue.qsize() if self._queue else 0
                self._publish_metrics()
            raise BulkheadTimeoutError(
                f"Bulkhead '{self.name}' acquire timeout after {self.timeout_seconds}s"
            )

        # Request left queue and moved to active execution.
        if queue_ticket and self._queue is not None:
            _ = self._queue.get_nowait()
            queue_ticket = False

        wait_time = (time.time() - start_wait) * 1000
        self._wait_times.append(wait_time)
        async with self._lock:
            self._metrics.active_requests += 1
            self._metrics.queued_requests = self._queue.qsize() if self._queue else 0
            self._publish_metrics()

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._metrics.total_completed += 1
            return result
        finally:
            self._semaphore.release()
            async with self._lock:
                self._metrics.active_requests -= 1
                self._metrics.queued_requests = self._queue.qsize() if self._queue else 0
                if self._wait_times:
                    sorted_times = sorted(self._wait_times)
                    self._metrics.avg_wait_time_ms = sum(sorted_times) / len(sorted_times)
                    p99_idx = min(len(sorted_times) - 1, int(len(sorted_times) * 0.99))
                    self._metrics.p99_wait_time_ms = sorted_times[p99_idx]
                self._publish_metrics()

    def get_state(self) -> dict[str, Any]:
        utilization = (
            self._metrics.active_requests / self.max_concurrent * 100
            if self.max_concurrent > 0
            else 0
        )
        return {
            "name": self.name,
            "state": self._state.value,
            "metrics": {
                "active_requests": self._metrics.active_requests,
                "max_concurrent": self.max_concurrent,
                "queued_requests": self._metrics.queued_requests,
                "queue_size": self.queue_size,
                "total_completed": self._metrics.total_completed,
                "total_rejected": self._metrics.total_rejected,
                "total_timeout": self._metrics.total_timeout,
                "avg_wait_time_ms": round(self._metrics.avg_wait_time_ms, 2),
                "p99_wait_time_ms": round(self._metrics.p99_wait_time_ms, 2),
            },
            "utilization": round(utilization, 2),
        }

    async def close(self) -> None:
        self._state = BulkheadState.CLOSED
        logger.warning("Bulkhead '%s' closed", self.name)

    async def open(self) -> None:
        self._state = BulkheadState.OPEN
        logger.info("Bulkhead '%s' opened", self.name)

    async def is_overloaded(self) -> bool:
        queued = self._metrics.queued_requests
        queue_limit_reached = self.queue_size > 0 and queued >= self.queue_size
        return self._metrics.active_requests >= self.max_concurrent and queue_limit_reached


def bulkhead(name: str, max_concurrent: int, queue_size: int = 0, timeout_seconds: float = 30.0):
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        bulkhead_instance = Bulkhead(name, max_concurrent, queue_size, timeout_seconds)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await bulkhead_instance.execute(func, *args, **kwargs)

        wrapper._bulkhead = bulkhead_instance  # type: ignore[attr-defined]
        return wrapper

    return decorator


_bulkheads: dict[str, Bulkhead] = {}


def _get_bulkhead_configs() -> dict[str, tuple[int, int, int]]:
    from app.core.config import settings

    return {
        "api": (
            settings.API_BULKHEAD_MAX_CONCURRENT,
            settings.API_BULKHEAD_QUEUE_SIZE,
            settings.API_BULKHEAD_TIMEOUT,
        ),
        "dicom": (
            settings.DICOM_BULKHEAD_MAX_CONCURRENT,
            settings.DICOM_BULKHEAD_QUEUE_SIZE,
            settings.DICOM_BULKHEAD_TIMEOUT,
        ),
        "upload": (
            settings.UPLOAD_BULKHEAD_MAX_CONCURRENT,
            settings.UPLOAD_BULKHEAD_QUEUE_SIZE,
            settings.UPLOAD_BULKHEAD_TIMEOUT,
        ),
        "download": (
            settings.DOWNLOAD_BULKHEAD_MAX_CONCURRENT,
            settings.DOWNLOAD_BULKHEAD_QUEUE_SIZE,
            settings.DOWNLOAD_BULKHEAD_TIMEOUT,
        ),
        "s3": (
            settings.S3_BULKHEAD_MAX_CONCURRENT,
            settings.S3_BULKHEAD_QUEUE_SIZE,
            settings.S3_BULKHEAD_TIMEOUT,
        ),
        "audit_export": (
            settings.AUDIT_EXPORT_BULKHEAD_MAX_CONCURRENT,
            settings.AUDIT_EXPORT_BULKHEAD_QUEUE_SIZE,
            settings.AUDIT_EXPORT_BULKHEAD_TIMEOUT,
        ),
        "webhook": (
            settings.WEBHOOK_BULKHEAD_MAX_CONCURRENT,
            settings.WEBHOOK_BULKHEAD_QUEUE_SIZE,
            settings.WEBHOOK_BULKHEAD_TIMEOUT,
        ),
        "cleanup": (
            settings.CLEANUP_BULKHEAD_MAX_CONCURRENT,
            0,
            settings.CLEANUP_BULKHEAD_TIMEOUT,
        ),
    }


def get_bulkhead(name: str) -> Bulkhead:
    if name in _bulkheads:
        return _bulkheads[name]

    configs = _get_bulkhead_configs()
    max_concurrent, queue_size, timeout = configs.get(name, (10, 20, 30))
    _bulkheads[name] = Bulkhead(name, max_concurrent, queue_size, timeout)
    return _bulkheads[name]


def initialize_bulkheads() -> None:
    """Pre-create configured bulkheads and publish zero-valued metric series."""
    for name in _get_bulkhead_configs():
        bulkhead = get_bulkhead(name)
        bulkhead._publish_metrics()
