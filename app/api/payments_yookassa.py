"""YooKassa payments API."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import billing_enabled, yookassa_checkout_enabled
from app.billing.deps import require_billing_user
from app.billing.payment_records import upsert_yookassa_payment
from app.billing.usage import (
    ENTERPRISE_UPLOADS_LIMIT,
    PREMIUM_UPLOADS_LIMIT,
    activate_subscription,
    cancel_subscription,
    get_user_subscription,
)
from app.billing.yookassa_client import YooKassaClient, YooKassaClientError
from app.billing.yookassa_schemas import (
    YooKassaCreatePaymentRequest,
    YooKassaCreatePaymentResponse,
    YooKassaPaymentStatusResponse,
    YooKassaPlanType,
    YooKassaSubscriptionResponse,
)
from app.core.auth import get_current_admin, get_current_user
from app.core.auth_utils import TokenData
from app.core.dependencies import get_db_for_write
from app.core.tenant import require_tenant
from app.models.payment import Payment

router = APIRouter(prefix="/payments/yookassa", tags=["Payments (YooKassa)"])
admin_router = APIRouter(prefix="/admin/payments/yookassa", tags=["Admin Payments (YooKassa)"])


def _env_str(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


PRICE_PREMIUM_MONTHLY = _env_int("PRICE_PREMIUM_MONTHLY", 1990)
PRICE_PREMIUM_YEARLY = _env_int("PRICE_PREMIUM_YEARLY", 19900)
PRICE_ENTERPRISE = _env_int("PRICE_ENTERPRISE", 9990)


def _amount_value_to_rub(amount_value: str | None) -> float:
    if not amount_value:
        return 0.0
    return float(Decimal(str(amount_value)).quantize(Decimal("0.01")))


def _plan_amount_and_limit(plan_type: YooKassaPlanType) -> tuple[int, int]:
    if plan_type == YooKassaPlanType.premium_monthly:
        return PRICE_PREMIUM_MONTHLY, PREMIUM_UPLOADS_LIMIT
    if plan_type == YooKassaPlanType.premium_yearly:
        return PRICE_PREMIUM_YEARLY, PREMIUM_UPLOADS_LIMIT
    if plan_type == YooKassaPlanType.enterprise:
        return PRICE_ENTERPRISE, ENTERPRISE_UPLOADS_LIMIT
    raise ValueError(f"Unknown plan_type: {plan_type}")


class AdminRefundResponse(BaseModel):
    payment_id: str
    refund: dict[str, Any]


class AdminListPaymentsResponse(BaseModel):
    payments: list[dict[str, Any]]
    total: int
    status_filter: str | None = None


def _client() -> YooKassaClient:
    return YooKassaClient(
        shop_id=_env_str("YOOKASSA_SHOP_ID"),
        secret_key=_env_str("YOOKASSA_SECRET_KEY"),
        api_url=os.getenv("YOOKASSA_API_URL"),
    )


@router.post("/create", response_model=YooKassaCreatePaymentResponse, status_code=201)
async def yookassa_create_payment(
    request: Request,
    body: YooKassaCreatePaymentRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_for_write),
) -> YooKassaCreatePaymentResponse:
    if not yookassa_checkout_enabled():
        raise HTTPException(status_code=403, detail="Оплата временно отключена")
    tenant = require_tenant(request)
    user = await require_billing_user(db, current_user, tenant.id)

    return_url_success = _env_str("YOOKASSA_RETURN_URL_SUCCESS")
    amount_cents, _ = _plan_amount_and_limit(body.plan_type)
    plan_type_value = body.plan_type.value
    description = f"SMDG: {plan_type_value} subscription"
    metadata = {"user_id": str(user.id), "tenant_id": str(user.tenant_id), "plan_type": plan_type_value}

    try:
        created = await _client().create_payment(
            amount=amount_cents,
            currency="RUB",
            description=description,
            return_url=return_url_success,
            metadata=metadata,
            capture=True,
        )
    except YooKassaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await upsert_yookassa_payment(
        db,
        payment_id=created.payment_id,
        user_id=user.id,
        tenant_id=user.tenant_id,
        amount_cents=amount_cents,
        currency="RUB",
        status="pending",
        description=description[:256],
        payment_method=None,
        metadata=metadata,
    )
    await db.commit()

    return YooKassaCreatePaymentResponse(
        payment_id=created.payment_id,
        confirmation_url=created.confirmation_url,
    )


@router.get("/subscription", response_model=YooKassaSubscriptionResponse)
async def yookassa_get_subscription(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_for_write),
) -> YooKassaSubscriptionResponse:
    user = await require_billing_user(db, current_user)
    data = await get_user_subscription(db, user.id)
    expires_at = data.get("expires_at")
    period_start = data.get("period_start")
    period_end = data.get("period_end")
    return YooKassaSubscriptionResponse(
        plan_type=str(data["plan_type"]),
        status=str(data["status"]),
        is_active=bool(data["is_active"]),
        monthly_uploads_limit=int(data["monthly_uploads_limit"]),
        used_uploads=int(data["used_uploads"]),
        remaining_uploads=int(data["remaining_uploads"]),
        expires_at=expires_at.isoformat() if hasattr(expires_at, "isoformat") else (
            str(expires_at) if expires_at else None
        ),
        period_start=period_start.isoformat() if hasattr(period_start, "isoformat") else (
            str(period_start) if period_start else None
        ),
        period_end=period_end.isoformat() if hasattr(period_end, "isoformat") else (
            str(period_end) if period_end else None
        ),
    )


@router.get("/status/{payment_id}", response_model=YooKassaPaymentStatusResponse)
async def yookassa_check_status(
    payment_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_for_write),
) -> YooKassaPaymentStatusResponse:
    user = await require_billing_user(db, current_user)
    result = await db.execute(
        select(Payment).where(Payment.payment_id == payment_id, Payment.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")

    local_meta = row.metadata_json or {}

    try:
        data = await _client().get_payment(payment_id)
    except YooKassaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    yookassa_status = str(data.get("status") or "").lower()
    status_map = {
        "pending": "pending",
        "waiting_for_capture": "waiting_for_capture",
        "succeeded": "succeeded",
        "canceled": "canceled",
        "cancelled": "canceled",
    }
    local_status = status_map.get(yookassa_status, yookassa_status or "pending")

    remote_meta = data.get("metadata") or {}
    meta = remote_meta if remote_meta else local_meta
    plan_type = (meta.get("plan_type") or "").strip()
    payment_method_type = (data.get("payment_method") or {}).get("type")
    amount_value = data.get("amount", {}).get("value")
    currency = str(data.get("amount", {}).get("currency") or row.currency or "RUB")
    description = data.get("description") or row.description
    captured_at = data.get("captured_at")

    from datetime import datetime, timezone

    captured_dt = datetime.now(timezone.utc) if local_status == "succeeded" else None
    await upsert_yookassa_payment(
        db,
        payment_id=payment_id,
        user_id=user.id,
        tenant_id=user.tenant_id,
        amount_cents=int((Decimal(str(amount_value)) * 100).quantize(Decimal("1"))) if amount_value else row.amount,
        currency=currency,
        status=local_status,
        description=description,
        payment_method=str(payment_method_type) if payment_method_type else None,
        metadata=meta,
        captured_at=captured_dt,
    )

    if local_status == "succeeded" and plan_type in ("premium_monthly", "premium_yearly", "enterprise"):
        await activate_subscription(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
            plan_type=plan_type,  # type: ignore[arg-type]
            yookassa_payment_id=payment_id,
            yookassa_payment_method=str(payment_method_type) if payment_method_type else None,
        )
    elif local_status == "canceled":
        await cancel_subscription(db, user_id=user.id)

    await db.commit()
    return YooKassaPaymentStatusResponse(payment_id=payment_id, status=local_status)


@admin_router.get("", response_model=AdminListPaymentsResponse)
async def admin_list_payments(
    status_filter: str | None = Query(default=None),
    _: TokenData = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_for_write),
) -> AdminListPaymentsResponse:
    stmt = select(Payment).where(Payment.provider == "yookassa").order_by(Payment.created_at.desc()).limit(500)
    count_stmt = select(func.count()).select_from(Payment).where(Payment.provider == "yookassa")
    if status_filter:
        stmt = stmt.where(Payment.status == status_filter)
        count_stmt = count_stmt.where(Payment.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    payments = [
        {
            "payment_id": r.payment_id,
            "user_id": r.user_id,
            "amount": r.amount,
            "currency": r.currency,
            "status": r.status,
            "description": r.description,
            "payment_method": r.payment_method,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "captured_at": r.captured_at.isoformat() if r.captured_at else None,
        }
        for r in rows
    ]
    return AdminListPaymentsResponse(payments=payments, total=int(total), status_filter=status_filter)


@admin_router.post("/refund/{payment_id}", response_model=AdminRefundResponse)
async def admin_refund_payment(
    payment_id: str,
    _: TokenData = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_for_write),
) -> AdminRefundResponse:
    result = await db.execute(select(Payment).where(Payment.payment_id == payment_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if (row.status or "").lower() != "succeeded":
        raise HTTPException(status_code=400, detail="Refund is allowed only for succeeded payments")

    try:
        refund = await _client().refund_payment(payment_id, amount=int(row.amount))
    except YooKassaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AdminRefundResponse(payment_id=payment_id, refund=refund)
