from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.file_access_event import FileAccessEvent

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    headers = getattr(request, "headers", None) or {}
    forwarded_for = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if isinstance(forwarded_for, str) and forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    headers = getattr(request, "headers", None) or {}
    user_agent = headers.get("user-agent", "unknown") if hasattr(headers, "get") else "unknown"
    return user_agent if isinstance(user_agent, str) else "unknown"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def record_file_access_event(
    db: AsyncSession,
    *,
    request: Request,
    tenant_id: int,
    action: str,
    channel: str,
    source: str,
    destination: str,
    file_record: File | None = None,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    actor_role: str | None = None,
    success: bool = True,
    failure_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> FileAccessEvent | None:
    """Persist a structured file audit event without exposing secrets."""

    event = FileAccessEvent(
        tenant_id=tenant_id,
        file_id=getattr(file_record, "id", None),
        actor_user_id=actor_user_id,
        action=action,
        channel=channel,
        source=source,
        destination=destination,
        original_name=getattr(file_record, "original_name", None),
        encrypted_name=getattr(file_record, "encrypted_name", None),
        size_bytes=getattr(file_record, "original_size", None) or getattr(file_record, "encrypted_size", None),
        actor_username=actor_username,
        actor_role=actor_role,
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request)[:512],
        success=success,
        failure_reason=failure_reason,
        extra_metadata=metadata or {},
    )
    db.add(event)
    if commit:
        await db.commit()
    return event


async def safe_record_file_access_event(db: AsyncSession, **kwargs: Any) -> FileAccessEvent | None:
    """Best-effort audit write: never fail the file operation itself."""

    try:
        return await record_file_access_event(db, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record file access event: %s", exc, exc_info=True)
        if kwargs.get("commit"):
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to roll back after file audit error", exc_info=True)
        return None
