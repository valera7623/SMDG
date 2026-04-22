"""
Email service with DLQ integration.

SMTP sender implementation is injected from application code.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.services.dead_letter_service import dlq

logger = logging.getLogger(__name__)

EmailSender = Callable[[str, str, str, Optional[Dict[str, Any]]], Awaitable[bool]]
_email_sender: Optional[EmailSender] = None


def register_email_sender(sender: EmailSender) -> None:
    """Register async email sender callback."""
    global _email_sender
    _email_sender = sender
    logger.info("Email sender registered for DLQ-aware sending")


async def send_email_with_dlq(
    *,
    to_email: str,
    subject: str,
    body: str,
    metadata: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> bool:
    """Send email and fallback to DLQ when sender fails."""
    if _email_sender is None:
        error = RuntimeError("Email sender is not configured")
        await dlq.send_to_dlq(
            queue_name="email",
            payload={"to_email": to_email, "subject": subject, "body": body, "metadata": metadata or {}},
            error=error,
            max_retries=max_retries,
            metadata={"source": "email_service"},
        )
        return False

    try:
        ok = await _email_sender(to_email, subject, body, metadata)
        if ok:
            return True
        raise RuntimeError("Email sender returned False")
    except Exception as exc:  # noqa: BLE001
        await dlq.send_to_dlq(
            queue_name="email",
            payload={"to_email": to_email, "subject": subject, "body": body, "metadata": metadata or {}},
            error=exc,
            max_retries=max_retries,
            metadata={"source": "email_service"},
        )
        return False


async def _email_dlq_handler(payload: dict) -> bool:
    """Replay handler for email messages from DLQ."""
    if _email_sender is None:
        return False

    to_email = payload.get("to_email")
    subject = payload.get("subject")
    body = payload.get("body")
    metadata = payload.get("metadata")
    if not to_email or subject is None or body is None:
        return False
    return await _email_sender(to_email, subject, body, metadata)


dlq.register_handler("email", _email_dlq_handler)
