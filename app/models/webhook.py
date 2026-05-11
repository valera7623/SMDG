# app/models/webhook.py
"""
Модели webhook-подписок и истории доставки.
"""
from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from datetime import datetime
from typing import Optional, List
from enum import Enum

from app.models.base import Base


class WebhookEvent(str, Enum):
    """Типы событий для webhook-уведомлений."""
    FILE_UPLOADED = "file.uploaded"
    FILE_DOWNLOADED = "file.downloaded"
    FILE_DELETED = "file.deleted"
    LINK_CREATED = "link.created"
    LINK_EXPIRED = "link.expired"
    CLEANUP_COMPLETED = "cleanup.completed"


class DeliveryStatus(str, Enum):
    """Статус доставки webhook."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class WebhookSubscription(Base):
    """Подписка на webhook-уведомления."""
    __tablename__ = 'webhook_subscriptions'
    __table_args__ = {'extend_existing': True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('tenants.id'), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)

    url: Mapped[str] = mapped_column(String(512), nullable=False)
    events: Mapped[List[str]] = mapped_column(
        PG_ARRAY(String(50)),
        nullable=False,
        default=list,
    )
    secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    headers: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.current_timestamp()
    )
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    deliveries = relationship(
        'WebhookDelivery',
        back_populates='subscription',
        cascade='all, delete-orphan',
        lazy='select'
    )
    tenant = relationship('Tenant', lazy='select')
    user = relationship('User', lazy='select')

    def __repr__(self):
        return f'<WebhookSubscription id={self.id} url={self.url} active={self.is_active}>'


class WebhookDelivery(Base):
    """История доставки webhook-уведомлений."""
    __tablename__ = 'webhook_deliveries'
    __table_args__ = {'extend_existing': True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('webhook_subscriptions.id'), nullable=False
    )
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DeliveryStatus.PENDING.value)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    subscription = relationship('WebhookSubscription', back_populates='deliveries', lazy='select')

    def __repr__(self):
        return f'<WebhookDelivery id={self.id} event={self.event} status={self.status} attempts={self.attempts}>'
