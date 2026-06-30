"""Persist payment rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment


async def record_stripe_payment(
    db: AsyncSession,
    *,
    payment_id: str,
    user_id: int,
    tenant_id: int,
    amount_cents: int,
    currency: str,
    status: str,
    description: str,
    payment_intent_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    stmt = insert(Payment).values(
        payment_id=payment_id,
        user_id=user_id,
        tenant_id=tenant_id,
        amount=amount_cents,
        currency=currency,
        status=status,
        description=description,
        provider="stripe",
        stripe_payment_intent_id=payment_intent_id,
        stripe_checkout_session_id=session_id,
        metadata_json=metadata or {},
        captured_at=now if status == "succeeded" else None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["payment_id"],
        set_={
            "status": status,
            "captured_at": now if status == "succeeded" else None,
            "metadata_json": metadata or {},
        },
    )
    await db.execute(stmt)


async def upsert_yookassa_payment(
    db: AsyncSession,
    *,
    payment_id: str,
    user_id: int,
    tenant_id: int,
    amount_cents: int,
    currency: str,
    status: str,
    description: str | None,
    payment_method: str | None,
    metadata: dict[str, Any] | None = None,
    captured_at: datetime | None = None,
) -> None:
    stmt = insert(Payment).values(
        payment_id=payment_id,
        user_id=user_id,
        tenant_id=tenant_id,
        amount=amount_cents,
        currency=currency,
        status=status,
        description=description,
        payment_method=payment_method,
        provider="yookassa",
        metadata_json=metadata or {},
        captured_at=captured_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["payment_id"],
        set_={
            "status": status,
            "amount": amount_cents,
            "currency": currency,
            "description": description,
            "payment_method": payment_method,
            "metadata_json": metadata or {},
            "captured_at": captured_at,
        },
    )
    await db.execute(stmt)
