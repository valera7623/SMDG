from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.auth_utils import TokenData
from app.main import app


def _disable_limiter():
    if hasattr(app.state, "limiter"):
        app.state.limiter.enabled = False


def _override_user():
    return TokenData(sub="doctor", role="doctor", tenant_id=1)


def _override_db(dialect_name: str = "postgresql"):
    async def _get_db():
        session = AsyncMock()
        bind = MagicMock()
        bind.dialect.name = dialect_name
        session.bind = bind
        session.execute = AsyncMock()
        yield session

    return _get_db


def test_slow_query_returns_200_when_query_finishes():
    from app.api.test import slow_query
    from app.core.database import get_db

    _disable_limiter()
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db("postgresql")
    try:
        with patch("app.api.test.execute_db_with_timeout", new=AsyncMock(return_value=object())):
            with TestClient(app) as client:
                response = client.post("/api/test/slow-query?sleep_seconds=1")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_slow_query_returns_504_on_timeout():
    from app.core.database import get_db

    _disable_limiter()
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db("postgresql")
    try:
        with patch(
            "app.api.test.execute_db_with_timeout",
            new=AsyncMock(side_effect=HTTPException(status_code=504, detail="Database query timeout")),
        ):
            with TestClient(app) as client:
                response = client.post("/api/test/slow-query?sleep_seconds=20")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 504
    assert "timeout" in response.json()["detail"].lower()


def test_slow_query_requires_postgresql_backend():
    from app.core.database import get_db

    _disable_limiter()
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db("sqlite")
    try:
        with TestClient(app) as client:
            response = client.post("/api/test/slow-query?sleep_seconds=2")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "postgresql" in response.json()["detail"].lower()

