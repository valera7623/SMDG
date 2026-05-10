"""Фоновый планировщик повторной отправки webhook-доставок."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import exc, select

from app.core.database import AsyncSessionLocal
from app.core.log_utils import ThrottledErrorLogger
from app.core.webhook import webhook_dispatcher
from app.models.webhook import DeliveryStatus, WebhookDelivery

logger = logging.getLogger(__name__)


async def webhook_retry_scheduler() -> None:
    """Фоновая задача для повторной отправки неудачных webhook доставок.

    Логирование throttled через ``ThrottledErrorLogger`` (см.
    ``app/core/log_utils.py``): первый фейл — WARNING, повторы той же
    сигнатуры — DEBUG, каждые ~5 мин — напоминание в WARNING, при
    восстановлении — INFO. Это не даёт шедулеру затопить лог при
    длительной деградации (БД остановлена, DNS не резолвится и т.п.).

    Backoff на sleep: при штатной работе ``BASE_SLEEP``, при длительных
    сбоях растёт до ``MAX_SLEEP`` — чтобы не долбить разрушенную
    зависимость каждые 10 секунд.
    """
    # Ждём чтобы миграции успели примениться
    await asyncio.sleep(5)

    BASE_SLEEP: int = 10
    MAX_SLEEP: int = 60
    throttled = ThrottledErrorLogger(logger=logger, remind_every=30)
    LOG_KEY = "webhook_retry"

    while True:
        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(WebhookDelivery)
                    .where(
                        WebhookDelivery.status == DeliveryStatus.RETRYING.value,
                        WebhookDelivery.next_retry_at <= datetime.now(timezone.utc),
                        WebhookDelivery.attempts < WebhookDelivery.max_attempts,
                    )
                    .limit(50)
                )
                result = await db.execute(stmt)
                pending_retries = result.scalars().all()

                for delivery in pending_retries:
                    from app.models.webhook import WebhookSubscription

                    sub_stmt = select(WebhookSubscription).where(
                        WebhookSubscription.id == delivery.subscription_id
                    )
                    sub_result = await db.execute(sub_stmt)
                    subscription = sub_result.scalar_one_or_none()

                    if subscription and subscription.is_active:
                        await webhook_dispatcher._send_with_retry(
                            subscription=subscription,
                            payload_json=delivery.payload,
                            db=db,
                        )

                await db.commit()

            throttled.recovered(
                LOG_KEY,
                message="✅ %s recovered after %d failed attempts",
            )
            await asyncio.sleep(BASE_SLEEP)

        except asyncio.CancelledError:
            raise
        except (exc.ProgrammingError, exc.OperationalError) as e:
            throttled.failure(LOG_KEY, e, message="%s failed: %s")
            failures = throttled.failures(LOG_KEY)
            await asyncio.sleep(min(BASE_SLEEP * max(1, failures // 10), MAX_SLEEP))
        except Exception as e:
            throttled.failure(
                LOG_KEY,
                e,
                message="%s unexpected error: %s",
                include_traceback_on_new=True,
            )
            failures = throttled.failures(LOG_KEY)
            await asyncio.sleep(min(BASE_SLEEP * max(1, failures // 10), MAX_SLEEP))

        await asyncio.sleep(30)
