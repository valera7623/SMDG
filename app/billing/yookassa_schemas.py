"""Pydantic models for YooKassa API."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, HttpUrl


class YooKassaPlanType(str, Enum):
    premium_monthly = "premium_monthly"
    premium_yearly = "premium_yearly"
    enterprise = "enterprise"


class YooKassaCreatePaymentRequest(BaseModel):
    plan_type: YooKassaPlanType


class YooKassaCreatePaymentResponse(BaseModel):
    payment_id: str
    confirmation_url: HttpUrl


class YooKassaPaymentStatusResponse(BaseModel):
    payment_id: str
    status: str


class YooKassaSubscriptionResponse(BaseModel):
    plan_type: str
    status: str
    is_active: bool
    monthly_uploads_limit: int
    used_uploads: int
    remaining_uploads: int
    expires_at: str | None = None
    period_start: str | None = None
    period_end: str | None = None
