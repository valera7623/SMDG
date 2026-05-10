"""
Интеграционные проверки tenant resolution при разных DEPLOYMENT_TYPE / MULTI_TENANCY.

Требуют доступную PostgreSQL (.env.test). Если порта нет — пропуск (локальный CI без БД).

Дублирующая логика покрыта unit-тестами в ``tests/test_core/test_tenant_single_mode.py``.
"""
from __future__ import annotations

import os
import socket

import pytest


def _pg_listener() -> bool:
    if os.getenv("SMDG_SKIP_DB_INTEGRATION") == "1":
        return False
    host = os.getenv("SMDG_PG_TEST_HOST", "127.0.0.1")
    port = int(os.getenv("SMDG_PG_TEST_PORT", "5432"))
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_listener(),
    reason="PostgreSQL недоступен на %s:%s (или SMDG_SKIP_DB_INTEGRATION=1)"
    % (os.getenv("SMDG_PG_TEST_HOST", "127.0.0.1"), os.getenv("SMDG_PG_TEST_PORT", "5432")),
)

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import select
from unittest.mock import patch

from app.core.tenant import resolve_tenant_from_request
from app.models.tenant import Tenant

import app.core.feature_flags as ff


def _scope(
    host: str = "localhost:8000",
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    headers = [(b"host", host.encode())]
    if extra_headers:
        headers.extend(extra_headers)
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
        "headers": headers,
    }


def _is_enabled_single_tenant(feature):
    """Все фичи как в матрице, но MULTI_TENANCY принудительно выключен."""
    if feature == ff.Feature.MULTI_TENANCY:
        return False
    return _ORIG_IS_ENABLED(feature)


def _is_enabled_multi_tenant(feature):
    """Принудительно включён MULTI_TENANCY (имитация SaaS без смены всего env)."""
    if feature == ff.Feature.MULTI_TENANCY:
        return True
    return _ORIG_IS_ENABLED(feature)


_ORIG_IS_ENABLED = ff.is_enabled


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_tenant_super_admin_always_default_not_other_subdomain(db_session):
    """При отключённом multi-tenancy super_admin не переключается на другой tenant по Host."""
    db_session.add(Tenant(id=2, name="Other Org", subdomain="other", settings={}))
    await db_session.commit()

    other = await db_session.get(Tenant, 2)
    default = await db_session.get(Tenant, 1)
    assert other is not None and default is not None

    req = Request(_scope(host="other.localhost:8000"))

    with patch.object(ff, "is_enabled", side_effect=_is_enabled_single_tenant):
        resolved = await resolve_tenant_from_request(
            db_session,
            req,
            jwt_tenant_id=other.id,
            jwt_role="super_admin",
        )

    assert resolved is not None
    assert resolved.id == default.id
    assert resolved.subdomain == "default"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_tenant_super_admin_ignores_x_tenant_id(db_session):
    """X-Tenant-ID на другую организацию не меняет контекст для super_admin."""
    db_session.add(Tenant(id=3, name="Alt", subdomain="alt", settings={}))
    await db_session.commit()

    result = await db_session.execute(select(Tenant).where(Tenant.subdomain == "alt"))
    alt = result.scalar_one()
    default = await db_session.get(Tenant, 1)

    req = Request(
        _scope(
            extra_headers=[(b"x-tenant-id", str(alt.id).encode())],
        )
    )

    with patch.object(ff, "is_enabled", side_effect=_is_enabled_single_tenant):
        resolved = await resolve_tenant_from_request(
            db_session,
            req,
            jwt_tenant_id=alt.id,
            jwt_role="super_admin",
        )

    assert resolved.id == default.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_tenant_user_forbidden_wrong_jwt_tenant(db_session):
    """Обычный пользователь с JWT от другого tenant получает 403."""
    db_session.add(Tenant(id=4, name="Alt", subdomain="alt2", settings={}))
    await db_session.commit()

    result = await db_session.execute(select(Tenant).where(Tenant.subdomain == "alt2"))
    alt = result.scalar_one()

    req = Request(_scope())

    with patch.object(ff, "is_enabled", side_effect=_is_enabled_single_tenant):
        with pytest.raises(HTTPException) as ei:
            await resolve_tenant_from_request(
                db_session,
                req,
                jwt_tenant_id=alt.id,
                jwt_role="user",
            )
        assert ei.value.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_tenant_super_admin_can_use_host_hint(db_session):
    """При включённом MULTI_TENANCY super_admin по-прежнему может выбрать tenant по Host."""
    db_session.add(Tenant(id=5, name="Beta", subdomain="beta", settings={}))
    await db_session.commit()

    result = await db_session.execute(select(Tenant).where(Tenant.subdomain == "beta"))
    beta = result.scalar_one()

    req = Request(_scope(host="beta.example.com:8000"))

    with patch.object(ff, "is_enabled", side_effect=_is_enabled_multi_tenant):
        resolved = await resolve_tenant_from_request(
            db_session,
            req,
            jwt_tenant_id=None,
            jwt_role="super_admin",
        )

    assert resolved is not None
    assert resolved.id == beta.id
