"""Тесты для Readiness / Liveness probes (``app/api/health.py``).

Покрываем сценарии, критичные для production:

* ``/health/live``                   — всегда 200.
* ``/health/ready`` — happy path     — 200 когда все проверки успешны.
* ``/health/ready`` — shutting_down  — 503 во время graceful shutdown.
* ``/health/ready`` — overloaded     — 503 при превышении MAX_CONCURRENT_REQUESTS.
* ``/health/ready`` — БД недоступна  — 503 с ``dependencies_unavailable``.
* ``/health/ready`` — Redis недоступен — 503.
* ``/health/ready`` — Storage недоступен — 503.
* ``/health/checks`` — admin-only    — 200 для admin, 401 без токена.
* TTL-кэш не вызывает нижележащие проверки повторно в пределах окна.

Все внешние зависимости замокированы, тесты быстрые (<1с суммарно).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api import health as health_module
from app.core.auth import get_current_admin, get_current_user
from app.core.auth_utils import TokenData
from app.main import app


# ──────────────────────────────────────────────────────────────────────
# Фикстуры
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_cache_and_state():
    """Сброс TTL-кэша, app.state и rate limiter до/после каждого теста.

    * Сбрасываем модульный ``_checks_cache``, чтобы результаты проверок
      из предыдущего теста не "протекали" в следующий.
    * Выставляем ``active_requests`` / ``shutting_down`` в изначальные значения.
    * Отключаем slowapi limiter: в ``app/main.py`` создаётся отдельный
      экземпляр с ``storage_uri=settings.redis_url`` (реальный Redis),
      который не отключается через ``app.core.rate_limiter.limiter``.
    """
    health_module._checks_cache.invalidate()
    app.state.shutting_down = False
    app.state.active_requests = 0
    if not hasattr(app.state, "active_requests_lock"):
        app.state.active_requests_lock = asyncio.Lock()
    if hasattr(app.state, "limiter"):
        app.state.limiter.enabled = False
    yield
    health_module._checks_cache.invalidate()
    app.state.shutting_down = False
    app.state.active_requests = 0


@pytest.fixture
def health_client():
    """Лёгкий TestClient без фикстур из conftest (БД/Redis здесь не нужны)."""
    with TestClient(app) as client:
        yield client


def _patch_checks(
    *,
    database_ok: bool = True,
    redis_ok: bool = True,
    storage_ok: bool = True,
    dicom_ok: bool = True,
):
    """Контекст-менеджер: мокаем низкоуровневые ``_do_check_*`` функции.

    Возвращаем готовые патчи, которые надо использовать через ``with``
    в каждом тесте. Мы мокаем именно "низкий" уровень, чтобы проверить
    также обёртку ``_timed`` и кэш.
    """

    async def _ok() -> None:
        return None

    async def _fail(name: str):
        raise RuntimeError(f"{name} unavailable (test)")

    patches = [
        patch.object(
            health_module,
            "_do_check_database",
            new=(lambda: _ok()) if database_ok else (lambda: _fail("db")),
        ),
        patch.object(
            health_module,
            "_do_check_redis",
            new=(lambda: _ok()) if redis_ok else (lambda: _fail("redis")),
        ),
        patch.object(
            health_module,
            "_do_check_storage",
            new=(lambda: _ok()) if storage_ok else (lambda: _fail("storage")),
        ),
        patch.object(
            health_module,
            "_do_check_dicom_viewer",
            new=(lambda: _ok()) if dicom_ok else (lambda: _fail("dicom")),
        ),
    ]
    return patches


# ──────────────────────────────────────────────────────────────────────
# /health/live
# ──────────────────────────────────────────────────────────────────────


class TestLivenessProbe:
    """Liveness probe НИКОГДА не должна возвращать != 200 при живом процессе."""

    def test_live_returns_200(self, health_client):
        resp = health_client.get("/health/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alive"
        assert "timestamp" in data

    def test_live_ignores_shutting_down(self, health_client):
        """Даже во время shutdown /health/live должна отвечать 200."""
        app.state.shutting_down = True
        resp = health_client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    def test_live_ignores_db_failure(self, health_client):
        """/health/live не проверяет зависимости — 200 даже если БД мертва."""
        with patch.object(
            health_module,
            "_do_check_database",
            new=lambda: (_ for _ in ()).throw(RuntimeError("DB dead")),
        ):
            resp = health_client.get("/health/live")
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# /health/ready — happy path
# ──────────────────────────────────────────────────────────────────────


class TestReadinessProbeHappy:
    def test_ready_all_checks_pass(self, health_client):
        patches = _patch_checks()
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/ready")
        finally:
            for p in patches:
                p.stop()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True
        assert data["checks"]["database"] is True
        assert data["checks"]["redis"] is True
        assert data["checks"]["storage"] is True
        assert data["max_requests"] >= 1
        assert "timestamp" in data


# ──────────────────────────────────────────────────────────────────────
# /health/ready — shutting_down
# ──────────────────────────────────────────────────────────────────────


class TestReadinessShuttingDown:
    def test_shutting_down_returns_503(self, health_client):
        app.state.shutting_down = True
        resp = health_client.get("/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["ready"] is False
        assert data["reason"] == "shutting_down"
        assert "message" in data
        assert resp.headers.get("retry-after") == "30"

    def test_shutting_down_skips_dependency_checks(self, health_client):
        """Во время shutdown НЕ должны вызываться проверки зависимостей."""
        app.state.shutting_down = True
        called = {"db": False}

        async def _tracked_db():
            called["db"] = True

        with patch.object(health_module, "_do_check_database", new=_tracked_db):
            resp = health_client.get("/health/ready")

        assert resp.status_code == 503
        assert called["db"] is False, "DB check не должна вызываться при shutdown"


# ──────────────────────────────────────────────────────────────────────
# /health/ready — overloaded
# ──────────────────────────────────────────────────────────────────────


class TestReadinessOverloaded:
    def test_overloaded_returns_503(self, health_client):
        from app.core.config import settings

        app.state.active_requests = settings.max_concurrent_requests + 10
        patches = _patch_checks()
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/ready")
        finally:
            for p in patches:
                p.stop()

        assert resp.status_code == 503
        data = resp.json()
        assert data["ready"] is False
        assert data["reason"] == "overloaded"
        assert data["active_requests"] >= data["max_requests"]
        assert resp.headers.get("retry-after") == "5"

    def test_overloaded_has_priority_over_dependencies(self, health_client):
        """Overload проверяется ДО зависимостей — fail fast."""
        from app.core.config import settings

        app.state.active_requests = settings.max_concurrent_requests + 1
        patches = _patch_checks(database_ok=False)
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/ready")
        finally:
            for p in patches:
                p.stop()

        data = resp.json()
        assert resp.status_code == 503
        assert data["reason"] == "overloaded", \
            "При overloaded reason не должен становиться dependencies_unavailable"


# ──────────────────────────────────────────────────────────────────────
# /health/ready — dependencies unavailable
# ──────────────────────────────────────────────────────────────────────


class TestReadinessDependenciesUnavailable:
    def test_database_down_returns_503(self, health_client):
        patches = _patch_checks(database_ok=False)
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/ready")
        finally:
            for p in patches:
                p.stop()

        assert resp.status_code == 503
        data = resp.json()
        assert data["ready"] is False
        assert data["reason"] == "dependencies_unavailable"
        assert data["checks"]["database"] is False
        assert data["checks"]["redis"] is True
        assert data["checks"]["storage"] is True

    def test_redis_down_returns_503(self, health_client):
        patches = _patch_checks(redis_ok=False)
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/ready")
        finally:
            for p in patches:
                p.stop()

        assert resp.status_code == 503
        data = resp.json()
        assert data["reason"] == "dependencies_unavailable"
        assert data["checks"]["redis"] is False

    def test_storage_down_returns_503(self, health_client):
        patches = _patch_checks(storage_ok=False)
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/ready")
        finally:
            for p in patches:
                p.stop()

        assert resp.status_code == 503
        data = resp.json()
        assert data["reason"] == "dependencies_unavailable"
        assert data["checks"]["storage"] is False

    def test_dependency_timeout_marked_as_failure(self, health_client):
        """Если проверка превышает timeout — считаем её провалившейся."""
        from app.core.config import settings

        async def _hang():
            await asyncio.sleep(settings.readiness_check_timeout + 5)

        with patch.object(health_module, "_do_check_database", new=_hang), \
             patch.object(health_module, "_do_check_redis", new=lambda: asyncio.sleep(0)), \
             patch.object(health_module, "_do_check_storage", new=lambda: asyncio.sleep(0)), \
             patch.object(health_module, "_do_check_dicom_viewer", new=lambda: asyncio.sleep(0)):
            resp = health_client.get("/health/ready")

        assert resp.status_code == 503
        data = resp.json()
        assert data["reason"] == "dependencies_unavailable"
        assert data["checks"]["database"] is False


# ──────────────────────────────────────────────────────────────────────
# Кэширование
# ──────────────────────────────────────────────────────────────────────


class TestReadinessCaching:
    def test_cache_reuses_result_within_ttl(self, health_client):
        """Несколько probe подряд не должны вызывать проверки N раз."""
        call_count = {"db": 0}

        async def _counting_db():
            call_count["db"] += 1

        with patch.object(health_module, "_do_check_database", new=_counting_db), \
             patch.object(health_module, "_do_check_redis", new=lambda: asyncio.sleep(0)), \
             patch.object(health_module, "_do_check_storage", new=lambda: asyncio.sleep(0)), \
             patch.object(health_module, "_do_check_dicom_viewer", new=lambda: asyncio.sleep(0)):
            for _ in range(5):
                resp = health_client.get("/health/ready")
                assert resp.status_code == 200

        assert call_count["db"] == 1, \
            f"DB check вызвался {call_count['db']} раз, ожидалось 1 (кэш)"

    def test_cache_invalidate_forces_recheck(self, health_client):
        """После invalidate() проверка запускается заново."""
        call_count = {"db": 0}

        async def _counting_db():
            call_count["db"] += 1

        with patch.object(health_module, "_do_check_database", new=_counting_db), \
             patch.object(health_module, "_do_check_redis", new=lambda: asyncio.sleep(0)), \
             patch.object(health_module, "_do_check_storage", new=lambda: asyncio.sleep(0)), \
             patch.object(health_module, "_do_check_dicom_viewer", new=lambda: asyncio.sleep(0)):
            health_client.get("/health/ready")
            health_module._checks_cache.invalidate()
            health_client.get("/health/ready")

        assert call_count["db"] == 2


# ──────────────────────────────────────────────────────────────────────
# /health/checks — admin-only
# ──────────────────────────────────────────────────────────────────────


class TestDetailedChecksAdminOnly:
    def test_checks_requires_auth(self, health_client):
        """Без admin-токена — 401/403."""
        app.dependency_overrides.pop(get_current_admin, None)
        resp = health_client.get("/health/checks")
        assert resp.status_code in (401, 403)

    def test_checks_returns_detailed_info_for_admin(self, health_client):
        """С override'ом admin-зависимости получаем полный отчёт."""

        async def _admin():
            return TokenData(sub="admin", role="admin", tenant_id=1)

        app.dependency_overrides[get_current_admin] = _admin
        patches = _patch_checks()
        for p in patches:
            p.start()
        try:
            resp = health_client.get("/health/checks")
        finally:
            for p in patches:
                p.stop()
            app.dependency_overrides.pop(get_current_admin, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "database" in data["checks"]
        assert "redis" in data["checks"]
        assert "storage" in data["checks"]
        assert "dicom_viewer" in data["checks"]
        assert "latency_ms" in data["checks"]["database"]
        assert data["active_requests"] >= 0
        assert data["max_requests"] >= 1
        assert data["config"]["max_concurrent_requests"] == data["max_requests"]


# ──────────────────────────────────────────────────────────────────────
# Legacy endpoints (smoke)
# ──────────────────────────────────────────────────────────────────────


class TestLegacyHealthEndpoints:
    def _with_admin(self):
        async def _admin():
            return TokenData(sub="admin", role="admin", tenant_id=1)

        app.dependency_overrides[get_current_admin] = _admin

    def test_features_endpoint(self, health_client):
        self._with_admin()
        try:
            resp = health_client.get("/health/features")
            assert resp.status_code == 200
            data = resp.json()
            assert "deployment_type" in data
            assert "features" in data
        finally:
            app.dependency_overrides.pop(get_current_admin, None)

    def test_deployment_endpoint(self, health_client):
        self._with_admin()
        try:
            resp = health_client.get("/health/deployment")
            assert resp.status_code == 200
            assert "deployment_type" in resp.json()
        finally:
            app.dependency_overrides.pop(get_current_admin, None)
