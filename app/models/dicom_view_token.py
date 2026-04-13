# app/models/dicom_view_token.py
from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from typing import Optional
from app.models.base import Base
import uuid


class DicomViewToken(Base):
    """Временный токен для просмотра DICOM-файлов через OHIF Viewer.

    Отличие от FileLink:
    - Multi-use (не одноразовый): multi-frame DICOM требует нескольких запросов
    - Короткий TTL (по умолчанию 15 минут)
    - Привязан к конкретному файлу
    """
    __tablename__ = "dicom_view_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True,
        default=lambda: str(uuid.uuid4())
    )
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id"), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="NOW()"
    )

    # Связи
    file = relationship("File")
    user = relationship("User")

    def __repr__(self):
        return f"<DicomViewToken token={self.token[:8]}... file_id={self.file_id}>"
