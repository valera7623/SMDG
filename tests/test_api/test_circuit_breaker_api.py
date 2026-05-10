"""HTTP-тесты для ``app/api/circuit_breaker.py``."""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def admin_td() -> TokenData:
    return TokenData(sub="admin-cb", role="admin", tenant_id=1)


@pytest_asyncio.fixture
async def circuit_breaker_api_client(admin_td):
    async def _admin():
        return admin_td

    app.dependency_overrides[get_current_admin] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Tenant-ID": "1"},
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_status_lists_registered_breakers(circuit_breaker_api_client):
    name = f"api_cb_{time.time_ns()}"
    cb = CircuitBreaker(name=name, failure_threshold=3)
    import app.core.circuit_breaker as cb_core

    cb_core._circuit_breakers[name] = cb

    try:
        r = await circuit_breaker_api_client.get("/api/circuit-breaker/status")
        assert r.status_code == 200
        body = r.json()
        assert "summary" in body and "breakers" in body
        assert name in body["breakers"]
        assert body["summary"]["total"] >= 1
    finally:
        del cb_core._circuit_breakers[name]


@pytest.mark.asyncio
async def test_status_single_found(circuit_breaker_api_client):
    name = f"api_cb_one_{time.time_ns()}"
    cb = CircuitBreaker(name=name, failure_threshold=2)
    import app.core.circuit_breaker as cb_core

    cb_core._circuit_breakers[name] = cb

    try:
        r = await circuit_breaker_api_client.get(f"/api/circuit-breaker/status/{name}")
        assert r.status_code == 200
        assert r.json()["name"] == name
        assert r.json()["state"] == "closed"
    finally:
        del cb_core._circuit_breakers[name]


@pytest.mark.asyncio
async def test_status_single_not_found_returns_404(circuit_breaker_api_client):
    r = await circuit_breaker_api_client.get("/api/circuit-breaker/status/nonexistent_xyz_999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reset_known_breaker(circuit_breaker_api_client):
    name = f"api_cb_reset_{time.time_ns()}"
    cb = CircuitBreaker(name=name, failure_threshold=1)
    import app.core.circuit_breaker as cb_core

    cb_core._circuit_breakers[name] = cb
    cb._state = CircuitState.OPEN  # noqa: SLF001

    try:
        r = await circuit_breaker_api_client.post(f"/api/circuit-breaker/reset/{name}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "reset"
        assert data["current_state"] == "closed"
        assert cb.state is CircuitState.CLOSED
    finally:
        del cb_core._circuit_breakers[name]


@pytest.mark.asyncio
async def test_reset_unknown_returns_404(circuit_breaker_api_client):
    r = await circuit_breaker_api_client.post("/api/circuit-breaker/reset/missing_br_404")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reset_all(circuit_breaker_api_client):
    name = f"api_cb_ra_{time.time_ns()}"
    cb = CircuitBreaker(name=name, failure_threshold=1)
    import app.core.circuit_breaker as cb_core

    cb_core._circuit_breakers[name] = cb
    cb._state = CircuitState.HALF_OPEN  # noqa: SLF001

    try:
        r = await circuit_breaker_api_client.post("/api/circuit-breaker/reset-all")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "reset-all"
        assert name in data["reset"]
        assert cb.state is CircuitState.CLOSED
    finally:
        del cb_core._circuit_breakers[name]
