from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArchiveRecord(Base):
    __tablename__ = "archive_records"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    archive_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4())
    )

    source_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    source_table: Mapped[str] = mapped_column(String(64), nullable=False)

    archive_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    archive_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    archive_checksum: Mapped[str] = mapped_column(String(128), nullable=False)

    storage_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="glacier")
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    original_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="archived", index=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ArchiveRestoreRequest(Base):
    __tablename__ = "archive_restore_requests"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    archive_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("archive_records.archive_id"), index=True, nullable=False
    )
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    request_reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    restored_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
