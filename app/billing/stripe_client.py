"""Stripe API client."""

from __future__ import annotations

import os
import time
from typing import Any

import stripe

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

_subscription_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300.0


class StripeClientError(Exception):
    pass


def _require_configured() -> None:
    if not STRIPE_SECRET_KEY:
        raise StripeClientError("STRIPE_SECRET_KEY is not configured")


def create_customer(*, email: str, metadata: dict[str, str] | None = None) -> str:
    _require_configured()
    try:
        customer = stripe.Customer.create(email=email, metadata=metadata or {})
        return str(customer.id)
    except stripe.StripeError as exc:
        raise StripeClientError("Failed to create Stripe customer") from exc


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    mode: str = "subscription",
    metadata: dict[str, str] | None = None,
) -> dict[str, str]:
    _require_configured()
    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode=mode,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata or {},
            subscription_data={"metadata": metadata or {}} if mode == "subscription" else None,
        )
        return {"session_id": str(session.id), "url": str(session.url)}
    except stripe.StripeError as exc:
        raise StripeClientError("Failed to create checkout session") from exc


def get_subscription(subscription_id: str) -> dict[str, Any]:
    _require_configured()
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        payload = dict(sub)
        _subscription_cache[subscription_id] = (time.time(), payload)
        return payload
    except stripe.StripeError as exc:
        cached = _subscription_cache.get(subscription_id)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]
        raise StripeClientError("Failed to retrieve subscription") from exc


def cancel_subscription(subscription_id: str, *, at_period_end: bool = True) -> bool:
    _require_configured()
    try:
        if at_period_end:
            stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        else:
            stripe.Subscription.delete(subscription_id)
        return True
    except stripe.StripeError as exc:
        raise StripeClientError("Failed to cancel subscription") from exc


def retrieve_price(price_id: str) -> dict[str, Any]:
    _require_configured()
    try:
        return dict(stripe.Price.retrieve(price_id))
    except stripe.StripeError as exc:
        raise StripeClientError(f"Failed to retrieve price {price_id}") from exc


def create_refund(*, payment_intent_id: str, amount_cents: int | None = None) -> dict[str, Any]:
    _require_configured()
    try:
        params: dict[str, Any] = {"payment_intent": payment_intent_id}
        if amount_cents is not None:
            params["amount"] = amount_cents
        return dict(stripe.Refund.create(**params))
    except stripe.StripeError as exc:
        raise StripeClientError("Failed to create refund") from exc


def construct_webhook_event(payload: bytes, sig_header: str, secret: str) -> stripe.Event:
    return stripe.Webhook.construct_event(payload, sig_header, secret)
