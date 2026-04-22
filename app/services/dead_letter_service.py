"""
Dead Letter Queue service for handling failed messages.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.dlq_metrics import dlq_messages_total, dlq_processing_time, dlq_retries_total
from app.models.dead_letter import DeadLetterLog, DeadLetterMessage

logger = logging.getLogger(__name__)

QueueHandler = Callable[[Dict[str, Any]], Awaitable[bool]]

QUEUE_MAX_RETRIES: Dict[str, int] = {
    "webhook": 5,
    "email": 3,
    "cleanup": 3,
    "dicom": 2,
    "audit": 2,
}


class DeadLetterQueue:
    """Dead Letter Queue для обработки недоставленных сообщений."""

    def __init__(self) -> None:
        self.handlers: Dict[str, QueueHandler] = {}
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    def register_handler(self, queue_name: str, handler: QueueHandler) -> None:
        self.handlers[queue_name] = handler
        logger.info("Registered DLQ handler for queue=%s", queue_name)

    def _resolve_max_retries(self, queue_name: str, explicit_max_retries: Optional[int]) -> int:
        if explicit_max_retries is not None:
            return explicit_max_retries
        return QUEUE_MAX_RETRIES.get(queue_name, settings.DLQ_MAX_RETRIES)

    def _validate_payload_size(self, payload: Dict[str, Any]) -> None:
        payload_size = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        if payload_size > settings.DLQ_MAX_MESSAGE_SIZE_BYTES:
            raise ValueError(
                f"DLQ payload exceeds limit ({payload_size} > {settings.DLQ_MAX_MESSAGE_SIZE_BYTES})"
            )

    async def send_to_dlq(
        self,
        queue_name: str,
        payload: Dict[str, Any],
        error: Exception,
        max_retries: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DeadLetterMessage:
        if not settings.DLQ_ENABLED:
            raise RuntimeError("DLQ is disabled by configuration")

        self._validate_payload_size(payload)
        retries = self._resolve_max_retries(queue_name, max_retries)
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            message = DeadLetterMessage(
                queue_name=queue_name,
                payload=payload,
                error_message=str(error),
                error_type=error.__class__.__name__,
                max_retries=retries,
                next_retry_at=now + timedelta(seconds=settings.DLQ_RETRY_DELAY_SECONDS),
                extra_metadata=metadata or {},
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)

        dlq_messages_total.labels(queue_name=queue_name, status="pending").inc()
        logger.warning(
            "Message sent to DLQ: queue=%s, message_id=%s, error=%s",
            queue_name,
            message.message_id,
            error,
        )
        return message

    async def _append_log(
        self, session: AsyncSession, message_id: str, attempt_number: int, error_text: str
    ) -> None:
        session.add(
            DeadLetterLog(
                message_id=message_id,
                attempt_number=attempt_number,
                error=error_text[:2000],
            )
        )

    async def retry_message(self, message: DeadLetterMessage) -> bool:
        handler = self.handlers.get(message.queue_name)
        if not handler:
            logger.error("No DLQ handler for queue=%s", message.queue_name)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(DeadLetterMessage)
                    .where(DeadLetterMessage.message_id == message.message_id)
                    .values(status="failed", updated_at=datetime.now(timezone.utc))
                )
                await self._append_log(
                    session,
                    message_id=message.message_id,
                    attempt_number=message.retry_count + 1,
                    error_text=f"No handler registered for queue: {message.queue_name}",
                )
                await session.commit()
            return False

        started = datetime.now(timezone.utc)
        success = False

        try:
            success = await handler(message.payload)
            if not success:
                raise RuntimeError("DLQ handler returned False")

            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(DeadLetterMessage)
                    .where(DeadLetterMessage.message_id == message.message_id)
                    .values(
                        status="resolved",
                        resolved_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await self._append_log(
                    session,
                    message_id=message.message_id,
                    attempt_number=message.retry_count + 1,
                    error_text="Successfully resolved after retry",
                )
                await session.commit()

            dlq_messages_total.labels(queue_name=message.queue_name, status="resolved").inc()
            logger.info("DLQ message resolved: %s", message.message_id)
            return True
        except Exception as exc:  # noqa: BLE001
            new_retry_count = message.retry_count + 1
            now = datetime.now(timezone.utc)
            next_retry_at = None
            next_status = "failed"
            if new_retry_count < message.max_retries:
                backoff = settings.DLQ_RETRY_DELAY_SECONDS * (
                    settings.DLQ_RETRY_BACKOFF_MULTIPLIER ** new_retry_count
                )
                next_retry_at = now + timedelta(seconds=min(int(backoff), 3600))
                next_status = "pending"

            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(DeadLetterMessage)
                    .where(DeadLetterMessage.message_id == message.message_id)
                    .values(
                        retry_count=new_retry_count,
                        last_retry_at=now,
                        next_retry_at=next_retry_at,
                        status=next_status,
                        error_message=str(exc)[:4000],
                        error_type=exc.__class__.__name__,
                        updated_at=now,
                    )
                )
                await self._append_log(
                    session,
                    message_id=message.message_id,
                    attempt_number=new_retry_count,
                    error_text=str(exc),
                )
                await session.commit()

            dlq_messages_total.labels(queue_name=message.queue_name, status=next_status).inc()
            dlq_retries_total.labels(queue_name=message.queue_name, success="false").inc()
            logger.warning(
                "DLQ retry failed: message_id=%s attempt=%s/%s status=%s error=%s",
                message.message_id,
                new_retry_count,
                message.max_retries,
                next_status,
                exc,
            )
            return False
        finally:
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            dlq_processing_time.labels(queue_name=message.queue_name).observe(elapsed)
            if success:
                dlq_retries_total.labels(queue_name=message.queue_name, success="true").inc()

    async def process_dlq(self) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DeadLetterMessage)
                .where(
                    DeadLetterMessage.status == "pending",
                    DeadLetterMessage.next_retry_at <= datetime.now(timezone.utc),
                )
                .order_by(DeadLetterMessage.next_retry_at.asc())
                .limit(10)
            )
            messages = result.scalars().all()

            for message in messages:
                await session.execute(
                    update(DeadLetterMessage)
                    .where(DeadLetterMessage.message_id == message.message_id)
                    .values(status="processing", updated_at=datetime.now(timezone.utc))
                )
            await session.commit()

        if messages:
            await asyncio.gather(*(self.retry_message(message) for message in messages))

    async def cleanup_old_messages(self, days: Optional[int] = None) -> int:
        ttl_days = days or settings.DLQ_CLEANUP_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DeadLetterMessage).where(DeadLetterMessage.created_at < cutoff)
            )
            old_messages = result.scalars().all()
            deleted = len(old_messages)
            for message in old_messages:
                await session.delete(message)
            await session.commit()
            return deleted

    async def worker(self) -> None:
        self._running = True
        while self._running:
            try:
                await self.process_dlq()
            except Exception as exc:  # noqa: BLE001
                logger.error("DLQ worker error: %s", exc)
            await asyncio.sleep(10)

    def start(self) -> None:
        if not settings.DLQ_ENABLED:
            logger.info("DLQ worker skipped: DLQ_DISABLED")
            return
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self.worker(), name="dlq_worker")
            logger.info("DLQ worker started")

    async def stop(self) -> None:
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            logger.info("DLQ worker stopped")

    async def get_stats(self) -> Dict[str, int]:
        async with AsyncSessionLocal() as session:
            total = await session.execute(select(func.count()).select_from(DeadLetterMessage))
            pending = await session.execute(
                select(func.count()).where(DeadLetterMessage.status == "pending")
            )
            processing = await session.execute(
                select(func.count()).where(DeadLetterMessage.status == "processing")
            )
            failed = await session.execute(
                select(func.count()).where(DeadLetterMessage.status == "failed")
            )
            resolved = await session.execute(
                select(func.count()).where(DeadLetterMessage.status == "resolved")
            )
            return {
                "total": int(total.scalar() or 0),
                "pending": int(pending.scalar() or 0),
                "processing": int(processing.scalar() or 0),
                "failed": int(failed.scalar() or 0),
                "resolved": int(resolved.scalar() or 0),
            }

    async def replay_message(self, message_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DeadLetterMessage).where(DeadLetterMessage.message_id == message_id)
            )
            message = result.scalar_one_or_none()
            if not message:
                return False

            await session.execute(
                update(DeadLetterMessage)
                .where(DeadLetterMessage.message_id == message_id)
                .values(
                    status="pending",
                    next_retry_at=datetime.now(timezone.utc),
                    retry_count=0,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self._append_log(
                session,
                message_id=message_id,
                attempt_number=0,
                error_text="Manual replay scheduled",
            )
            await session.commit()
            logger.info("DLQ replay scheduled: %s", message_id)
            return True


dlq = DeadLetterQueue()
