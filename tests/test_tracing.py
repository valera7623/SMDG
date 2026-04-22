"""Tests for distributed tracing (``app/core/tracing.py``, ``app/api/tracing.py``).

Covers three layers:

1. **Fail-open setup**: ``setup_tracing`` никогда не ломает приложение —
   когда ``OTEL_ENABLED=false``, когда пакеты OpenTelemetry не установлены,
   и когда коллектор недоступен.
2. **No-op fallback**: ``get_tracer`` и ``get_current_trace_id`` безопасно
   возвращают валидные объекты/пустую строку без OpenTelemetry.
3. **Admin tracing API**: ``/api/tracing/search`` и ``/api/tracing/trace/{id}``
   требуют авторизации и корректно обрабатывают недоступность Jaeger.

Тесты намеренно избегают реального запуска OTLP-экспортёра: достаточно
проверить корректность каркаса, graceful degradation и HTTP-контрактов.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import tracing as tracing_module
from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.main import app


# ──────────────────────────────────────────────────────────────────────
# Общие фикстуры
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_tracing_state(monkeypatch):
    """Сбрасываем глобальные переменные модуля tracing между тестами.

    Без этого setup_tracing из предыдущего теста оставит _TRACING_ENABLED=True
    и последующие вызовы станут идемпотентными no-op'ами, что скрывает баги.

    Дополнительно отключаем slowapi limiter, который в app.main создаётся
    поверх реального Redis — в sandbox-окружении тестов Redis может быть
    недоступен, а без этой защиты любой запрос падает с ConnectionError.
    """
    monkeypatch.setattr(tracing_module, "_TRACING_ENABLED", False)
    monkeypatch.setattr(tracing_module, "_TRACER_PROVIDER", None)
    monkeypatch.setattr(tracing_module, "_TRACER", None)
    for key in (
        "OTEL_ENABLED",
        "OTEL_SERVICE_NAME",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_TRACES_SAMPLER",
        "OTEL_TRACES_SAMPLER_ARG",
    ):
        monkeypatch.delenv(key, raising=False)
    # Disable the slowapi limiter that app.main binds to app.state.
    if hasattr(app.state, "limiter"):
        app.state.limiter.enabled = False
    yield


@pytest.fixture
def admin_override():
    """Подменяет get_current_admin на тестового администратора."""
    def _get_admin() -> TokenData:
        return TokenData(sub="admin", role="admin", tenant_id=1)

    app.dependency_overrides[get_current_admin] = _get_admin
    yield
    app.dependency_overrides.pop(get_current_admin, None)


# ──────────────────────────────────────────────────────────────────────
# setup_tracing / shutdown_tracing
# ──────────────────────────────────────────────────────────────────────


class TestSetupTracing:
    """Поведение ``setup_tracing`` в разных окружениях."""

    def test_disabled_by_default_returns_none(self, monkeypatch):
        """Без OTEL_ENABLED setup_tracing должен вернуть None и не трогать app."""
        monkeypatch.delenv("OTEL_ENABLED", raising=False)
        fake_app = MagicMock()

        result = tracing_module.setup_tracing(fake_app)

        assert result is None
        assert tracing_module.is_tracing_enabled() is False

    def test_disabled_explicitly(self, monkeypatch):
        monkeypatch.setenv("OTEL_ENABLED", "false")
        result = tracing_module.setup_tracing(MagicMock())
        assert result is None

    def test_idempotent_double_init(self, monkeypatch):
        """Повторный вызов setup_tracing не должен падать и не переинициализировать."""
        monkeypatch.setattr(tracing_module, "_TRACING_ENABLED", True)
        monkeypatch.setattr(tracing_module, "_TRACER", "sentinel")
        result = tracing_module.setup_tracing(MagicMock())
        assert result == "sentinel"

    def test_fail_open_on_import_error(self, monkeypatch):
        """Если OpenTelemetry не установлен — не должно быть исключения."""
        monkeypatch.setenv("OTEL_ENABLED", "true")
        # Эмулируем отсутствие пакета: setup_tracing делает импорт ВНУТРИ
        # функции, поэтому мы можем подставить заглушку через встроенный
        # __import__ hook. Проще — патчим тот единственный импорт через
        # monkeypatch builtins.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("opentelemetry"):
                raise ImportError(f"mocked missing {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        result = tracing_module.setup_tracing(MagicMock())
        assert result is None
        assert tracing_module.is_tracing_enabled() is False

    def test_fail_open_on_unexpected_error(self, monkeypatch):
        """Любое исключение внутри setup должно превращаться в None + log."""
        monkeypatch.setenv("OTEL_ENABLED", "true")

        # Патчим Resource.create, чтобы вылетала ошибка при попытке
        # собрать ресурс — всё остальное уже импортировано реально.
        try:
            from opentelemetry.sdk.resources import Resource  # type: ignore
        except ImportError:
            pytest.skip("opentelemetry-sdk not installed in this environment")

        def explode(*_a, **_kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(Resource, "create", staticmethod(explode))

        result = tracing_module.setup_tracing(MagicMock())
        assert result is None
        assert tracing_module.is_tracing_enabled() is False


class TestShutdownTracing:
    """Поведение ``shutdown_tracing``."""

    @pytest.mark.asyncio
    async def test_shutdown_without_init_is_noop(self):
        """Shutdown до init не должен падать."""
        await tracing_module.shutdown_tracing()

    @pytest.mark.asyncio
    async def test_shutdown_flushes_provider(self, monkeypatch):
        """Shutdown обязан вызвать force_flush + shutdown на провайдере."""
        provider = MagicMock()
        provider.force_flush = MagicMock()
        provider.shutdown = MagicMock()
        monkeypatch.setattr(tracing_module, "_TRACER_PROVIDER", provider)
        monkeypatch.setattr(tracing_module, "_TRACING_ENABLED", True)

        await tracing_module.shutdown_tracing()

        provider.force_flush.assert_called_once()
        provider.shutdown.assert_called_once()
        assert tracing_module.is_tracing_enabled() is False


# ──────────────────────────────────────────────────────────────────────
# No-op tracer / trace_id
# ──────────────────────────────────────────────────────────────────────


class TestNoopBehavior:
    """Проверяем, что отсутствие OpenTelemetry не мешает кастомным спанам."""

    def test_get_tracer_always_returns_usable_object(self):
        tracer = tracing_module.get_tracer("test")
        # Минимальный API, который используется в upload.py.
        assert hasattr(tracer, "start_as_current_span")
        with tracer.start_as_current_span("noop") as span:
            # Любые set_attribute/set_status НЕ должны падать.
            span.set_attribute("x", 1)
            span.set_status("ok")
            span.record_exception(ValueError("test"))

    def test_current_trace_id_without_active_span(self):
        """Без активного span возвращается пустая строка, а не 0/None."""
        trace_id = tracing_module.get_current_trace_id()
        assert trace_id == ""

    def test_is_enabled_false_without_setup(self):
        assert tracing_module.is_tracing_enabled() is False


# ──────────────────────────────────────────────────────────────────────
# /api/tracing/* (admin API поверх Jaeger)
# ──────────────────────────────────────────────────────────────────────


class TestTracingAPI:
    """HTTP-контракты для admin-эндпоинтов tracing.

    Фикстура ``db_session`` тут намеренно НЕ используется: эти тесты
    проверяют только контракт HTTP-уровня, а все внешние зависимости
    замокированы. Подключения к Postgres не нужны — и не должны быть
    обязательны для прохождения unit-тестов в CI без DB-сервиса.
    """

    def test_search_requires_auth(self):
        """Без авторизации — 401."""
        with TestClient(app) as client:
            response = client.get("/api/tracing/search")
        assert response.status_code == 401

    def test_search_success_returns_jaeger_payload(self, admin_override):
        fake_payload = {"data": [{"traceID": "abc123"}], "total": 1}

        class _FakeResponse:
            status_code = 200

            def json(self):
                return fake_payload

            @property
            def text(self):
                return "ok"

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None):
                assert "/api/traces" in url
                assert params["service"] == "smdg"
                return _FakeResponse()

        with patch("app.api.tracing.httpx.AsyncClient", _FakeClient):
            with TestClient(app) as client:
                response = client.get("/api/tracing/search?service=smdg&limit=5")

        assert response.status_code == 200
        assert response.json() == fake_payload

    def test_search_limit_validated(self, admin_override):
        """limit > 200 должен вернуть 422 от Pydantic-валидатора."""
        with TestClient(app) as client:
            response = client.get("/api/tracing/search?limit=10000")
        assert response.status_code == 422

    def test_jaeger_unavailable_returns_503(self, admin_override):
        """Недоступный Jaeger → 503, а не 500."""
        class _FailingClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                raise httpx.ConnectError("no route to host")

        with patch("app.api.tracing.httpx.AsyncClient", _FailingClient):
            with TestClient(app) as client:
                response = client.get("/api/tracing/search")

        assert response.status_code == 503

    def test_trace_id_format_validated(self, admin_override):
        """Невалидный trace_id не должен попасть в Jaeger."""
        with TestClient(app) as client:
            response = client.get("/api/tracing/trace/" + "x" * 100)
        assert response.status_code == 400

    def test_trace_not_found_bubbles_up_as_404(self, admin_override):
        class _NotFoundResponse:
            status_code = 404
            text = "not found"

            def json(self):
                return {"data": []}

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                return _NotFoundResponse()

        with patch("app.api.tracing.httpx.AsyncClient", _Client):
            with TestClient(app) as client:
                response = client.get("/api/tracing/trace/abcdef0123456789abcdef0123456789")

        assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────
# Middleware
# ──────────────────────────────────────────────────────────────────────


class TestTracingMiddleware:
    """TracingMiddleware добавляет X-Trace-Id только когда trace_id валиден."""

    def test_no_header_when_tracing_disabled(self):
        """При отключённом tracing заголовка X-Trace-Id быть не должно."""
        with TestClient(app) as client:
            response = client.get("/health/live")
        # get_current_trace_id() вернёт "" без активного span → заголовка нет.
        assert "x-trace-id" not in {k.lower() for k in response.headers.keys()}

    def test_header_added_when_trace_id_present(self, monkeypatch):
        """Если get_current_trace_id() возвращает hex, middleware его пробрасывает."""
        fake_id = "a" * 32

        monkeypatch.setattr(
            "app.core.middleware.get_current_trace_id",
            lambda: fake_id,
        )

        with TestClient(app) as client:
            response = client.get("/health/live")

        assert response.headers.get("x-trace-id") == fake_id
