from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.database import get_db
from app.core.tenant import assert_tenant_access, require_tenant
from app.models.file_access_event import FileAccessEvent

router = APIRouter(prefix="/admin/file-audit", tags=["Admin File Audit"])


class FileAccessEventResponse(BaseModel):
    id: int
    created_at: datetime
    action: str
    channel: str
    success: bool
    failure_reason: str | None = None
    tenant_id: int
    file_id: int | None = None
    original_name: str | None = None
    encrypted_name: str | None = None
    size_bytes: int | None = None
    actor_user_id: int | None = None
    actor_username: str | None = None
    actor_role: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    source: str
    destination: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileAccessEventListResponse(BaseModel):
    total: int
    items: list[FileAccessEventResponse]


def _event_to_response(event: FileAccessEvent) -> FileAccessEventResponse:
    return FileAccessEventResponse(
        id=event.id,
        created_at=event.created_at,
        action=event.action,
        channel=event.channel,
        success=event.success,
        failure_reason=event.failure_reason,
        tenant_id=event.tenant_id,
        file_id=event.file_id,
        original_name=event.original_name,
        encrypted_name=event.encrypted_name,
        size_bytes=event.size_bytes,
        actor_user_id=event.actor_user_id,
        actor_username=event.actor_username,
        actor_role=event.actor_role,
        client_ip=event.client_ip,
        user_agent=event.user_agent,
        source=event.source,
        destination=event.destination,
        metadata=event.extra_metadata or {},
    )


@router.get("/", response_model=FileAccessEventListResponse)
async def list_file_access_events(
    request: Request,
    response: Response,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action: str | None = Query(None, max_length=32),
    actor_user_id: int | None = Query(None, ge=1),
    search: str | None = Query(None, max_length=255),
    success: bool | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
) -> FileAccessEventListResponse:
    tenant = require_tenant(request)
    assert_tenant_access(current_admin.tenant_id, tenant.id, current_admin.role)

    filters = [FileAccessEvent.tenant_id == tenant.id]
    if action:
        filters.append(FileAccessEvent.action == action)
    if actor_user_id:
        filters.append(FileAccessEvent.actor_user_id == actor_user_id)
    if success is not None:
        filters.append(FileAccessEvent.success.is_(success))
    if start:
        filters.append(FileAccessEvent.created_at >= start)
    if end:
        filters.append(FileAccessEvent.created_at <= end)
    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(
                FileAccessEvent.actor_username.ilike(pattern),
                FileAccessEvent.original_name.ilike(pattern),
                FileAccessEvent.encrypted_name.ilike(pattern),
                FileAccessEvent.client_ip.ilike(pattern),
            )
        )

    total = (
        await db.execute(
            select(func.count(FileAccessEvent.id)).where(*filters)
        )
    ).scalar_one()
    result = await db.execute(
        select(FileAccessEvent)
        .where(*filters)
        .order_by(FileAccessEvent.created_at.desc(), FileAccessEvent.id.desc())
        .offset(skip)
        .limit(limit)
    )
    items = [_event_to_response(event) for event in result.scalars().all()]
    response.headers["X-Total-Count"] = str(total)
    return FileAccessEventListResponse(total=total, items=items)
