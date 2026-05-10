import asyncio
import builtins
from unittest.mock import MagicMock, patch

import pytest

from app.core.bulkhead import (
    Bulkhead,
    BulkheadRejectedError,
    BulkheadTimeoutError,
    bulkhead as bulkhead_decorator,
    get_bulkhead,
    initialize_bulkheads,
)


@pytest.fixture(autouse=True)
def clear_bulkhead_registry():
    """Изоляция глобального реестра для тестов ``get_bulkhead`` / ``initialize``."""
    import app.core.bulkhead as bh

    bh._bulkheads.clear()
    yield
    bh._bulkheads.clear()


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


@pytest.mark.asyncio
async def test_execute_rejects_when_closed():
    bh = Bulkhead("closed-test", max_concurrent=1, queue_size=0, timeout_seconds=1.0)
    await bh.close()

    async def ok():
        return 1

    with pytest.raises(BulkheadRejectedError, match="CLOSED"):
        await bh.execute(ok)


@pytest.mark.asyncio
async def test_queue_full_rejects():
    bh = Bulkhead("qf", max_concurrent=1, queue_size=1, timeout_seconds=2.0)

    async def slow():
        await asyncio.sleep(0.3)
        return "a"

    a = asyncio.create_task(bh.execute(slow))
    b = asyncio.create_task(bh.execute(slow))
    await asyncio.sleep(0.05)
    with pytest.raises(BulkheadRejectedError, match="queue is full"):
        await bh.execute(slow)

    await asyncio.gather(a, b, return_exceptions=True)


@pytest.mark.asyncio
async def test_open_after_close():
    bh = Bulkhead("reopen", 1, 0, 1.0)
    await bh.close()
    await bh.open()
    async def x():
        return 42

    assert await bh.execute(x) == 42


@pytest.mark.asyncio
async def test_get_state_and_utilization():
    bh = Bulkhead("metrics", max_concurrent=2, queue_size=0, timeout_seconds=1.0)

    async def work():
        await asyncio.sleep(0.05)
        return 1

    await bh.execute(work)
    st = bh.get_state()
    assert st["name"] == "metrics"
    assert st["state"] == "open"
    assert "metrics" in st and st["metrics"]["total_completed"] >= 1
    assert "utilization" in st


@pytest.mark.asyncio
async def test_is_overloaded_true():
    bh = Bulkhead("ol", max_concurrent=2, queue_size=3, timeout_seconds=1.0)
    bh._metrics.active_requests = 2
    bh._metrics.queued_requests = 3
    assert await bh.is_overloaded() is True


@pytest.mark.asyncio
async def test_is_overloaded_false_when_queue_disabled():
    bh = Bulkhead("ol2", max_concurrent=2, queue_size=0, timeout_seconds=1.0)
    bh._metrics.active_requests = 2
    bh._metrics.queued_requests = 0
    assert await bh.is_overloaded() is False


@pytest.mark.asyncio
async def test_bulkhead_decorator_executes():
    @bulkhead_decorator("dec", max_concurrent=1, queue_size=0, timeout_seconds=1.0)
    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(2, 3) == 5
    assert hasattr(add, "_bulkhead")


@pytest.mark.asyncio
async def test_publish_metrics_skips_on_import_error(monkeypatch):
    bh = Bulkhead("imp", 1, 0, 1.0)
    real_import = builtins.__import__

    def _guard(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.core.bulkhead_metrics":
            raise ImportError("simulated metrics import failure")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guard)
    bh._publish_metrics()


@pytest.mark.asyncio
async def test_publish_metrics_rejected_and_timeout_deltas():
    """Ветки ``rejected_delta`` / ``timeout_delta`` в ``_publish_metrics``."""
    bh = Bulkhead("prom", 1, 0, 0.01)
    inc_rej = MagicMock()
    inc_to = MagicMock()

    with (
        patch("app.core.bulkhead_metrics.bulkhead_rejected_total") as rej,
        patch("app.core.bulkhead_metrics.bulkhead_timeout_total") as to,
        patch("app.core.bulkhead_metrics.bulkhead_active") as act,
        patch("app.core.bulkhead_metrics.bulkhead_queued") as qd,
        patch("app.core.bulkhead_metrics.bulkhead_utilization") as ut,
    ):
        rej.labels.return_value.inc = inc_rej
        to.labels.return_value.inc = inc_to
        act.labels.return_value.set = MagicMock()
        qd.labels.return_value.set = MagicMock()
        ut.labels.return_value.set = MagicMock()

        bh._metrics.total_rejected = 5
        bh._metrics.total_timeout = 3
        bh._last_reported_rejected = 3
        bh._last_reported_timeout = 1
        bh._metrics.active_requests = 0
        bh._metrics.queued_requests = 0

        bh._publish_metrics()

        inc_rej.assert_called_once_with(2)
        inc_to.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_get_bulkhead_creates_from_config_and_unknown_default():
    import app.core.bulkhead as bh_mod

    bh_mod._bulkheads.clear()
    api_bh = get_bulkhead("api")
    assert api_bh.name == "api"
    assert get_bulkhead("api") is api_bh

    unk = get_bulkhead("custom_unknown_service")
    assert unk.name == "custom_unknown_service"


@pytest.mark.asyncio
async def test_initialize_bulkheads_preloads_all():
    import app.core.bulkhead as bh_mod

    bh_mod._bulkheads.clear()
    initialize_bulkheads()
    cfg = bh_mod._get_bulkhead_configs()
    for name in cfg:
        assert name in bh_mod._bulkheads


@pytest.mark.asyncio
async def test_max_concurrent_zero_get_state():
    bh = Bulkhead("zero", max_concurrent=0, queue_size=0, timeout_seconds=1.0)
    st = bh.get_state()
    assert st["utilization"] == 0
