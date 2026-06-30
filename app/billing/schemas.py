"""Pydantic models for payments API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateCheckoutRequest(BaseModel):
    price_id: str
    success_url: str | None = None
    cancel_url: str | None = None


class CreateCheckoutResponse(BaseModel):
    session_id: str
    url: str


class PriceItem(BaseModel):
    id: str
    name: str
    amount: int | None = None
    currency: str = "usd"
    plan_type: str | None = None
    interval: str | None = None


class PricesResponse(BaseModel):
    prices: list[PriceItem]


class BillingConfigResponse(BaseModel):
    billing_enabled: bool
    stripe_enabled: bool
    yookassa_enabled: bool


class SubscriptionResponse(BaseModel):
    plan_type: str
    status: str
    uploads_limit: int
    uploads_used: int
    uploads_remaining: int
    current_period_end: str | None = None
    is_active: bool
    payment_provider: str | None = None
    stripe_subscription_id: str | None = None


class CancelSubscriptionResponse(BaseModel):
    status: str
    effective_date: str | None = None


class AdminSubscriptionsResponse(BaseModel):
    subscriptions: list[dict[str, Any]]
    total: int
    status_filter: str | None = None


class AdminRevenueResponse(BaseModel):
    period: str
    currency: str
    total_amount_cents: int
    payment_count: int
    mrr_cents: int


class AdminRefundResponse(BaseModel):
    payment_id: str
    refund: dict[str, Any]
