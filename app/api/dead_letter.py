"""
API для управления Dead Letter Queue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.core.auth import get_current_admin
from app.core.database import AsyncSessionLocal
from app.models.dead_letter import DeadLetterLog, DeadLetterMessage
from app.services.dead_letter_service import dlq

router = APIRouter(prefix="/api/dlq", tags=["Dead Letter Queue"])


@router.get("/stats")
async def get_dlq_stats(current_admin=Depends(get_current_admin)):
    return await dlq.get_stats()


@router.get("/messages")
async def get_dlq_messages(
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    queue_name: Optional[str] = Query(None, description="Фильтр по очереди"),
    message_id: Optional[str] = Query(None, description="Поиск по message_id"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    current_admin=Depends(get_current_admin),
):
    async with AsyncSessionLocal() as session:
        query = select(DeadLetterMessage)
        count_query = select(func.count()).select_from(DeadLetterMessage)

        if status:
            query = query.where(DeadLetterMessage.status == status)
            count_query = count_query.where(DeadLetterMessage.status == status)
        if queue_name:
            query = query.where(DeadLetterMessage.queue_name == queue_name)
            count_query = count_query.where(DeadLetterMessage.queue_name == queue_name)
        if message_id:
            message_filter = DeadLetterMessage.message_id.ilike(f"%{message_id}%")
            query = query.where(message_filter)
            count_query = count_query.where(message_filter)

        query = query.order_by(DeadLetterMessage.created_at.desc()).offset(offset).limit(limit)
        total = (await session.execute(count_query)).scalar() or 0
        messages = (await session.execute(query)).scalars().all()

        return {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "messages": [
                {
                    "message_id": m.message_id,
                    "queue_name": m.queue_name,
                    "error_message": m.error_message,
                    "error_type": m.error_type,
                    "retry_count": m.retry_count,
                    "max_retries": m.max_retries,
                    "status": m.status,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "next_retry_at": m.next_retry_at.isoformat() if m.next_retry_at else None,
                }
                for m in messages
            ],
        }


@router.get("/messages/{message_id}")
async def get_dlq_message(message_id: str, current_admin=Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        message = (
            await session.execute(
                select(DeadLetterMessage).where(DeadLetterMessage.message_id == message_id)
            )
        ).scalar_one_or_none()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        logs = (
            await session.execute(
                select(DeadLetterLog)
                .where(DeadLetterLog.message_id == message_id)
                .order_by(DeadLetterLog.timestamp.asc())
            )
        ).scalars().all()

        return {
            "message": {
                "message_id": message.message_id,
                "queue_name": message.queue_name,
                "payload": message.payload,
                "error_message": message.error_message,
                "error_type": message.error_type,
                "retry_count": message.retry_count,
                "max_retries": message.max_retries,
                "status": message.status,
                "created_at": message.created_at.isoformat() if message.created_at else None,
                "resolved_at": message.resolved_at.isoformat() if message.resolved_at else None,
                "metadata": message.extra_metadata,
            },
            "logs": [
                {
                    "attempt_number": log.attempt_number,
                    "error": log.error,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                }
                for log in logs
            ],
        }


@router.post("/messages/{message_id}/replay")
async def replay_dlq_message(message_id: str, current_admin=Depends(get_current_admin)):
    if not await dlq.replay_message(message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"status": "replay_scheduled", "message_id": message_id}


@router.delete("/messages/{message_id}")
async def delete_dlq_message(message_id: str, current_admin=Depends(get_current_admin)):
    async with AsyncSessionLocal() as session:
        message = (
            await session.execute(
                select(DeadLetterMessage).where(DeadLetterMessage.message_id == message_id)
            )
        ).scalar_one_or_none()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        await session.delete(message)
        await session.commit()
        return {"status": "deleted", "message_id": message_id}


@router.post("/cleanup")
async def cleanup_dlq(
    days: int = Query(30, ge=1, le=3650, description="Удалить сообщения старше N дней"),
    current_admin=Depends(get_current_admin),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        messages = (
            await session.execute(
                select(DeadLetterMessage).where(DeadLetterMessage.created_at < cutoff)
            )
        ).scalars().all()
        for message in messages:
            await session.delete(message)
        await session.commit()
        return {"deleted": len(messages), "older_than_days": days}
