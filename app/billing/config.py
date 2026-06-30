"""Billing feature flags from environment (same pattern as ReportAgent)."""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def billing_enabled() -> bool:
    """When false: no upload limits, checkout disabled (testing / maintenance)."""
    return _env_bool("BILLING_ENABLED", default=True)


def stripe_checkout_enabled() -> bool:
    if not billing_enabled():
        return False
    return bool(os.getenv("STRIPE_SECRET_KEY", "").strip())


def yookassa_checkout_enabled() -> bool:
    if not billing_enabled():
        return False
    return bool(
        os.getenv("YOOKASSA_SHOP_ID", "").strip()
        and os.getenv("YOOKASSA_SECRET_KEY", "").strip()
    )
