"""Тесты для фонового сборщика health-метрик.

Все внешние зависимости (engine, redis, storage, database) мокаются —
задача тестов проверить, что:

* успешная проверка выставляет gauge в 1;
* неуспешная / таймаут — в 0;
* collector устойчив к исключениям и не падает.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import metrics
from app.core import health_collector as hc


@pytest.mark.asyncio
async def test_update_gauge_from_check_success() -> None:
    async def ok() -> None:
        return None

    metrics.smdg_db_up.set(0)
    await hc._update_gauge_from_check(metrics.smdg_db_up, ok, name="db")
    assert _gauge_value("smdg_db_up") == 1


@pytest.mark.asyncio
async def test_update_gauge_from_check_failure() -> None:
    async def broken() -> None:
        raise RuntimeError("boom")

    metrics.smdg_db_up.set(1)
    await hc._update_gauge_from_check(metrics.smdg_db_up, broken, name="db")
    assert _gauge_value("smdg_db_up") == 0


@pytest.mark.asyncio
async def test_update_gauge_from_check_timeout(monkeypatch) -> None:
    """Если проверка зависла дольше _CHECK_TIMEOUT_SEC — gauge → 0."""
    monkeypatch.setattr(hc, "_CHECK_TIMEOUT_SEC", 0.05)

    async def hang() -> None:
        await asyncio.sleep(1.0)

    metrics.smdg_redis_up.set(1)
    await hc._update_gauge_from_check(metrics.smdg_redis_up, hang, name="redis")
    assert _gauge_value("smdg_redis_up") == 0


@pytest.mark.asyncio
async def test_update_gauge_from_check_throttles_repeats(caplog) -> None:
    """Повторные ошибки одного типа не должны спамить WARNING."""
    import logging

    # Сбрасываем throttled-state перед тестом — другие тесты могут оставить
    # счётчики (в частности, test_update_gauge_from_check_failure).
    hc._throttled.reset()

    async def broken() -> None:
        raise RuntimeError("persistent error")

    metrics.smdg_db_up.set(1)

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=hc.logger.name):
        # 4 подряд одинаковые ошибки
        for _ in range(4):
            await hc._update_gauge_from_check(metrics.smdg_db_up, broken, name="database")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    # Первая ошибка — WARNING, остальные — DEBUG.
    assert len(warnings) == 1
    assert "database" in warnings[0].getMessage()
    assert len(debugs) >= 3


@pytest.mark.asyncio
async def test_update_gauge_from_check_recovery_logs_info(caplog) -> None:
    """После серии сбоев успешная проверка пишет INFO 'recovered'."""
    import logging

    hc._throttled.reset()

    async def broken() -> None:
        raise RuntimeError("down")

    async def ok() -> None:
        return None

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=hc.logger.name):
        await hc._update_gauge_from_check(metrics.smdg_redis_up, broken, name="redis")
        await hc._update_gauge_from_check(metrics.smdg_redis_up, broken, name="redis")
        await hc._update_gauge_from_check(metrics.smdg_redis_up, ok, name="redis")

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("recovered" in r.getMessage() for r in infos)
    assert _gauge_value("smdg_redis_up") == 1


@pytest.mark.asyncio
async def test_update_audit_heartbeat_no_attr(monkeypatch) -> None:
    """Если у audit_logger нет last_write_ts — просто пишем current time."""
    metrics.smdg_last_audit_timestamp.set(0)
    await hc._update_audit_heartbeat()
    # любое значение > 0 подойдёт (ts = time.time())
    assert _gauge_value("smdg_last_audit_timestamp") > 0


def _gauge_value(name: str) -> float:
    from prometheus_client import REGISTRY

    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == name:
                return sample.value
    raise AssertionError(f"{name} not found in registry")
