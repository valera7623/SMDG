"""YooKassa REST API v3 client."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


class YooKassaClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response_body: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True)
class YooKassaPaymentResult:
    payment_id: str
    confirmation_url: str


class YooKassaClient:
    _payment_cache: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        *,
        shop_id: str,
        secret_key: str,
        api_url: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.api_url = (api_url or os.getenv("YOOKASSA_API_URL") or "https://api.yookassa.ru/v3").rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _auth(self) -> tuple[str, str]:
        return (self.shop_id, self.secret_key)

    def _idempotence_key(self) -> str:
        return uuid.uuid4().hex

    def _cache_get(self, payment_id: str) -> dict[str, Any] | None:
        cached = self._payment_cache.get(payment_id)
        if not cached:
            return None
        if time.time() - float(cached.get("ts", 0)) > 300:
            return None
        return cached.get("data")

    def _cache_set(self, payment_id: str, data: dict[str, Any]) -> None:
        self._payment_cache[payment_id] = {"ts": time.time(), "data": data}

    async def create_payment(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        return_url: str,
        metadata: dict[str, Any] | None = None,
        capture: bool = True,
    ) -> YooKassaPaymentResult:
        amount_value = f"{amount / 100:.2f}"
        payload: dict[str, Any] = {
            "amount": {"value": amount_value, "currency": currency},
            "capture": capture,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": metadata or {},
        }
        headers = {"Idempotence-Key": self._idempotence_key()}

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                f"{self.api_url}/payments",
                json=payload,
                headers=headers,
                auth=self._auth(),
            )

        if resp.status_code >= 400:
            raise YooKassaClientError(
                f"YooKassa create_payment failed: HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=_safe_json(resp),
            )

        data = resp.json()
        payment_id = str(data.get("id") or "")
        confirmation_url = (
            data.get("confirmation", {}).get("confirmation_url") or data.get("confirmation_url") or ""
        )
        if not payment_id or not confirmation_url:
            raise YooKassaClientError("YooKassa create_payment returned unexpected payload", response_body=data)

        return YooKassaPaymentResult(payment_id=payment_id, confirmation_url=str(confirmation_url))

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.get(f"{self.api_url}/payments/{payment_id}", auth=self._auth())
            except httpx.HTTPError as exc:
                cached = self._cache_get(payment_id)
                if cached is not None:
                    return cached
                raise YooKassaClientError(f"YooKassa get_payment network error: {exc}") from exc

        if resp.status_code >= 500:
            cached = self._cache_get(payment_id)
            if cached is not None:
                return cached
            raise YooKassaClientError(
                f"YooKassa get_payment failed with 5xx HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=_safe_json(resp),
            )

        if resp.status_code >= 400:
            raise YooKassaClientError(
                f"YooKassa get_payment failed HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=_safe_json(resp),
            )

        data = resp.json()
        self._cache_set(payment_id, data)
        return data

    async def capture_payment(self, payment_id: str) -> dict[str, Any]:
        headers = {"Idempotence-Key": self._idempotence_key()}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                f"{self.api_url}/payments/{payment_id}/capture",
                headers=headers,
                auth=self._auth(),
            )

        if resp.status_code >= 500:
            cached = self._cache_get(payment_id)
            if cached is not None:
                return cached
            raise YooKassaClientError(
                f"YooKassa capture_payment failed with 5xx HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=_safe_json(resp),
            )

        if resp.status_code >= 400:
            raise YooKassaClientError(
                f"YooKassa capture_payment failed HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=_safe_json(resp),
            )

        data = resp.json()
        self._cache_set(payment_id, data)
        return data

    async def refund_payment(self, payment_id: str, *, amount: int) -> dict[str, Any]:
        headers = {"Idempotence-Key": self._idempotence_key(), "Content-Type": "application/json"}
        amount_value = f"{amount / 100:.2f}"
        payload = {"payment_id": payment_id, "amount": {"value": amount_value, "currency": "RUB"}}

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                f"{self.api_url}/refunds",
                json=payload,
                headers=headers,
                auth=self._auth(),
            )

        if resp.status_code >= 400:
            raise YooKassaClientError(
                f"YooKassa refund_payment failed HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_body=_safe_json(resp),
            )

        return resp.json()


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text[:500]
