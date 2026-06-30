"""Subscription usage tracking and activation (upload limits)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import billing_enabled
from app.models.subscription import Subscription

_TESTING_UNLIMITED = 999_999

PlanType = Literal["freemium", "premium_monthly", "premium_yearly", "enterprise"]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


FREEMIUM_UPLOADS_LIMIT = _env_int("FREEMIUM_UPLOADS_LIMIT", _env_int("FREEMIUM_REPORTS_LIMIT", 10))
PREMIUM_UPLOADS_LIMIT = _env_int("PREMIUM_UPLOADS_LIMIT", _env_int("PREMIUM_REPORTS_LIMIT", 500))
ENTERPRISE_UPLOADS_LIMIT = _env_int("ENTERPRISE_UPLOADS_LIMIT", _env_int("ENTERPRISE_REPORTS_LIMIT", 5000))


def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return month_start, next_month


def _plan_monthly_limit(plan_type: PlanType) -> int:
    if plan_type == "freemium":
        return FREEMIUM_UPLOADS_LIMIT
    if plan_type in ("premium_monthly", "premium_yearly"):
        return PREMIUM_UPLOADS_LIMIT
    if plan_type == "enterprise":
        return ENTERPRISE_UPLOADS_LIMIT
    raise ValueError(f"Unknown plan type: {plan_type}")


def _plan_expires_at(plan_type: PlanType, now: datetime) -> datetime | None:
    if plan_type == "premium_monthly":
        return now + timedelta(days=30)
    if plan_type == "premium_yearly":
        return now + timedelta(days=365)
    if plan_type == "enterprise":
        return now + timedelta(days=30)
    return None


def _normalize_plan_type(value: str) -> PlanType:
    v = (value or "").strip().lower()
    if v in ("freemium", "premium_monthly", "premium_yearly", "enterprise"):
        return v  # type: ignore[return-value]
    return "freemium"


def _coerce_plan_type(value: str) -> PlanType:
    v = (value or "").strip().lower()
    if v in ("freemium", "premium_monthly", "premium_yearly", "enterprise"):
        return v  # type: ignore[return-value]
    raise HTTPException(status_code=400, detail=f"Unknown plan_type '{value}'")


def _api_plan_label(plan_type: str) -> str:
    if plan_type in ("premium_monthly", "premium_yearly"):
        return "premium"
    if plan_type == "enterprise":
        return "enterprise"
    return "freemium"


def _subscription_snapshot(row: Subscription | None, now: datetime) -> dict[str, object]:
    period_start, period_end = _month_bounds(now)

    if not row:
        limit = FREEMIUM_UPLOADS_LIMIT
        return {
            "plan_type": "freemium",
            "status": "active",
            "is_active": True,
            "monthly_uploads_limit": limit,
            "used_uploads": 0,
            "remaining_uploads": limit,
            "expires_at": None,
            "period_start": period_start,
            "period_end": period_end,
            "stripe_subscription_id": None,
            "payment_provider": "freemium",
        }

    status = (row.status or "active").lower()
    expires_at = row.expires_at
    is_active = status == "active" and (expires_at is None or expires_at >= now)

    if is_active:
        plan_type = _normalize_plan_type(row.plan_type)
        monthly_limit = int(row.monthly_uploads_limit)
        used_uploads = int(row.used_uploads)
        if not row.period_start or row.period_start.strftime("%Y-%m") != period_start.strftime("%Y-%m"):
            used_uploads = 0
        return {
            "plan_type": plan_type,
            "status": status,
            "is_active": True,
            "monthly_uploads_limit": monthly_limit,
            "used_uploads": used_uploads,
            "remaining_uploads": max(0, monthly_limit - used_uploads),
            "expires_at": expires_at,
            "period_start": row.period_start or period_start,
            "period_end": row.period_end or period_end,
            "stripe_subscription_id": row.stripe_subscription_id,
            "payment_provider": row.payment_provider,
        }

    limit = FREEMIUM_UPLOADS_LIMIT
    return {
        "plan_type": "freemium",
        "status": "freemium",
        "is_active": False,
        "monthly_uploads_limit": limit,
        "used_uploads": 0,
        "remaining_uploads": limit,
        "expires_at": None,
        "period_start": period_start,
        "period_end": period_end,
        "stripe_subscription_id": None,
        "payment_provider": "freemium",
    }


async def _get_subscription_row(db: AsyncSession, user_id: int) -> Subscription | None:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    return result.scalar_one_or_none()


async def get_user_subscription(db: AsyncSession, user_id: int) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    row = await _get_subscription_row(db, user_id)
    return _subscription_snapshot(row, now)


async def get_subscription_api_response(db: AsyncSession, user_id: int) -> dict[str, object]:
    if not billing_enabled():
        return {
            "plan_type": "freemium",
            "status": "testing",
            "uploads_limit": _TESTING_UNLIMITED,
            "uploads_used": 0,
            "uploads_remaining": _TESTING_UNLIMITED,
            "current_period_end": None,
            "is_active": True,
            "payment_provider": "disabled",
            "stripe_subscription_id": None,
        }

    sub = await get_user_subscription(db, user_id)
    period_end = sub.get("expires_at") or sub.get("period_end")
    period_end_str = period_end.isoformat() if hasattr(period_end, "isoformat") else (
        str(period_end) if period_end else None
    )
    return {
        "plan_type": _api_plan_label(str(sub["plan_type"])),
        "status": str(sub["status"]),
        "uploads_limit": int(sub["monthly_uploads_limit"]),
        "uploads_used": int(sub["used_uploads"]),
        "uploads_remaining": int(sub["remaining_uploads"]),
        "current_period_end": period_end_str,
        "is_active": bool(sub["is_active"]),
        "payment_provider": str(sub.get("payment_provider") or "freemium"),
        "stripe_subscription_id": sub.get("stripe_subscription_id"),
    }


def plan_type_from_price_id(price_id: str) -> PlanType:
    monthly = os.getenv("STRIPE_PRICE_ID_MONTHLY", "").strip()
    yearly = os.getenv("STRIPE_PRICE_ID_YEARLY", "").strip()
    payg = os.getenv("STRIPE_PRICE_ID_PAYG", "").strip()
    enterprise = os.getenv("STRIPE_PRICE_ID_ENTERPRISE", "").strip() or payg
    if price_id == monthly:
        return "premium_monthly"
    if price_id == yearly:
        return "premium_yearly"
    if price_id == enterprise or price_id == payg:
        return "enterprise"
    return "premium_monthly"


async def get_stripe_customer_id(db: AsyncSession, user_id: int) -> str | None:
    row = await _get_subscription_row(db, user_id)
    return row.stripe_customer_id if row and row.stripe_customer_id else None


async def check_upload_allowed(db: AsyncSession, user_id: int) -> None:
    if not billing_enabled():
        return
    sub = await get_user_subscription(db, user_id)
    if not bool(sub.get("is_active", True)):
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Подписка неактивна. Оформите тариф для загрузки файлов.",
                "upgrade_url": "/#/pricing",
                "code": "subscription_inactive",
            },
        )
    if int(sub["used_uploads"]) >= int(sub["monthly_uploads_limit"]):
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Лимит загрузок исчерпан. Оформите подписку.",
                "upgrade_url": "/#/pricing",
                "code": "upload_limit_exceeded",
            },
        )


async def consume_upload_slot(db: AsyncSession, user_id: int, tenant_id: int) -> None:
    if not billing_enabled():
        return

    now = datetime.now(timezone.utc)
    period_start, period_end = _month_bounds(now)

    row = await _get_subscription_row(db, user_id)
    if not row:
        plan_type: PlanType = "freemium"
        row = Subscription(
            user_id=user_id,
            tenant_id=tenant_id,
            plan_type=plan_type,
            status="active",
            monthly_uploads_limit=_plan_monthly_limit(plan_type),
            used_uploads=1,
            period_start=period_start,
            period_end=period_end,
            payment_provider="freemium",
        )
        db.add(row)
        await db.flush()
        return

    sub = _subscription_snapshot(row, now)
    if int(sub["used_uploads"]) >= int(sub["monthly_uploads_limit"]):
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Лимит загрузок исчерпан. Оформите подписку.",
                "upgrade_url": "/#/pricing",
                "code": "upload_limit_exceeded",
            },
        )

    if not row.period_start or row.period_start.strftime("%Y-%m") != period_start.strftime("%Y-%m"):
        row.used_uploads = 0
        row.period_start = period_start
        row.period_end = period_end

    row.used_uploads += 1
    await db.flush()


async def activate_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    tenant_id: int,
    plan_type: PlanType,
    yookassa_payment_id: str,
    yookassa_payment_method: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    period_start, period_end = _month_bounds(now)
    expires_at_dt = _plan_expires_at(plan_type, now)
    monthly_limit = _plan_monthly_limit(plan_type)

    stmt = insert(Subscription).values(
        user_id=user_id,
        tenant_id=tenant_id,
        plan_type=plan_type,
        status="active",
        monthly_uploads_limit=monthly_limit,
        used_uploads=0,
        period_start=period_start,
        period_end=period_end,
        expires_at=expires_at_dt,
        yookassa_payment_id=yookassa_payment_id,
        yookassa_payment_method=yookassa_payment_method,
        payment_provider="yookassa",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "plan_type": plan_type,
            "status": "active",
            "monthly_uploads_limit": monthly_limit,
            "used_uploads": 0,
            "period_start": period_start,
            "period_end": period_end,
            "expires_at": expires_at_dt,
            "yookassa_payment_id": yookassa_payment_id,
            "yookassa_payment_method": yookassa_payment_method,
            "payment_provider": "yookassa",
        },
    )
    await db.execute(stmt)


async def activate_stripe_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    tenant_id: int,
    plan_type: PlanType,
    stripe_customer_id: str | None,
    stripe_subscription_id: str | None,
    current_period_start: datetime | None,
    current_period_end: datetime | None,
    status: str = "active",
) -> None:
    now = datetime.now(timezone.utc)
    period_start = current_period_start or _month_bounds(now)[0]
    period_end = current_period_end or _month_bounds(now)[1]
    monthly_limit = _plan_monthly_limit(plan_type)

    stmt = insert(Subscription).values(
        user_id=user_id,
        tenant_id=tenant_id,
        plan_type=plan_type,
        status=status,
        monthly_uploads_limit=monthly_limit,
        used_uploads=0,
        period_start=period_start,
        period_end=period_end,
        expires_at=current_period_end,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        payment_provider="stripe",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "plan_type": plan_type,
            "status": status,
            "monthly_uploads_limit": monthly_limit,
            "period_start": period_start,
            "period_end": period_end,
            "expires_at": current_period_end,
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "payment_provider": "stripe",
        },
    )
    await db.execute(stmt)


async def cancel_stripe_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    effective_date: datetime | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    effective = effective_date or now
    period_start, period_end = _month_bounds(now)
    row = await _get_subscription_row(db, user_id)
    if not row:
        return
    row.status = "canceled"
    row.expires_at = effective
    row.plan_type = "freemium"
    row.monthly_uploads_limit = FREEMIUM_UPLOADS_LIMIT
    row.used_uploads = 0
    row.period_start = period_start
    row.period_end = period_end
    row.stripe_subscription_id = None
    row.payment_provider = "freemium"
    await db.flush()


async def cancel_subscription(db: AsyncSession, *, user_id: int) -> None:
    now = datetime.now(timezone.utc)
    period_start, period_end = _month_bounds(now)
    row = await _get_subscription_row(db, user_id)
    if not row:
        return
    row.status = "canceled"
    row.expires_at = now
    row.plan_type = "freemium"
    row.monthly_uploads_limit = FREEMIUM_UPLOADS_LIMIT
    row.used_uploads = 0
    row.period_start = period_start
    row.period_end = period_end
    row.yookassa_payment_id = None
    row.yookassa_payment_method = None
    row.stripe_subscription_id = None
    row.payment_provider = "freemium"
    await db.flush()


async def resolve_user_tenant(db: AsyncSession, user_id: int) -> int:
    from app.models.user import User

    result = await db.execute(select(User.tenant_id).where(User.id == user_id))
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="User tenant not found")
    return int(tenant_id)
