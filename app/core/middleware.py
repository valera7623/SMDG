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
import gzip
from typing import Awaitable, Callable

try:
    import brotli
except ModuleNotFoundError:  # pragma: no cover - depends on runtime image
    brotli = None
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import audit_logger
from app.core.bulkhead import BulkheadRejectedError, BulkheadTimeoutError, get_bulkhead
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

        # ASGI-транспорты (например httpx ASGITransport) часто не вызывают lifespan;
        # без этого обращение к app.state падает до инициализации в lifespan.
        if not hasattr(state, "active_requests_lock"):
            state.active_requests_lock = asyncio.Lock()
        if not hasattr(state, "active_requests"):
            state.active_requests = 0

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

        response_started = False

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, guarded_send),
                timeout=float(settings.HTTP_REQUEST_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            # If app already started sending response, it is unsafe to emit another one.
            if response_started:
                logger.warning(
                    "HTTP request timed out after %.2fs, but response already started",
                    float(settings.HTTP_REQUEST_TIMEOUT_SECONDS),
                )
                return
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


class BulkheadMiddleware:
    """ASGI middleware for API-level bulkhead isolation."""

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

        if not settings.BULKHEAD_ENABLED:
            await self.app(scope, receive, send)
            return

        bulkhead = get_bulkhead("api")
        try:
            await bulkhead.execute(self.app, scope, receive, send)
        except BulkheadRejectedError:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Service is overloaded. Please try again later.",
                    "retry_after": 5,
                },
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
        except BulkheadTimeoutError:
            response = JSONResponse(
                status_code=504,
                content={"detail": "Gateway timeout while waiting for API worker slot"},
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


class CompressionMiddleware:
    """ASGI-middleware for response compression with Brotli/Gzip fallback."""

    _DEFAULT_CONTENT_TYPES: tuple[str, ...] = (
        "text/plain",
        "text/html",
        "text/css",
        "text/xml",
        "text/javascript",
        "application/json",
        "application/javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
        "application/ld+json",
        "application/manifest+json",
        "application/vnd.api+json",
        "application/dicom+json",
        "image/svg+xml",
    )

    # prefix, minimum size, gzip level, brotli level, allow_brotli, allow_gzip
    _POLICY: tuple[tuple[str, int, int, int, bool, bool], ...] = (
        ("application/dicom+json", 1000, 6, 6, False, True),
        ("text/html", 500, 9, 9, True, True),
        ("text/css", 500, 9, 9, True, True),
        ("application/javascript", 500, 9, 9, True, True),
        ("application/json", 500, 6, 6, True, True),
        ("image/svg+xml", 1000, 5, 5, False, True),
    )

    _SKIP_PREFIXES: tuple[str, ...] = (
        "image/png",
        "application/pdf",
        "application/dicom",
    )

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,
        compressible_types: list[str] | None = None,
        brotli_enabled: bool = True,
        gzip_enabled: bool = True,
        gzip_level: int = 6,
        brotli_quality: int = 6,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compressible_types = tuple(compressible_types or self._DEFAULT_CONTENT_TYPES)
        self.brotli_enabled = brotli_enabled
        self.gzip_enabled = gzip_enabled
        self.gzip_level = max(1, min(gzip_level, 9))
        self.brotli_quality = max(1, min(brotli_quality, 11))
        if brotli is None:
            self.brotli_enabled = False

    def _get_policy(self, content_type: str) -> tuple[int, int, int, bool, bool]:
        ctype = content_type.lower()
        for prefix in self._SKIP_PREFIXES:
            if ctype.startswith(prefix):
                return (0, 0, 0, False, False)
        for (
            prefix,
            min_size,
            gzip_level,
            brotli_level,
            allow_brotli,
            allow_gzip,
        ) in self._POLICY:
            if ctype.startswith(prefix):
                return (
                    min_size,
                    gzip_level,
                    brotli_level,
                    allow_brotli and self.brotli_enabled,
                    allow_gzip and self.gzip_enabled,
                )
        if any(ctype.startswith(t.lower()) for t in self.compressible_types):
            return (
                self.minimum_size,
                self.gzip_level,
                self.brotli_quality,
                self.brotli_enabled,
                self.gzip_enabled,
            )
        return (0, 0, 0, False, False)

    @staticmethod
    def _parse_accept_encoding(raw_value: str) -> tuple[bool, bool]:
        if not raw_value:
            return False, False
        value = raw_value.lower()
        wildcard = "*" in value
        supports_br = "br" in value
        supports_gzip = "gzip" in value
        if wildcard:
            supports_br = True
            supports_gzip = True
        return supports_br, supports_gzip

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        req_br, req_gzip = self._parse_accept_encoding(
            request.headers.get("accept-encoding", "")
        )
        if not req_br and not req_gzip:
            await self.app(scope, receive, send)
            return

        response_started = False
        status_code: int = 200
        headers: list[tuple[bytes, bytes]] = []
        chunks: list[bytes] = []
        more_body_expected = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, status_code, headers, more_body_expected

            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                return

            if message["type"] != "http.response.body":
                await send(message)
                return

            body = message.get("body", b"")
            if body:
                chunks.append(body)
            more_body_expected = bool(message.get("more_body", False))
            if more_body_expected:
                return

            if not response_started:
                # Defensive fallback: malformed app message order.
                await send({"type": "http.response.start", "status": status_code, "headers": headers})

            body_bytes = b"".join(chunks)
            final_headers = self._compress_headers_and_body(
                headers=headers,
                body=body_bytes,
                content_accepts_br=req_br,
                content_accepts_gzip=req_gzip,
                status_code=status_code,
            )

            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": final_headers[0],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": final_headers[1],
                    "more_body": False,
                }
            )

        await self.app(scope, receive, send_wrapper)

    def _compress_headers_and_body(
        self,
        headers: list[tuple[bytes, bytes]],
        body: bytes,
        content_accepts_br: bool,
        content_accepts_gzip: bool,
        status_code: int,
    ) -> tuple[list[tuple[bytes, bytes]], bytes]:
        # 204/304 и ответы без тела не трогаем.
        if status_code in (204, 304) or not body:
            return headers, body

        lowered: dict[bytes, bytes] = {k.lower(): v for k, v in headers}
        if b"content-encoding" in lowered:
            return headers, body

        content_type = lowered.get(b"content-type", b"").decode("latin-1").split(";")[0].strip()
        if not content_type:
            return headers, body

        min_size, gzip_level, brotli_level, allow_brotli, allow_gzip = self._get_policy(content_type)
        if min_size <= 0 or len(body) < min_size:
            return headers, body

        selected_encoding: str | None = None
        compressed_body = body

        try:
            if content_accepts_br and allow_brotli and brotli is not None:
                candidate = brotli.compress(body, quality=brotli_level)
                if len(candidate) < len(body):
                    selected_encoding = "br"
                    compressed_body = candidate
            if selected_encoding is None and content_accepts_gzip and allow_gzip:
                candidate = gzip.compress(body, compresslevel=gzip_level)
                if len(candidate) < len(body):
                    selected_encoding = "gzip"
                    compressed_body = candidate
        except Exception as exc:  # pragma: no cover
            logger.warning("Compression failed: %s", exc)
            return headers, body

        if not selected_encoding:
            return headers, body

        out_headers = [
            (k, v)
            for (k, v) in headers
            if k.lower() not in (b"content-length", b"content-encoding")
        ]
        out_headers.append((b"content-encoding", selected_encoding.encode("ascii")))
        out_headers.append((b"content-length", str(len(compressed_body)).encode("ascii")))

        vary = lowered.get(b"vary")
        if vary is None:
            out_headers.append((b"vary", b"Accept-Encoding"))
        elif b"accept-encoding" not in vary.lower():
            out_headers.append((b"vary", vary + b", Accept-Encoding"))

        return out_headers, compressed_body


__all__ = [
    "AuditMiddleware",
    "ActiveRequestsMiddleware",
    "TimeoutMiddleware",
    "BulkheadMiddleware",
    "TracingMiddleware",
    "SLOMiddleware",
    "CompressionMiddleware",
]
