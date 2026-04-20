"""
Middleware-слои SMDG.

Здесь определены:
- :class:`AuditMiddleware` — сквозное аудит-логирование HTTP-запросов.
- :class:`ActiveRequestsMiddleware` — отслеживание активных in-flight запросов
  и мягкое отклонение новых во время graceful shutdown.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import audit_logger

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """Аудит всех HTTP-запросов через единый логгер."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[JSONResponse]],
    ):
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        url = request.url.path
        user_agent = request.headers.get("user-agent") or "unknown"

        try:
            response = await call_next(request)
            status_code = response.status_code
            success = status_code < 400
            reason = f"Status: {status_code}, UA: {user_agent[:100]}"

            audit_logger.log_operation(
                action=f"{method} {url}",
                filename="",
                user="api",
                ip=client_ip,
                reason=reason,
                success=success,
                metadata={
                    "method": method,
                    "path": url,
                    "status": status_code,
                    "user_agent": user_agent,
                },
            )
            return response

        except Exception as e:
            audit_logger.log_operation(
                action=f"{method} {url}",
                filename="",
                user="api",
                ip=client_ip,
                reason=str(e),
                success=False,
                metadata={
                    "method": method,
                    "path": url,
                    "status": 500,
                    "user_agent": user_agent,
                },
            )
            raise


# Пути, которые должны продолжать работать даже во время shutdown:
# Kubernetes/Docker healthcheck и метрики должны быть доступны,
# иначе оркестратор не сможет корректно снять под трафик.
_SHUTDOWN_WHITELIST: frozenset[str] = frozenset(
    {
        "/health/live",
        "/health/ready",
        "/health/features",
        "/health/deployment",
        "/health",
        "/metrics",
    }
)


class ActiveRequestsMiddleware:
    """
    ASGI-middleware, отслеживающий количество in-flight HTTP-запросов.

    Функции:
    1. Ведёт счётчик ``app.state.active_requests`` (под защитой
       ``app.state.active_requests_lock``).
    2. Во время graceful shutdown (``app.state.shutting_down is True``)
       возвращает ``503 Service Unavailable`` на новые запросы, не
       входящие в whitelist (healthchecks, metrics).

    Счётчик увеличивается на входе в middleware и уменьшается в ``finally``,
    что гарантирует корректный подсчёт даже при исключениях и отмене задач.
    """

    def __init__(self, app: ASGIApp, fastapi_app: FastAPI) -> None:
        self.app = app
        self._fastapi_app = fastapi_app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = self._fastapi_app.state
        path: str = scope.get("path", "")

        shutting_down: bool = getattr(state, "shutting_down", False)
        if shutting_down and path not in _SHUTDOWN_WHITELIST:
            logger.warning(
                "Отклонён новый запрос во время shutdown: %s %s",
                scope.get("method", "?"),
                path,
            )
            response = JSONResponse(
                status_code=503,
                content={
                    "status": "shutting_down",
                    "detail": "Service is gracefully shutting down, retry later",
                },
                headers={"Retry-After": "30", "Connection": "close"},
            )
            await response(scope, receive, send)
            return

        lock = state.active_requests_lock
        async with lock:
            state.active_requests += 1
            current = state.active_requests
        logger.debug("→ active_requests=%d (%s %s)", current, scope.get("method"), path)

        try:
            await self.app(scope, receive, send)
        finally:
            async with lock:
                state.active_requests -= 1
                current = state.active_requests
            logger.debug("← active_requests=%d (%s %s)", current, scope.get("method"), path)


__all__ = ["AuditMiddleware", "ActiveRequestsMiddleware"]
