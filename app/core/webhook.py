# app/core/webhook.py
"""
Webhook Dispatcher — отправка уведомлений о событиях.

Поддерживает:
- HMAC-SHA256 подпись payload
- Retry с exponential backoff
- Асинхронную отправку через aiohttp
- Логирование результатов доставки
"""
import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.webhook import (
    WebhookSubscription,
    WebhookDelivery,
    DeliveryStatus,
)
from app.services.dead_letter_service import dlq
from app.core.bulkhead import get_bulkhead

logger = logging.getLogger(__name__)


@dataclass
class WebhookPayload:
    """Стандартизированный payload для webhook."""
    event: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "smdg"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "timestamp": self.timestamp,
            "source": self.source,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def sign_payload(payload: str, secret: str) -> str:
    """Создать HMAC-SHA256 подпись payload."""
    return hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


class WebhookDispatcher:
    """
    Диспетчер webhook-уведомлений.

    Отправляет уведомления подписанным подпискам при возникновении событий.
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Ленивая инициализация HTTP сессии."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Закрыть HTTP сессию."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def dispatch(
        self,
        event: str,
        data: Dict[str, Any],
        db: Optional[AsyncSession] = None,
        tenant_id: int | None = None,
    ):
        """
        Отправить webhook-уведомление всем подписанным подпискам.

        Args:
            event: Тип события (например, "file.uploaded")
            data: Данные события
            db: Опциональная DB сессия (если не передана — создаётся новая)
            tenant_id: Tenant, которому принадлежит событие. Если передан,
                доставляем событие только подпискам этого tenant.
        """
        payload = WebhookPayload(event=event, data=data)
        payload_json = payload.to_json()

        own_session = db is None
        if own_session:
            db = AsyncSessionLocal()

        try:
            stmt = select(WebhookSubscription).where(
                WebhookSubscription.is_active == True,
                WebhookSubscription.events.contains([event])
            )
            if tenant_id is not None:
                stmt = stmt.where(WebhookSubscription.tenant_id == tenant_id)
            result = await db.execute(stmt)
            subscriptions = result.scalars().all()

            if not subscriptions:
                logger.debug(f"   Нет подписок на событие: {event}")
                return

            logger.info(f"🔔 Webhook dispatch: {event} ({len(subscriptions)} подписок)")

            tasks = []
            bulkhead = get_bulkhead("webhook")
            for sub in subscriptions:
                task = asyncio.create_task(
                    bulkhead.execute(
                        self._send_with_retry,
                        subscription=sub,
                        payload_json=payload_json,
                        db=db,
                    )
                )
                tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            # Gracefully handle missing tables (migration not run yet)
            if "does not exist" in str(e) or "UndefinedTableError" in str(e):
                logger.debug(f"🔔 Webhook tables not ready yet, skipping dispatch: {event}")
            else:
                logger.error(f"❌ Webhook dispatch error: {e}")
        finally:
            if own_session:
                try:
                    await db.close()
                except Exception:
                    pass

    async def _send_with_retry(
        self,
        subscription: WebhookSubscription,
        payload_json: str,
        db: AsyncSession,
    ):
        """
        Отправить webhook с retry и exponential backoff.
        """
        max_attempts = subscription.max_retries or 3
        timeout_value = min(
            subscription.timeout_seconds or settings.WEBHOOK_CALL_TIMEOUT_SECONDS,
            settings.WEBHOOK_CALL_TIMEOUT_SECONDS,
        )
        timeout = aiohttp.ClientTimeout(total=timeout_value)

        delivery = WebhookDelivery(
            subscription_id=subscription.id,
            event="unknown",
            payload=payload_json,
            status=DeliveryStatus.PENDING.value,
            max_attempts=max_attempts,
        )

        db.add(delivery)
        await db.flush()

        for attempt in range(1, max_attempts + 1):
            try:
                session = await self._get_session()

                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "SMDG-Webhook/1.0",
                    "X-Webhook-Event": payload_json[:100],
                }

                if subscription.secret:
                    signature = sign_payload(payload_json, subscription.secret)
                    headers["X-Webhook-Signature"] = f"sha256={signature}"
                    headers["X-Webhook-Timestamp"] = datetime.now(timezone.utc).isoformat()

                if subscription.headers:
                    try:
                        custom_headers = json.loads(subscription.headers)
                        headers.update(custom_headers)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid custom headers in subscription {subscription.id}")

                async with session.post(
                    subscription.url,
                    data=payload_json,
                    headers=headers,
                    timeout=timeout
                ) as response:
                    response_body = await response.text()

                    delivery.attempts = attempt
                    delivery.response_status = response.status
                    delivery.response_body = response_body[:2000]

                    if response.ok:
                        delivery.status = DeliveryStatus.SUCCESS.value
                        delivery.delivered_at = datetime.now(timezone.utc)
                        delivery.error_message = None
                        subscription.last_triggered_at = delivery.delivered_at

                        logger.info(
                            f"✅ Webhook delivered: {subscription.url} "
                            f"(status={response.status}, attempt={attempt})"
                        )
                    else:
                        delivery.status = DeliveryStatus.FAILED.value
                        delivery.error_message = f"HTTP {response.status}: {response_body[:500]}"

                        if attempt < max_attempts:
                            delivery.status = DeliveryStatus.RETRYING.value
                            backoff = min(2 ** attempt, 300)
                            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                            logger.warning(
                                f"⚠️ Webhook failed (attempt {attempt}/{max_attempts}): "
                                f"{subscription.url} — HTTP {response.status}. Retry через {backoff}с"
                            )
                            await asyncio.sleep(backoff)

            except asyncio.TimeoutError:
                delivery.attempts = attempt
                delivery.status = DeliveryStatus.FAILED.value
                delivery.error_message = f"Timeout after {timeout.total or 10}s"

                if attempt < max_attempts:
                    delivery.status = DeliveryStatus.RETRYING.value
                    backoff = min(2 ** attempt, 300)
                    delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                    logger.warning(
                        f"⏱️ Webhook timeout (attempt {attempt}/{max_attempts}). Retry через {backoff}с"
                    )
                    await asyncio.sleep(backoff)

            except aiohttp.ClientError as e:
                delivery.attempts = attempt
                delivery.status = DeliveryStatus.FAILED.value
                delivery.error_message = f"Client error: {str(e)[:500]}"

                if attempt < max_attempts:
                    delivery.status = DeliveryStatus.RETRYING.value
                    backoff = min(2 ** attempt, 300)
                    delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
                    logger.warning(
                        f"🌐 Webhook client error (attempt {attempt}/{max_attempts}). Retry через {backoff}с"
                    )
                    await asyncio.sleep(backoff)

            except Exception as e:
                delivery.attempts = attempt
                delivery.status = DeliveryStatus.FAILED.value
                delivery.error_message = f"Unexpected error: {str(e)[:500]}"
                logger.error(f"❌ Webhook unexpected error: {e}")
                break

        if delivery.status not in (DeliveryStatus.SUCCESS.value,):
            delivery.status = DeliveryStatus.FAILED.value
            try:
                await dlq.send_to_dlq(
                    queue_name="webhook",
                    payload={
                        "url": subscription.url,
                        "payload": json.loads(payload_json),
                        "webhook_id": subscription.id,
                    },
                    error=Exception(delivery.error_message or "Webhook delivery failed"),
                    max_retries=subscription.max_retries,
                    metadata={"source": "webhook_dispatcher"},
                )
            except Exception as dlq_exc:  # noqa: BLE001
                logger.error("Failed to enqueue webhook to DLQ: %s", dlq_exc)

        try:
            payload_data = json.loads(payload_json)
            delivery.event = payload_data.get("event", "unknown")
        except json.JSONDecodeError:
            delivery.event = "unknown"

        await db.commit()

    async def process_dlq_webhook(self, payload: Dict[str, Any]) -> bool:
        """DLQ handler for webhook payloads."""
        url = payload.get("url")
        webhook_payload = payload.get("payload")
        if not url or webhook_payload is None:
            logger.error("Invalid DLQ webhook payload: %s", payload)
            return False

        session = await self._get_session()
        timeout = aiohttp.ClientTimeout(total=settings.WEBHOOK_CALL_TIMEOUT_SECONDS)
        async with session.post(url, json=webhook_payload, timeout=timeout) as response:
            return response.ok


# Глобальный экземпляр
webhook_dispatcher = WebhookDispatcher()

# Регистрация обработчика webhook для DLQ replay.
dlq.register_handler("webhook", webhook_dispatcher.process_dlq_webhook)
