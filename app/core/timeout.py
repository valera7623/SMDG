"""Timeout utilities for SMDG."""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Awaitable, Callable, TypeVar

from app.core.timeout_metrics import timeout_duration_seconds, timeout_total

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TimeoutError(Exception):
    """Raised when an operation exceeds the configured timeout."""


def _record_timeout(operation: str, service: str, seconds: float) -> None:
    timeout_total.labels(operation=operation, service=service).inc()
    timeout_duration_seconds.labels(operation=operation, service=service).observe(seconds)


def timeout(
    seconds: float,
    error_message: str = "Operation timed out",
    *,
    service: str = "api",
    operation: str | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that adds timeout handling to async functions."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        op_name = operation or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError as exc:
                _record_timeout(op_name, service, seconds)
                logger.error("Timeout after %.2fs: %s", seconds, op_name)
                raise TimeoutError(error_message) from exc

        return wrapper

    return decorator


async def run_with_timeout(
    coro: Awaitable[T],
    timeout_seconds: float,
    error_message: str = "Operation timed out",
    *,
    service: str = "core",
    operation: str = "operation",
) -> T:
    """Run coroutine with timeout and unified TimeoutError."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        _record_timeout(operation, service, timeout_seconds)
        logger.error("Timeout after %.2fs: %s", timeout_seconds, error_message)
        raise TimeoutError(error_message) from exc

