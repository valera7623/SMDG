from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response

from app.api.admin_file_audit import list_file_access_events
from app.core.auth_utils import TokenData
from app.models.file_access_event import FileAccessEvent
from app.models.tenant import Tenant
from app.services.file_audit_service import record_file_access_event


def _request_for_tenant(tenant_id: int):
    request = MagicMock()
    request.headers = {"user-agent": "pytest-agent", "x-forwarded-for": "203.0.113.7, 10.0.0.1"}
    request.client = MagicMock(host="127.0.0.1")
    request.scope = {}
    request.state = MagicMock()
    request.state.tenant = MagicMock(id=tenant_id)
    return request


@pytest.mark.asyncio
async def test_record_file_access_event_persists_client_context(db_session):
    tenant = Tenant(id=61, name="Audit Tenant", subdomain="audit-tenant", settings={})
    db_session.add(tenant)
    await db_session.commit()

    event = await record_file_access_event(
        db_session,
        request=_request_for_tenant(tenant.id),
        tenant_id=tenant.id,
        action="upload",
        channel="authenticated",
        source="client:203.0.113.7/browser",
        destination="storage:report.age",
        actor_user_id=None,
        actor_username="alice",
        actor_role="doctor",
        metadata={"mime_type": "application/pdf"},
        commit=True,
    )

    assert event is not None
    saved = await db_session.get(FileAccessEvent, event.id)
    assert saved is not None
    assert saved.client_ip == "203.0.113.7"
    assert saved.user_agent == "pytest-agent"
    assert saved.extra_metadata["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_admin_file_audit_list_is_scoped_to_request_tenant(db_session):
    tenant_a = Tenant(id=62, name="Audit A", subdomain="audit-a", settings={})
    tenant_b = Tenant(id=63, name="Audit B", subdomain="audit-b", settings={})
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()
    db_session.add_all([
        FileAccessEvent(
            tenant_id=tenant_a.id,
            action="upload",
            channel="authenticated",
            source="client:203.0.113.7/browser",
            destination="storage:a.age",
            original_name="a.pdf",
            actor_username="alice",
        ),
        FileAccessEvent(
            tenant_id=tenant_b.id,
            action="download_token",
            channel="public_link",
            source="storage:b.age",
            destination="client:203.0.113.8/browser",
            original_name="b.pdf",
            actor_username="public_link",
        ),
    ])
    await db_session.commit()

    response = Response()
    result = await list_file_access_events(
        request=_request_for_tenant(tenant_a.id),
        response=response,
        current_admin=TokenData(sub="admin", role="admin", tenant_id=tenant_a.id),
        db=db_session,
    )

    assert result.total == 1
    assert response.headers["X-Total-Count"] == "1"
    assert result.items[0].tenant_id == tenant_a.id
    assert result.items[0].original_name == "a.pdf"


@pytest.mark.asyncio
async def test_admin_file_audit_rejects_cross_tenant_admin(db_session):
    response = Response()

    with pytest.raises(HTTPException) as exc:
        await list_file_access_events(
            request=_request_for_tenant(63),
            response=response,
            current_admin=TokenData(sub="admin", role="admin", tenant_id=62),
            db=db_session,
        )

    assert exc.value.status_code == 403
