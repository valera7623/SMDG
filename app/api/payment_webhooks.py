"""Incoming payment webhooks (Stripe + YooKassa)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.billing import stripe_client
from app.billing.payment_records import record_stripe_payment, upsert_yookassa_payment
from app.billing.usage import (
    activate_stripe_subscription,
    activate_subscription,
    cancel_stripe_subscription,
    cancel_subscription,
    plan_type_from_price_id,
    resolve_user_tenant,
)
from app.billing.yookassa_client import YooKassaClient, YooKassaClientError
from app.core.database import AsyncSessionLocal
from app.models.payment import Payment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Payment Webhooks"])

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "").strip()


def _ts_iso(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _metadata_user_id(metadata: dict[str, Any] | None) -> int | None:
    if not metadata:
        return None
    uid = metadata.get("user_id")
    if uid is None:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


def _metadata_tenant_id(metadata: dict[str, Any] | None) -> int | None:
    if not metadata:
        return None
    tid = metadata.get("tenant_id")
    if tid is None:
        return None
    try:
        return int(tid)
    except (TypeError, ValueError):
        return None


async def _handle_checkout_completed(session: dict[str, Any]) -> None:
    metadata = session.get("metadata") or {}
    user_id = _metadata_user_id(metadata)
    if not user_id:
        logger.warning("checkout.session.completed without user_id metadata")
        return

    async with AsyncSessionLocal() as db:
        tenant_id = _metadata_tenant_id(metadata) or await resolve_user_tenant(db, user_id)
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        price_id = metadata.get("price_id") or ""
        plan_type = metadata.get("plan_type") or plan_type_from_price_id(str(price_id))

        if subscription_id:
            sub = stripe_client.get_subscription(str(subscription_id))
            await activate_stripe_subscription(
                db,
                user_id=user_id,
                tenant_id=tenant_id,
                plan_type=plan_type,  # type: ignore[arg-type]
                stripe_customer_id=str(customer_id) if customer_id else None,
                stripe_subscription_id=str(subscription_id),
                current_period_start=_ts_iso(sub.get("current_period_start")),
                current_period_end=_ts_iso(sub.get("current_period_end")),
                status=str(sub.get("status") or "active"),
            )
        else:
            await activate_stripe_subscription(
                db,
                user_id=user_id,
                tenant_id=tenant_id,
                plan_type=plan_type,  # type: ignore[arg-type]
                stripe_customer_id=str(customer_id) if customer_id else None,
                stripe_subscription_id=None,
                current_period_start=_ts_iso(session.get("created")),
                current_period_end=None,
                status="active",
            )

        amount = int(session.get("amount_total") or 0)
        currency = str(session.get("currency") or "usd")
        payment_id = str(session.get("payment_intent") or session.get("id") or uuid.uuid4())
        await record_stripe_payment(
            db,
            payment_id=payment_id,
            user_id=user_id,
            tenant_id=tenant_id,
            amount_cents=amount,
            currency=currency,
            status="succeeded",
            description="Stripe checkout completed",
            payment_intent_id=str(session.get("payment_intent")) if session.get("payment_intent") else None,
            session_id=str(session.get("id")),
            metadata=metadata,
        )
        await db.commit()


async def _sync_subscription_object(sub: dict[str, Any], *, user_id: int | None = None) -> None:
    metadata = sub.get("metadata") or {}
    uid = user_id or _metadata_user_id(metadata)
    if not uid:
        logger.warning("subscription event without user_id")
        return

    status = str(sub.get("status") or "active")
    items = (sub.get("items") or {}).get("data") or []
    price_id = ""
    if items:
        price = items[0].get("price") or {}
        price_id = str(price.get("id") or "")
    plan_type = plan_type_from_price_id(price_id) if price_id else "premium_monthly"

    async with AsyncSessionLocal() as db:
        tenant_id = _metadata_tenant_id(metadata) or await resolve_user_tenant(db, uid)
        if status in ("canceled", "unpaid", "incomplete_expired"):
            await cancel_stripe_subscription(
                db,
                user_id=uid,
                effective_date=_ts_iso(sub.get("canceled_at") or sub.get("current_period_end")),
            )
        else:
            await activate_stripe_subscription(
                db,
                user_id=uid,
                tenant_id=tenant_id,
                plan_type=plan_type,  # type: ignore[arg-type]
                stripe_customer_id=str(sub.get("customer")) if sub.get("customer") else None,
                stripe_subscription_id=str(sub.get("id")),
                current_period_start=_ts_iso(sub.get("current_period_start")),
                current_period_end=_ts_iso(sub.get("current_period_end")),
                status=status,
            )
        await db.commit()


async def _handle_invoice_payment(invoice: dict[str, Any], *, succeeded: bool) -> None:
    metadata = invoice.get("metadata") or {}
    user_id = _metadata_user_id(metadata)
    sub_details = invoice.get("subscription_details") or {}
    if not user_id and isinstance(sub_details, dict):
        user_id = _metadata_user_id(sub_details.get("metadata"))

    amount = int(invoice.get("amount_paid") or invoice.get("amount_due") or 0)
    currency = str(invoice.get("currency") or "usd")
    payment_intent = invoice.get("payment_intent")
    payment_id = str(payment_intent or invoice.get("id") or uuid.uuid4())

    if user_id:
        async with AsyncSessionLocal() as db:
            tenant_id = _metadata_tenant_id(metadata) or await resolve_user_tenant(db, user_id)
            await record_stripe_payment(
                db,
                payment_id=payment_id,
                user_id=user_id,
                tenant_id=tenant_id,
                amount_cents=amount,
                currency=currency,
                status="succeeded" if succeeded else "failed",
                description="Stripe subscription invoice",
                payment_intent_id=str(payment_intent) if payment_intent else None,
                metadata=metadata,
            )
            await db.commit()


@router.post("/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=401)

    payload = await request.body()
    sig = request.headers.get("Stripe-Signature") or ""
    try:
        event = stripe_client.construct_webhook_event(payload, sig, WEBHOOK_SECRET)
    except (stripe.SignatureVerificationError, ValueError):
        raise HTTPException(status_code=401) from None

    event_type = event["type"]
    data_object = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(dict(data_object))
        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            await _sync_subscription_object(dict(data_object))
        elif event_type == "customer.subscription.deleted":
            uid = _metadata_user_id(dict(data_object).get("metadata"))
            if uid:
                async with AsyncSessionLocal() as db:
                    await cancel_stripe_subscription(
                        db,
                        user_id=uid,
                        effective_date=_ts_iso(dict(data_object).get("canceled_at")),
                    )
                    await db.commit()
        elif event_type == "invoice.payment_succeeded":
            await _handle_invoice_payment(dict(data_object), succeeded=True)
        elif event_type == "invoice.payment_failed":
            await _handle_invoice_payment(dict(data_object), succeeded=False)
    except Exception as exc:
        logger.exception("Stripe webhook handler error for %s: %s", event_type, exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed") from exc

    return JSONResponse({"status": "ok"})


def _get_signature_header(request: Request) -> str:
    return request.headers.get("Content-Signature") or request.headers.get("X-Content-Signature") or ""


def _verify_yookassa_signature(raw_body: bytes, signature_header: str) -> bool:
    if not YOOKASSA_SECRET_KEY:
        return False
    sig = signature_header.strip()
    if sig.startswith("sha256="):
        sig = sig.replace("sha256=", "", 1)
    computed = hmac.new(YOOKASSA_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, sig)


def _amount_to_cents(amount_value: str | None) -> int:
    if not amount_value:
        return 0
    return int((Decimal(str(amount_value)) * 100).quantize(Decimal("1")))


@router.post("/yookassa", response_class=JSONResponse)
async def yookassa_webhook(request: Request) -> JSONResponse:
    raw_body = await request.body()
    signature_header = _get_signature_header(request)

    if not _verify_yookassa_signature(raw_body, signature_header):
        logger.warning("YooKassa webhook invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = str(payload.get("event") or "")
    payment = payload.get("object") or {}
    payment_id = str(payment.get("id") or "")
    yookassa_status = str(payment.get("status") or "").lower()

    if not payment_id or "payment." not in event:
        return JSONResponse({"status": "ok"})

    metadata = payment.get("metadata") or {}
    user_id = _metadata_user_id(metadata)
    plan_type = metadata.get("plan_type")

    if not user_id:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Payment).where(Payment.payment_id == payment_id))
            existing = result.scalar_one_or_none()
        if existing:
            user_id = existing.user_id
            if not plan_type and existing.metadata_json:
                plan_type = existing.metadata_json.get("plan_type")

    if not user_id:
        logger.warning("YooKassa webhook missing user_id for payment %s", payment_id)
        return JSONResponse({"status": "ok"})

    amount_value = payment.get("amount", {}).get("value")
    currency = payment.get("amount", {}).get("currency") or "RUB"
    amount_cents = _amount_to_cents(amount_value)
    description = payment.get("description")
    payment_method = payment.get("payment_method")
    payment_method_type = payment_method.get("type") if isinstance(payment_method, dict) else None

    try:
        async with AsyncSessionLocal() as db:
            tenant_id = _metadata_tenant_id(metadata) or await resolve_user_tenant(db, user_id)

            if event == "payment.succeeded" or yookassa_status == "succeeded":
                captured_at = datetime.now(timezone.utc)
                await upsert_yookassa_payment(
                    db,
                    payment_id=payment_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    amount_cents=amount_cents,
                    currency=currency,
                    status="succeeded",
                    description=description[:256] if isinstance(description, str) else None,
                    payment_method=str(payment_method_type) if payment_method_type else None,
                    metadata=metadata,
                    captured_at=captured_at,
                )
                if plan_type:
                    await activate_subscription(
                        db,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        plan_type=str(plan_type),  # type: ignore[arg-type]
                        yookassa_payment_id=payment_id,
                        yookassa_payment_method=str(payment_method_type) if payment_method_type else None,
                    )

            elif event == "payment.waiting_for_capture" or yookassa_status == "waiting_for_capture":
                await upsert_yookassa_payment(
                    db,
                    payment_id=payment_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    amount_cents=amount_cents,
                    currency=currency,
                    status="waiting_for_capture",
                    description=description[:256] if isinstance(description, str) else None,
                    payment_method=str(payment_method_type) if payment_method_type else None,
                    metadata=metadata,
                )
                if os.getenv("YOOKASSA_AUTO_CAPTURE_ON_WAITING", "true").lower() in ("1", "true", "yes"):
                    try:
                        client = YooKassaClient(
                            shop_id=os.getenv("YOOKASSA_SHOP_ID", ""),
                            secret_key=os.getenv("YOOKASSA_SECRET_KEY", ""),
                            api_url=os.getenv("YOOKASSA_API_URL"),
                        )
                        await client.capture_payment(payment_id)
                    except YooKassaClientError as exc:
                        logger.warning("Auto capture failed (ignored): %s", exc)

            elif event == "payment.canceled" or yookassa_status == "canceled":
                await upsert_yookassa_payment(
                    db,
                    payment_id=payment_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    amount_cents=amount_cents,
                    currency=currency,
                    status="canceled",
                    description=description[:256] if isinstance(description, str) else None,
                    payment_method=str(payment_method_type) if payment_method_type else None,
                    metadata=metadata,
                )
                await cancel_subscription(db, user_id=user_id)

            await db.commit()
    except Exception as exc:
        logger.exception("Failed to process YooKassa webhook: %s", exc)

    return JSONResponse({"status": "ok"})
