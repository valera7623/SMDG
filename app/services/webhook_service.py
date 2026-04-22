"""
Webhook sending facade with DLQ integration.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.services.dead_letter_service import dlq

logger = logging.getLogger(__name__)


async def send_webhook_with_dlq(
    url: str,
    payload: Dict[str, Any],
    webhook_id: int,
    max_retries: int = 5,
) -> bool:
    """Отправить webhook с fallback в DLQ при неуспехе."""
    try:
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_CALL_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            if 200 <= response.status_code < 300:
                return True
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
    except Exception as exc:  # noqa: BLE001
        await dlq.send_to_dlq(
            queue_name="webhook",
            payload={"url": url, "payload": payload, "webhook_id": webhook_id},
            error=exc,
            max_retries=max_retries,
        )
        logger.warning("Webhook moved to DLQ: webhook_id=%s url=%s", webhook_id, url)
        return False
