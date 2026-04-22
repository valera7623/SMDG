"""
Middleware-слои SMDG.

Здесь определены:
- :class:`AuditMiddleware` — сквозное аудит-логирование HTTP-запросов.
- :class:`ActiveRequestsMiddleware` — отслеживание активных in-flight запросов
  и мягкое отклонение новых во время graceful shutdown.
- :class:`TracingMiddleware` — проброс ``X-Trace-Id`` в ответы клиентам,
  чтобы операторы могли легко найти конкретный запрос в Jaeger.
"""
from __future__ import annotations

import logging
import asyncio
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import audit_logger
from app.core.config import settings
from app.core.slo_metrics import (
    slo_latency_bucket,
    slo_success_requests,
    slo_total_requests,
)
from app.core.tracing import get_current_trace_id

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


class TimeoutMiddleware:
    """ASGI middleware that caps total request processing time."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send),
                timeout=float(settings.HTTP_REQUEST_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            response = JSONResponse(
                status_code=504,
                content={
                    "detail": (
                        f"Request timeout after "
                        f"{settings.HTTP_REQUEST_TIMEOUT_SECONDS} seconds"
                    )
                },
            )
            await response(scope, receive, send)


class TracingMiddleware:
    """ASGI-middleware, пробрасывающий ``X-Trace-Id`` в ответы клиентам.

    Работает поверх инструментации FastAPI от OpenTelemetry: когда
    ``FastAPIInstrumentor`` создаёт серверный span для запроса, его
    ``trace_id`` становится "текущим" в контексте. Мы оборачиваем ``send``,
    чтобы добавить к ``http.response.start`` заголовок ``X-Trace-Id`` —
    это позволяет в логах/ответах клиента видеть идентификатор трассы
    и искать её в Jaeger без дополнительных запросов.

    Если tracing отключён (``OTEL_ENABLED=false``) или OpenTelemetry не
    установлен, ``get_current_trace_id()`` вернёт пустую строку и
    middleware не добавит заголовок — поведение полностью прозрачно.

    Важно: по семантике Starlette этот класс должен быть зарегистрирован
    ПОСЛЕ всех других ASGI-слоёв, чтобы к моменту вызова ``send`` уже
    был активен серверный span (его создаёт ``FastAPIInstrumentor``
    изнутри при обработке запроса).
    """

    TRACE_HEADER: bytes = b"x-trace-id"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                trace_id = get_current_trace_id()
                if trace_id:
                    headers = list(message.get("headers") or [])
                    # Удаляем дубликаты, если кто-то уже выставил заголовок.
                    headers = [
                        (k, v) for (k, v) in headers if k.lower() != self.TRACE_HEADER
                    ]
                    headers.append((self.TRACE_HEADER, trace_id.encode("ascii")))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Пути, которые не должны попадать в SLO-счётчики: инфраструктурные
# probes и собственный /metrics (иначе Prometheus сам генерит «success»
# и искажает availability).
_SLO_EXCLUDED_PATHS: frozenset[str] = frozenset(
    {
        "/metrics",
        "/health",
        "/health/live",
        "/health/ready",
        "/health/features",
        "/health/deployment",
    }
)


class SLOMiddleware:
    """ASGI-middleware, собирающий SLI-метрики для SLO-расчётов.

    На каждый HTTP-запрос (кроме health/metrics) инкрементирует:

    - ``smdg_slo_total_requests_total{slo_name="api_availability"}``
    - ``smdg_slo_success_requests_total{slo_name="api_availability"}``
      для ответов 2xx-3xx (4xx и 5xx считаются ошибками SLO).

    Также кладёт длительность запроса в histogram
    ``smdg_slo_latency_seconds`` — на этой основе коллектор считает
    p50/p90/p99.

    Важно:
        Middleware не трогает стандартные ``http_requests_total`` /
        ``http_request_duration_seconds_*`` от
        ``prometheus-fastapi-instrumentator`` — они экспонируются
        параллельно и используются в PromQL-запросах дашборда.

    Порядок регистрации:
        SLO-middleware должен быть максимально внешним слоем, чтобы
        учитывать запросы, отклонённые rate-limiter'ом и
        ActiveRequests. См. ``app/main.py``.
    """

    SLO_NAME: str = "api_availability"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path in _SLO_EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        import time as _time  # local import: не нужен для non-http веток

        start = _time.perf_counter()
        status_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Любое необработанное исключение — SLO-ошибка. Код
            # по умолчанию (500) уже стоит, просто инкрементируем
            # total и пробрасываем исключение дальше по стеку.
            status_holder["code"] = 500
            raise
        finally:
            duration = _time.perf_counter() - start
            slo_total_requests.labels(slo_name=self.SLO_NAME).inc()
            if 200 <= status_holder["code"] < 400:
                slo_success_requests.labels(slo_name=self.SLO_NAME).inc()
            slo_latency_bucket.observe(duration)


__all__ = [
    "AuditMiddleware",
    "ActiveRequestsMiddleware",
    "TimeoutMiddleware",
    "TracingMiddleware",
    "SLOMiddleware",
]
