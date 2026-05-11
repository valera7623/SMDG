from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FileAccessEvent(Base):
    """Structured audit trail for file upload/download operations."""

    __tablename__ = "file_access_events"
    __table_args__ = (
        Index("ix_file_access_events_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_file_access_events_tenant_action_created_at", "tenant_id", "action", "created_at"),
        Index("ix_file_access_events_tenant_actor_created_at", "tenant_id", "actor_user_id", "created_at"),
        Index("ix_file_access_events_tenant_file_created_at", "tenant_id", "file_id", "created_at"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    destination: Mapped[str] = mapped_column(String(512), nullable=False)

    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    actor_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        index=True,
    )
