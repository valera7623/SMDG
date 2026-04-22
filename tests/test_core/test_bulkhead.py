import asyncio

import pytest

from app.core.bulkhead import Bulkhead, BulkheadRejectedError, BulkheadTimeoutError


@pytest.mark.asyncio
async def test_bulkhead_limits_concurrent():
    """Bulkhead rejects fast when queue is disabled."""
    bulkhead = Bulkhead("test", max_concurrent=2, queue_size=0, timeout_seconds=0.5)

    async def slow_task():
        await asyncio.sleep(0.1)
        return "done"

    tasks = [bulkhead.execute(slow_task) for _ in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert len([r for r in results if isinstance(r, BulkheadRejectedError)]) == 1


@pytest.mark.asyncio
async def test_bulkhead_queue():
    """Bulkhead serves queued requests without errors."""
    bulkhead = Bulkhead("test", max_concurrent=1, queue_size=2, timeout_seconds=1.0)

    async def slow_task():
        await asyncio.sleep(0.2)
        return "done"

    tasks = [bulkhead.execute(slow_task) for _ in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert all(not isinstance(r, Exception) for r in results)


@pytest.mark.asyncio
async def test_bulkhead_timeout():
    """Bulkhead raises timeout when slot is busy too long."""
    bulkhead = Bulkhead("test", max_concurrent=1, queue_size=1, timeout_seconds=0.1)

    async def slow_task():
        await asyncio.sleep(0.5)
        return "done"

    task1 = asyncio.create_task(bulkhead.execute(slow_task))
    await asyncio.sleep(0.05)

    with pytest.raises(BulkheadTimeoutError):
        await bulkhead.execute(slow_task)

    await task1
