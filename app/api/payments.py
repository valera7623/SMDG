"""Stripe payments API."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import stripe_client
from app.billing.config import billing_enabled, stripe_checkout_enabled
from app.billing.deps import require_billing_user
from app.billing.payment_records import record_stripe_payment
from app.billing.schemas import (
    AdminRefundResponse,
    AdminRevenueResponse,
    AdminSubscriptionsResponse,
    BillingConfigResponse,
    CancelSubscriptionResponse,
    CreateCheckoutRequest,
    CreateCheckoutResponse,
    PriceItem,
    PricesResponse,
    SubscriptionResponse,
)
from app.billing.stripe_client import StripeClientError
from app.billing.usage import (
    FREEMIUM_UPLOADS_LIMIT,
    cancel_stripe_subscription,
    get_stripe_customer_id,
    get_subscription_api_response,
    plan_type_from_price_id,
)
from app.core.auth import get_current_admin, get_current_user
from app.core.auth_utils import TokenData
from app.core.dependencies import get_db_for_write
from app.core.tenant import require_tenant
from app.models.payment import Payment
from app.models.subscription import Subscription

router = APIRouter(prefix="/payments", tags=["Payments"])
admin_router = APIRouter(prefix="/admin/payments", tags=["Admin Payments"])


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _default_success_url() -> str:
    return _env_str("STRIPE_SUCCESS_URL", "https://localhost/payment/success?session_id={CHECKOUT_SESSION_ID}")


def _default_cancel_url() -> str:
    return _env_str("STRIPE_CANCEL_URL", "https://localhost/payment/cancel")


def _price_catalog() -> list[tuple[str, str, str]]:
    return [
        (_env_str("STRIPE_PRICE_ID_MONTHLY"), "Monthly", "premium_monthly"),
        (_env_str("STRIPE_PRICE_ID_YEARLY"), "Yearly", "premium_yearly"),
        (_env_str("STRIPE_PRICE_ID_PAYG"), "Pay as you go", "enterprise"),
    ]


@router.get("/config", response_model=BillingConfigResponse)
async def billing_config() -> BillingConfigResponse:
    from app.billing.config import yookassa_checkout_enabled

    return BillingConfigResponse(
        billing_enabled=billing_enabled(),
        stripe_enabled=stripe_checkout_enabled(),
        yookassa_enabled=yookassa_checkout_enabled(),
    )


@router.get("/prices", response_model=PricesResponse)
async def list_prices() -> PricesResponse:
    if not stripe_checkout_enabled():
        return PricesResponse(prices=[])
    items: list[PriceItem] = []
    for price_id, name, plan_type in _price_catalog():
        if not price_id:
            continue
        amount: int | None = None
        currency = "usd"
        interval: str | None = None
        try:
            price = stripe_client.retrieve_price(price_id)
            amount = int(price.get("unit_amount") or 0)
            currency = str(price.get("currency") or "usd")
            recurring = price.get("recurring") or {}
            interval = recurring.get("interval") if isinstance(recurring, dict) else None
        except StripeClientError:
            pass
        items.append(
            PriceItem(
                id=price_id,
                name=name,
                amount=amount,
                currency=currency,
                plan_type=plan_type,
                interval=interval,
            )
        )
    return PricesResponse(prices=items)


@router.post("/create-checkout", response_model=CreateCheckoutResponse)
async def create_checkout(
    request: Request,
    body: CreateCheckoutRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_for_write),
) -> CreateCheckoutResponse:
    if not stripe_checkout_enabled():
        raise HTTPException(status_code=403, detail="Оплата Stripe временно отключена")
    tenant = require_tenant(request)
    user = await require_billing_user(db, current_user, tenant.id)

    success_url = body.success_url or _default_success_url()
    cancel_url = body.cancel_url or _default_cancel_url()
    plan_type = plan_type_from_price_id(body.price_id)
    mode = "subscription"
    payg_id = _env_str("STRIPE_PRICE_ID_PAYG")
    if body.price_id == payg_id and payg_id:
        mode = "payment"

    metadata = {
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "plan_type": plan_type,
        "price_id": body.price_id,
    }

    customer_id = await get_stripe_customer_id(db, user.id)
    try:
        if not customer_id:
            customer_id = stripe_client.create_customer(
                email=user.email,
                metadata={"user_id": str(user.id)},
            )
            stmt = insert(Subscription).values(
                user_id=user.id,
                tenant_id=user.tenant_id,
                plan_type="freemium",
                status="active",
                monthly_uploads_limit=FREEMIUM_UPLOADS_LIMIT,
                stripe_customer_id=customer_id,
                payment_provider="stripe",
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={"stripe_customer_id": customer_id},
            )
            await db.execute(stmt)
            await db.commit()

        session = stripe_client.create_checkout_session(
            customer_id=customer_id,
            price_id=body.price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            mode=mode,
            metadata=metadata,
        )
    except StripeClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CreateCheckoutResponse(**session)


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_for_write),
) -> SubscriptionResponse:
    user = await require_billing_user(db, current_user)
    data = await get_subscription_api_response(db, user.id)
    return SubscriptionResponse(**data)


@router.post("/cancel-subscription", response_model=CancelSubscriptionResponse)
async def cancel_subscription_route(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_for_write),
) -> CancelSubscriptionResponse:
    user = await require_billing_user(db, current_user)
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    if not row or not row.stripe_subscription_id:
        raise HTTPException(status_code=404, detail="No active Stripe subscription")

    sub_id = str(row.stripe_subscription_id)
    try:
        stripe_client.cancel_subscription(sub_id, at_period_end=True)
        sub_data = stripe_client.get_subscription(sub_id)
    except StripeClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    period_end = sub_data.get("current_period_end")
    effective = None
    if period_end:
        effective = datetime.fromtimestamp(int(period_end), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        end = row.period_end or row.expires_at
        effective = end.isoformat() if end else None

    row.status = "canceled"
    row.expires_at = datetime.fromisoformat(effective.replace("Z", "+00:00")) if effective else row.expires_at
    await db.commit()

    return CancelSubscriptionResponse(status="canceled", effective_date=effective)


@admin_router.get("/subscriptions", response_model=AdminSubscriptionsResponse)
async def admin_list_subscriptions(
    status_filter: str | None = Query(default=None),
    _: TokenData = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_for_write),
) -> AdminSubscriptionsResponse:
    stmt = select(Subscription).order_by(Subscription.created_at.desc()).limit(500)
    count_stmt = select(func.count()).select_from(Subscription)
    if status_filter:
        stmt = stmt.where(Subscription.status == status_filter)
        count_stmt = count_stmt.where(Subscription.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    subs = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "tenant_id": r.tenant_id,
            "plan_type": r.plan_type,
            "status": r.status,
            "monthly_uploads_limit": r.monthly_uploads_limit,
            "used_uploads": r.used_uploads,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "stripe_customer_id": r.stripe_customer_id,
            "stripe_subscription_id": r.stripe_subscription_id,
            "payment_provider": r.payment_provider,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
    return AdminSubscriptionsResponse(subscriptions=subs, total=int(total), status_filter=status_filter)


@admin_router.get("/revenue", response_model=AdminRevenueResponse)
async def admin_revenue(
    period: str = Query(default="month", pattern="^(month|year)$"),
    _: TokenData = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_for_write),
) -> AdminRevenueResponse:
    from datetime import timedelta

    since = datetime.now(timezone.utc) - (timedelta(days=365) if period == "year" else timedelta(days=30))
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0),
                func.count(),
                func.max(Payment.currency),
            ).where(
                Payment.status == "succeeded",
                Payment.provider == "stripe",
                Payment.created_at >= since,
            )
        )
    ).one()
    mrr_row = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == "succeeded",
                Payment.provider == "stripe",
                Payment.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
    ).scalar_one()

    return AdminRevenueResponse(
        period=period,
        currency=str(row[2] or "usd"),
        total_amount_cents=int(row[0] or 0),
        payment_count=int(row[1] or 0),
        mrr_cents=int(mrr_row or 0),
    )


@admin_router.post("/refund/{payment_id}", response_model=AdminRefundResponse)
async def admin_refund(
    payment_id: str,
    _: TokenData = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_for_write),
) -> AdminRefundResponse:
    result = await db.execute(select(Payment).where(Payment.payment_id == payment_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if (row.status or "").lower() != "succeeded":
        raise HTTPException(status_code=400, detail="Refund allowed only for succeeded payments")
    if not row.stripe_payment_intent_id:
        raise HTTPException(status_code=400, detail="Payment has no Stripe payment intent")

    try:
        refund = stripe_client.create_refund(
            payment_intent_id=str(row.stripe_payment_intent_id),
            amount_cents=int(row.amount),
        )
    except StripeClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    row.status = "refunded"
    await db.commit()
    return AdminRefundResponse(payment_id=payment_id, refund=refund)
