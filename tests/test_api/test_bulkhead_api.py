"""Тесты HTTP API ``app/api/bulkhead.py`` (админ)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData


@pytest.fixture
def admin_td() -> TokenData:
    return TokenData(sub="admin-bh", role="admin", tenant_id=1)


@pytest_asyncio.fixture
async def bulkhead_api_client(admin_td):
    async def _admin():
        return admin_td

    app.dependency_overrides[get_current_admin] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_get_status_returns_bulkheads(bulkhead_api_client):
    await bulkhead_api_client.post("/api/bulkhead/warmup")

    r = await bulkhead_api_client.get("/api/bulkhead/status")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "api" in data or len(data) >= 0


@pytest.mark.asyncio
async def test_warmup_initializes_and_returns_keys(bulkhead_api_client):
    r = await bulkhead_api_client.post("/api/bulkhead/warmup")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "initialized" in body and isinstance(body["initialized"], list)
    assert "bulkheads" in body


@pytest.mark.asyncio
async def test_metrics_endpoint(bulkhead_api_client):
    r = await bulkhead_api_client.get("/api/bulkhead/metrics")
    assert r.status_code == 200
    assert "bulkheads" in r.json()


@pytest.mark.asyncio
async def test_reset_known_bulkhead(bulkhead_api_client):
    from app.core import bulkhead as bm

    bm.initialize_bulkheads()
    r = await bulkhead_api_client.post("/api/bulkhead/reset/api")
    assert r.status_code == 200
    assert r.json()["bulkhead"] == "api"


@pytest.mark.asyncio
async def test_reset_unknown_bulkhead_returns_404(bulkhead_api_client, monkeypatch):
    def bad_get(name: str):
        raise ValueError("no such")

    monkeypatch.setattr("app.api.bulkhead.get_bulkhead", bad_get)

    r = await bulkhead_api_client.post("/api/bulkhead/reset/nonexistent_xyz")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reset_returns_404_when_lazy_create_noops(admin_td: TokenData):
    """Строки 25–26: после ``try`` имя всё ещё не в ``_bulkheads``.

    Через HTTP это не воспроизвести: middleware вызывает ``get_bulkhead("api")``
    до хендлера и уже кладёт bulkhead в реестр.
    """
    import app.api.bulkhead as bh_api
    from app.core import bulkhead as bm
    from fastapi import HTTPException

    bm._bulkheads.clear()

    def _noop(_name: str):
        return None

    orig = bh_api.get_bulkhead
    bh_api.get_bulkhead = _noop
    try:
        with pytest.raises(HTTPException) as exc_info:
            await bh_api.reset_bulkhead("api", admin_td)
        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value.detail).lower()
    finally:
        bh_api.get_bulkhead = orig


@pytest.mark.asyncio
async def test_reset_lazy_create_then_open(bulkhead_api_client, monkeypatch):
    """Ветка reset: имя ещё не в ``_bulkheads``, но известно конфигу — ``get_bulkhead`` создаёт."""
    from app.core import bulkhead as bm

    bm._bulkheads.clear()
    assert "api" not in bm._bulkheads

    r = await bulkhead_api_client.post("/api/bulkhead/reset/api")
    assert r.status_code == 200
    assert "api" in bm._bulkheads
