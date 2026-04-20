"""
Unit-тесты режима single-tenant (MULTI_TENANCY выключен): без реальной PostgreSQL.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.tenant import resolve_tenant_from_request
from app.models.tenant import Tenant

import app.core.feature_flags as ff


def _request(host: str = "localhost:8000", **headers: str) -> Request:
    h = [(b"host", host.encode())]
    for k, v in headers.items():
        hk = k.replace("_", "-").encode()
        h.append((hk, str(v).encode()))
    return Request(
        {
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
            "headers": h,
        }
    )


def _db_mock(default: Tenant):
    """Мок session.execute: первый запрос — default tenant по subdomain."""
    db = AsyncMock()

    async def execute_side_effect(stmt):
        r = MagicMock()

        def scalar_one_or_none():
            return default

        r.scalar_one_or_none = scalar_one_or_none
        # sqlalchemy 2: sync methods on result
        return r

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


_ORIG = ff.is_enabled


def _single_no_multi(f):
    if f == ff.Feature.MULTI_TENANCY:
        return False
    return _ORIG(f)


@pytest.mark.asyncio
async def test_super_admin_returns_default_not_other_host():
    default = Tenant(id=1, name="Default", subdomain="default", settings={})
    other = Tenant(id=2, name="Other", subdomain="other", settings={})

    db = _db_mock(default)

    req = _request(host="other.localhost:8000")

    with patch.object(ff, "is_enabled", side_effect=_single_no_multi):
        out = await resolve_tenant_from_request(
            db,
            req,
            jwt_tenant_id=other.id,
            jwt_role="super_admin",
        )

    assert out.id == 1
    assert out.subdomain == "default"


@pytest.mark.asyncio
async def test_super_admin_ignores_x_tenant_id_header():
    default = Tenant(id=1, name="Default", subdomain="default", settings={})
    alt = Tenant(id=9, name="Alt", subdomain="alt", settings={})

    db = _db_mock(default)
    req = _request(**{"x_tenant_id": str(alt.id)})

    with patch.object(ff, "is_enabled", side_effect=_single_no_multi):
        out = await resolve_tenant_from_request(
            db,
            req,
            jwt_tenant_id=alt.id,
            jwt_role="super_admin",
        )

    assert out.id == default.id


@pytest.mark.asyncio
async def test_user_403_when_jwt_tenant_not_default():
    default = Tenant(id=1, name="Default", subdomain="default", settings={})
    alt = Tenant(id=9, name="Alt", subdomain="alt", settings={})

    db = _db_mock(default)
    req = _request()

    with patch.object(ff, "is_enabled", side_effect=_single_no_multi):
        with pytest.raises(HTTPException) as ei:
            await resolve_tenant_from_request(
                db,
                req,
                jwt_tenant_id=alt.id,
                jwt_role="doctor",
            )
        assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_multi_tenant_super_admin_prefers_host_hints():
    beta = Tenant(id=3, name="Beta", subdomain="beta", settings={})

    db = AsyncMock()

    async def exec_multi(stmt):
        r = MagicMock()

        def scalar_one_or_none():
            return beta

        r.scalar_one_or_none = scalar_one_or_none
        return r

    db.execute = AsyncMock(side_effect=exec_multi)

    req = _request(host="beta.example.com:8080")

    def _multi_on(f):
        if f == ff.Feature.MULTI_TENANCY:
            return True
        return _ORIG(f)

    with patch.object(ff, "is_enabled", side_effect=_multi_on):
        out = await resolve_tenant_from_request(
            db,
            req,
            jwt_tenant_id=None,
            jwt_role="super_admin",
        )

    assert out.id == beta.id
