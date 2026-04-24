# app/models/file.py
from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.base import Base
from sqlalchemy.sql import func

class File(Base):
    __tablename__ = 'files'
    __table_args__ = {'extend_existing': True}
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey('tenants.id'), nullable=False, index=True, default=1)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_path: Mapped[str] = mapped_column(String(512), nullable=False)
    original_size: Mapped[int] = mapped_column(Integer, nullable=False)
    encrypted_size: Mapped[int] = mapped_column(Integer, nullable=False)
    original_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    patient_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    medical_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True, default=dict)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_archived: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    links = relationship('FileLink', back_populates='file', cascade='all, delete-orphan')
    view_tokens = relationship('DicomViewToken', back_populates='file', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<File id={self.id} original_name={self.original_name} patient_id={self.patient_id}>'
