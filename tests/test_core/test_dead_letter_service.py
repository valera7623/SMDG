import pytest
from sqlalchemy import select

from app.models.dead_letter import DeadLetterMessage
from app.services.dead_letter_service import dlq


@pytest.mark.asyncio
async def test_dlq_send_and_stats(db_session):
    message = await dlq.send_to_dlq(
        queue_name="webhook",
        payload={"url": "http://example.org/hook", "payload": {"ok": True}},
        error=Exception("Test error"),
    )

    assert message.message_id
    assert message.status == "pending"

    stats = await dlq.get_stats()
    assert stats["total"] >= 1
    assert stats["pending"] >= 1


@pytest.mark.asyncio
async def test_dlq_replay_message(db_session):
    message = await dlq.send_to_dlq(
        queue_name="email",
        payload={"to": "test@example.org"},
        error=Exception("SMTP down"),
        max_retries=3,
    )

    ok = await dlq.replay_message(message.message_id)
    assert ok is True

    updated = (
        await db_session.execute(
            select(DeadLetterMessage).where(DeadLetterMessage.message_id == message.message_id)
        )
    ).scalar_one()
    assert updated.status == "pending"
    assert updated.retry_count == 0
