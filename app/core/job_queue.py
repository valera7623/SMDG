"""Distributed Redis-backed job queue for stateless workers."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

JobHandler = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class Job:
    id: str
    type: str
    payload: Dict[str, Any]
    created_at: datetime
    retries: int = 0
    max_retries: int = 5


class DistributedJobQueue:
    """Simple distributed queue where any app replica can be a worker."""

    def __init__(self, queue_name: str = "jobs") -> None:
        self.queue_name = queue_name
        self.dead_letter_queue = "dead_letter_queue"
        self.redis_client: Optional[redis.Redis] = None
        self.handlers: Dict[str, JobHandler] = {}
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    def _require_redis(self) -> redis.Redis:
        if self.redis_client is None:
            raise RuntimeError("DistributedJobQueue is not initialized")
        return self.redis_client

    async def init(self) -> None:
        if self.redis_client is not None:
            return
        self.redis_client = redis.from_url(
            settings.JOB_QUEUE_REDIS_URL,
            decode_responses=True,
        )
        await self.redis_client.ping()

    async def close(self) -> None:
        await self.stop()
        if self.redis_client is not None:
            await self.redis_client.close()
        self.redis_client = None

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    async def enqueue(self, job_type: str, payload: Dict[str, Any]) -> str:
        rc = self._require_redis()
        job = Job(
            id=str(uuid.uuid4()),
            type=job_type,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        await rc.lpush(
            self.queue_name,
            json.dumps(
                {
                    "id": job.id,
                    "type": job.type,
                    "payload": job.payload,
                    "created_at": job.created_at.isoformat(),
                    "retries": job.retries,
                    "max_retries": job.max_retries,
                }
            ),
        )
        return job.id

    async def dequeue(self) -> Optional[Job]:
        rc = self._require_redis()
        data = await rc.rpop(self.queue_name)
        if data is None:
            return None
        job_data = json.loads(data)
        return Job(
            id=job_data["id"],
            type=job_data["type"],
            payload=job_data["payload"],
            created_at=datetime.fromisoformat(job_data["created_at"]),
            retries=job_data.get("retries", 0),
            max_retries=job_data.get("max_retries", 5),
        )

    async def requeue(self, job: Job, error: str) -> None:
        rc = self._require_redis()
        job.retries += 1
        if job.retries <= job.max_retries:
            delay = min(2 ** job.retries, 60)
            await asyncio.sleep(delay)
            await rc.lpush(
                self.queue_name,
                json.dumps(
                    {
                        "id": job.id,
                        "type": job.type,
                        "payload": job.payload,
                        "created_at": job.created_at.isoformat(),
                        "retries": job.retries,
                        "max_retries": job.max_retries,
                        "last_error": error,
                    }
                ),
            )
        else:
            await rc.lpush(
                self.dead_letter_queue,
                json.dumps(
                    {
                        "id": job.id,
                        "type": job.type,
                        "payload": job.payload,
                        "error": error,
                    }
                ),
            )

    async def worker(self) -> None:
        self._running = True
        while self._running:
            job = await self.dequeue()
            if job is None:
                await asyncio.sleep(1)
                continue
            handler = self.handlers.get(job.type)
            if handler is None:
                logger.warning("No handler for job type: %s", job.type)
                continue
            try:
                await handler(job.payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Job failed (%s): %s", job.id, exc)
                await self.requeue(job, str(exc))

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self.worker(), name="distributed_job_queue_worker")

    async def stop(self) -> None:
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def get_queue_length(self) -> int:
        rc = self._require_redis()
        return int(await rc.llen(self.queue_name))

    async def get_dead_letter_length(self) -> int:
        rc = self._require_redis()
        return int(await rc.llen(self.dead_letter_queue))


job_queue = DistributedJobQueue()
