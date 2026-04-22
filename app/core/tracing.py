"""
OpenTelemetry distributed tracing configuration for SMDG.

This module wires FastAPI, SQLAlchemy, Redis and HTTPX into a single trace
pipeline that ships spans to an OTLP collector (Jaeger via
``otel/opentelemetry-collector-contrib``).

Design goals
------------
* **Fail-open** — if the OTLP endpoint is unreachable or OpenTelemetry is not
  installed at all, the application must keep serving requests. All tracing
  calls must degrade to no-ops.
* **Low overhead** — sampling is controlled via
  ``OTEL_TRACES_SAMPLER``/``OTEL_TRACES_SAMPLER_ARG`` (parent-based ratio
  sampler at 10% by default). Span export uses ``BatchSpanProcessor`` to
  avoid synchronous I/O on the request path.
* **Privacy** — only non-sensitive attributes are emitted (file sizes,
  MIME types, storage keys). Health/metrics probes are excluded from
  instrumentation to reduce noise and avoid leaking readiness details.
* **Propagation** — B3 (single + multi header) is used to be compatible
  with the existing nginx upstream that forwards ``x-b3-*`` headers.

Environment variables
---------------------
OTEL_ENABLED
    Master switch. ``false`` disables the whole subsystem.
OTEL_SERVICE_NAME
    Service name reported to Jaeger (default ``smdg``).
OTEL_EXPORTER_OTLP_ENDPOINT
    gRPC endpoint of the collector (default ``http://otel-collector:4317``).
OTEL_TRACES_SAMPLER / OTEL_TRACES_SAMPLER_ARG
    Standard OpenTelemetry sampler env vars.
ENVIRONMENT
    ``production`` / ``staging`` / ``dev`` — added as a resource attribute.
SMDG_VERSION
    Application version for ``service.version``.

Public API
----------
* :func:`setup_tracing`     — one-shot initialisation called from lifespan.
* :func:`shutdown_tracing`  — graceful flush + provider shutdown.
* :func:`get_tracer`        — safe tracer accessor (returns no-op tracer
  when tracing is disabled).
* :func:`get_current_trace_id` — hex trace id of the active span or ``""``.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Optional imports — the whole subsystem is optional
# ──────────────────────────────────────────────────────────────────────
# We import lazily inside ``setup_tracing`` rather than at module level so
# that the application starts even when the opentelemetry-* packages are
# not installed (dev environments, slim tests, etc.).

_TRACING_ENABLED: bool = False
_TRACER_PROVIDER: Optional[Any] = None
_TRACER: Optional[Any] = None


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def is_tracing_enabled() -> bool:
    """Return whether tracing has been successfully initialised."""
    return _TRACING_ENABLED


def get_tracer(name: str = "smdg"):
    """Return a tracer that is safe to use even if tracing is disabled.

    When OpenTelemetry is not initialised, the returned object is the
    default no-op tracer from the OpenTelemetry API (which is itself safe
    to call); if the package is unavailable, a local no-op is returned.
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:  # pragma: no cover - import failure
        return _NoopTracer()


def get_current_trace_id() -> str:
    """Return hex-formatted trace id of the current span or empty string.

    Safe to call even if OpenTelemetry is not installed.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None:
            return ""
        ctx = span.get_span_context()
        if not ctx or not getattr(ctx, "is_valid", False):
            return ""
        return format(ctx.trace_id, "032x")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────
# No-op fallback
# ──────────────────────────────────────────────────────────────────────


class _NoopSpan:
    """Context-manager compatible span that does absolutely nothing."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # noqa: D401
        return False

    def set_attribute(self, *_args, **_kwargs) -> None:
        return None

    def set_status(self, *_args, **_kwargs) -> None:
        return None

    def record_exception(self, *_args, **_kwargs) -> None:
        return None

    def add_event(self, *_args, **_kwargs) -> None:
        return None

    def get_span_context(self):  # pragma: no cover - trivial
        return None


class _NoopTracer:
    """Tracer stub returned when OpenTelemetry is not available."""

    def start_as_current_span(self, *_args, **_kwargs) -> _NoopSpan:
        return _NoopSpan()

    def start_span(self, *_args, **_kwargs) -> _NoopSpan:
        return _NoopSpan()


# ──────────────────────────────────────────────────────────────────────
# Setup / shutdown
# ──────────────────────────────────────────────────────────────────────


def setup_tracing(
    app: "FastAPI",
    service_name: Optional[str] = None,
) -> Optional[Any]:
    """Initialise OpenTelemetry tracing for the given FastAPI app.

    Returns the global tracer on success or ``None`` when tracing is
    disabled/unavailable. This function is idempotent: subsequent calls
    are no-ops once tracing has been initialised.

    The function is deliberately defensive — any exception in imports or
    exporter setup is caught and logged (``warning``/``exception``) so
    that a misconfigured collector cannot bring down the API.
    """
    global _TRACING_ENABLED, _TRACER_PROVIDER, _TRACER

    if _TRACING_ENABLED:
        logger.debug("OpenTelemetry tracing already initialised")
        return _TRACER

    if not _env_truthy("OTEL_ENABLED", default=False):
        logger.info("OpenTelemetry tracing disabled (OTEL_ENABLED=false)")
        return None

    service_name = (
        service_name
        or os.getenv("OTEL_SERVICE_NAME")
        or "smdg"
    )

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.b3 import B3MultiFormat
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry packages not installed (%s); tracing disabled", exc
        )
        return None

    try:
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": os.getenv("SMDG_VERSION", "4.0.0"),
                "service.instance.id": os.getenv("HOSTNAME", "unknown"),
                "deployment.environment": os.getenv("ENVIRONMENT", "production"),
            }
        )

        tracer_provider = TracerProvider(resource=resource)

        endpoint = os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://otel-collector:4317",
        )
        otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        span_processor = BatchSpanProcessor(
            otlp_exporter,
            max_queue_size=2048,
            schedule_delay_millis=5000,
            max_export_batch_size=512,
        )
        tracer_provider.add_span_processor(span_processor)

        trace.set_tracer_provider(tracer_provider)
        set_global_textmap(B3MultiFormat())

        # ── Instrumentations ──────────────────────────────────────────
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="/health/live,/health/ready,/health/checks,/health/features,/health/deployment,/health,/metrics",
            tracer_provider=tracer_provider,
        )

        try:
            from app.core.database import get_engine

            engine = get_engine()
            sync_engine = getattr(engine, "sync_engine", engine)
            SQLAlchemyInstrumentor().instrument(
                engine=sync_engine,
                tracer_provider=tracer_provider,
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("SQLAlchemy instrumentation skipped: %s", exc)

        try:
            RedisInstrumentor().instrument(tracer_provider=tracer_provider)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Redis instrumentation skipped: %s", exc)

        try:
            HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("HTTPX instrumentation skipped: %s", exc)

        _TRACER_PROVIDER = tracer_provider
        _TRACER = trace.get_tracer(service_name)
        _TRACING_ENABLED = True

        logger.info(
            "✅ OpenTelemetry tracing initialised: service=%s endpoint=%s sampler=%s",
            service_name,
            endpoint,
            os.getenv("OTEL_TRACES_SAMPLER", "parentbased_always_on"),
        )
        return _TRACER

    except Exception as exc:
        logger.exception(
            "⚠️ Ошибка инициализации OpenTelemetry tracing: %s — приложение продолжит работать без трассировки",
            exc,
        )
        _TRACING_ENABLED = False
        _TRACER_PROVIDER = None
        _TRACER = None
        return None


async def shutdown_tracing() -> None:
    """Flush pending spans and shut down the tracer provider.

    Must be called from the lifespan shutdown hook to avoid losing the
    last batch of spans. Safe to call when tracing was never initialised.
    """
    global _TRACING_ENABLED, _TRACER_PROVIDER, _TRACER

    provider = _TRACER_PROVIDER
    if provider is None:
        return

    try:
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=3000)
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        logger.info("🔒 OpenTelemetry tracer provider остановлен")
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("⚠️ Ошибка остановки tracer provider: %s", exc)
    finally:
        _TRACER_PROVIDER = None
        _TRACER = None
        _TRACING_ENABLED = False


__all__ = [
    "setup_tracing",
    "shutdown_tracing",
    "get_tracer",
    "get_current_trace_id",
    "is_tracing_enabled",
]
