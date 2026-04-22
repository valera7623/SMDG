"""Unit-тесты для app/core/circuit_breaker.py.

Все тесты синхронные снаружи (pytest.mark.asyncio) и НЕ зависят от
реального PostgreSQL / Redis — мы проверяем только семантику FSM
и корректность учёта метрик.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    circuit_breaker,
    get_all_circuit_breakers,
    get_circuit_breaker,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------


def _make_cb(
    name: str = "test",
    *,
    failure_threshold: int = 3,
    recovery_timeout: float = 0.1,
    half_open_max_calls: int = 2,
    half_open_timeout: float = 1.0,
    exclude_exceptions=(),
) -> CircuitBreaker:
    return CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        half_open_max_calls=half_open_max_calls,
        half_open_timeout=half_open_timeout,
        exclude_exceptions=exclude_exceptions,
    )


class _Boom(Exception):
    pass


class _BoomChild(_Boom):
    pass


async def _ok() -> str:
    return "ok"


async def _fail() -> None:
    raise _Boom("service down")


# ---------------------------------------------------------------------
# CLOSED
# ---------------------------------------------------------------------


async def test_closed_passes_calls() -> None:
    cb = _make_cb()
    assert cb.state is CircuitState.CLOSED

    for _ in range(5):
        assert await cb.call(_ok) == "ok"

    assert cb.state is CircuitState.CLOSED
    assert cb.failure_count == 0


async def test_success_resets_failure_counter_in_closed() -> None:
    cb = _make_cb(failure_threshold=5)

    for _ in range(2):
        with pytest.raises(_Boom):
            await cb.call(_fail)
    assert cb.failure_count == 2

    # Успешный вызов сбрасывает счётчик подряд идущих ошибок.
    assert await cb.call(_ok) == "ok"
    assert cb.failure_count == 0
    assert cb.state is CircuitState.CLOSED


async def test_opens_after_failure_threshold() -> None:
    cb = _make_cb(failure_threshold=3)
    for i in range(3):
        with pytest.raises(_Boom):
            await cb.call(_fail)
        expected = (
            CircuitState.CLOSED if i < 2 else CircuitState.OPEN
        )
        assert cb.state is expected, f"iteration {i}"

    assert cb.failure_count == 3


# ---------------------------------------------------------------------
# OPEN
# ---------------------------------------------------------------------


async def test_open_rejects_calls_fast() -> None:
    cb = _make_cb(failure_threshold=1, recovery_timeout=10)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN

    # Downstream больше не должен вызываться: CircuitBreakerOpenError
    # летит из _before_call до исполнения функции.
    called = {"n": 0}

    async def _should_not_run():
        called["n"] += 1
        return "nope"

    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(_should_not_run)

    assert called["n"] == 0
    assert cb.state is CircuitState.OPEN


async def test_open_to_half_open_after_recovery_timeout() -> None:
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.05)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN

    # Ждём восстановительный таймаут и пробуем вызвать — брейкер должен
    # сам перейти в HALF_OPEN прямо в _before_call.
    await asyncio.sleep(0.08)

    result = await cb.call(_ok)
    assert result == "ok"
    assert cb.state is CircuitState.HALF_OPEN


# ---------------------------------------------------------------------
# HALF_OPEN
# ---------------------------------------------------------------------


async def test_half_open_closes_after_n_successes() -> None:
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=2)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    await asyncio.sleep(0.08)

    # Первый успех — остаёмся в HALF_OPEN.
    await cb.call(_ok)
    assert cb.state is CircuitState.HALF_OPEN

    # Второй успех — переходим в CLOSED.
    await cb.call(_ok)
    assert cb.state is CircuitState.CLOSED
    assert cb.failure_count == 0


async def test_half_open_reverts_to_open_on_any_failure() -> None:
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=3)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    await asyncio.sleep(0.08)

    # Запустим хотя бы один успех, чтобы доказать, что мы в HALF_OPEN.
    await cb.call(_ok)
    assert cb.state is CircuitState.HALF_OPEN

    # Одна ошибка в HALF_OPEN моментально возвращает OPEN.
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN


async def test_half_open_limits_concurrent_probes() -> None:
    """В HALF_OPEN не должно пройти больше, чем ``half_open_max_calls``
    одновременных вызовов."""
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=2)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    await asyncio.sleep(0.08)

    # Готовим «долгие» успешные вызовы, чтобы занять оба probe-слота.
    release = asyncio.Event()

    async def _slow_ok():
        await release.wait()
        return "slow-ok"

    t1 = asyncio.create_task(cb.call(_slow_ok))
    t2 = asyncio.create_task(cb.call(_slow_ok))

    # Дать планировщику войти в _before_call обоим.
    await asyncio.sleep(0.01)

    # Третий вызов должен быть отклонён: probe-slot limit.
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(_slow_ok)

    release.set()
    await asyncio.gather(t1, t2)
    # После двух успехов (=max_calls) брейкер должен быть CLOSED.
    assert cb.state is CircuitState.CLOSED


# ---------------------------------------------------------------------
# exclude_exceptions
# ---------------------------------------------------------------------


async def test_excluded_exceptions_do_not_trip_breaker() -> None:
    cb = _make_cb(failure_threshold=2, exclude_exceptions=(_Boom,))

    # _Boom полностью игнорируется статистикой: счётчик не растёт.
    for _ in range(10):
        with pytest.raises(_Boom):
            await cb.call(_fail)

    assert cb.state is CircuitState.CLOSED
    assert cb.failure_count == 0


async def test_exclude_matches_by_isinstance() -> None:
    cb = _make_cb(failure_threshold=2, exclude_exceptions=(_Boom,))

    async def _raise_child():
        raise _BoomChild()

    with pytest.raises(_BoomChild):
        await cb.call(_raise_child)
    assert cb.failure_count == 0


# ---------------------------------------------------------------------
# reset / get_state / registry
# ---------------------------------------------------------------------


async def test_reset_forces_closed() -> None:
    cb = _make_cb(failure_threshold=1, recovery_timeout=100)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN

    await cb.reset()
    assert cb.state is CircuitState.CLOSED
    assert cb.failure_count == 0

    # После reset успешные вызовы снова проходят.
    assert await cb.call(_ok) == "ok"


async def test_get_state_is_safe_snapshot() -> None:
    cb = _make_cb()
    state = cb.get_state()
    for key in (
        "name",
        "state",
        "state_numeric",
        "failure_count",
        "failure_threshold",
        "total_failures",
        "total_opens",
    ):
        assert key in state
    assert state["state"] == "closed"
    assert state["state_numeric"] == 0


async def test_get_circuit_breaker_returns_same_instance() -> None:
    # Сохраним имена, которых точно не было.
    unique = f"test_singleton_{time.time_ns()}"
    cb1 = get_circuit_breaker(unique)
    cb2 = get_circuit_breaker(unique)
    assert cb1 is cb2
    assert unique in get_all_circuit_breakers()


async def test_decorator_wraps_function() -> None:
    unique = f"test_decorator_{time.time_ns()}"

    @circuit_breaker(unique)
    async def _payload(x: int) -> int:
        if x < 0:
            raise _Boom("negative")
        return x * 2

    assert await _payload(3) == 6

    # Убедимся, что брейкер зарегистрирован.
    assert unique in get_all_circuit_breakers()


# ---------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------


async def test_failure_threshold_validated() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(name="x", failure_threshold=0)


async def test_half_open_max_calls_validated() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(name="x", half_open_max_calls=0)


async def test_total_opens_counter_increments_on_each_open() -> None:
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.01)

    # 1-ое открытие
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN

    # recovery → HALF_OPEN → ошибка → снова OPEN
    await asyncio.sleep(0.02)
    with pytest.raises(_Boom):
        await cb.call(_fail)

    assert cb.state is CircuitState.OPEN
    # Счётчик открытий должен быть 2.
    assert cb.get_state()["total_opens"] == 2


async def test_record_batch_worker_success_closes_from_half_open() -> None:
    """Фоновый успех (OTLP) без call(): OPEN→HALF_OPEN (по таймеру), затем 2 батча → CLOSED."""
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=2)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN

    await asyncio.sleep(0.08)
    # OPEN→HALF_OPEN обрабатывается при первом входе в record_batch_worker_success.
    await cb.record_batch_worker_success()
    assert cb.state is CircuitState.HALF_OPEN

    await cb.record_batch_worker_success()
    assert cb.state is CircuitState.CLOSED
