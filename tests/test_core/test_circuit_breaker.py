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
    schedule_batch_worker_success,
    schedule_dependency_failure,
    set_circuit_breaker_event_loop,
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


async def test_record_batch_worker_success_resets_failure_counter_in_closed() -> None:
    """Строки 301–307: в CLOSED батч сбрасывает накопленные ошибки."""
    cb = _make_cb(failure_threshold=5)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.failure_count == 1

    await cb.record_batch_worker_success()
    assert cb.failure_count == 0
    assert cb.state is CircuitState.CLOSED


async def test_excluded_exception_in_half_open_decrements_in_flight() -> None:
    """Строки 239–242: исключение из ``exclude_exceptions`` в HALF_OPEN уменьшает in_flight."""
    cb = _make_cb(exclude_exceptions=(ValueError,))
    async with cb._lock:
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_in_flight = 2

    await cb._after_call(error=ValueError("ignored"))

    assert cb._half_open_in_flight == 1  # noqa: SLF001


async def test_open_state_missing_opened_at_sets_timestamp() -> None:
    """Строки 355–358: OPEN без ``_opened_at`` — выставляем время, вызов всё ещё режется как OPEN."""
    cb = _make_cb(failure_threshold=1, recovery_timeout=100)
    with pytest.raises(_Boom):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN
    cb._opened_at = None  # noqa: SLF001

    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(_ok)

    assert cb._opened_at is not None  # noqa: SLF001


async def test_half_open_idle_timeout_returns_to_open() -> None:
    """Строки 375–381: HALF_OPEN без активности дольше ``half_open_timeout`` → OPEN."""
    cb = _make_cb(
        failure_threshold=1,
        recovery_timeout=0.05,
        half_open_max_calls=3,
        half_open_timeout=0.06,
    )
    with pytest.raises(_Boom):
        await cb.call(_fail)
    await asyncio.sleep(0.08)

    await cb.call(_ok)
    assert cb.state is CircuitState.HALF_OPEN

    await asyncio.sleep(0.12)
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(_ok)
    assert cb.state is CircuitState.OPEN


async def test_set_circuit_breaker_event_loop_and_schedule_dependency_failure() -> None:
    """Планирование сбоя из другого потока учитывается в том же брейкере."""
    name = f"sched_fail_{time.time_ns()}"
    cb = get_circuit_breaker(name, failure_threshold=2, recovery_timeout=60.0)

    loop = asyncio.get_running_loop()
    set_circuit_breaker_event_loop(loop)

    def _fire():
        schedule_dependency_failure(name, ValueError("remote"))

    await asyncio.to_thread(_fire)
    await asyncio.sleep(0.05)

    assert cb.get_state()["total_failures"] >= 1

    set_circuit_breaker_event_loop(None)


async def test_schedule_dependency_failure_no_op_without_loop() -> None:
    schedule_dependency_failure("no_loop_cb_never_registered_xyz", RuntimeError("x"))
    assert "no_loop_cb_never_registered_xyz" not in get_all_circuit_breakers()


async def test_set_circuit_breaker_event_loop_closed_loop_no_crash() -> None:
    """Строка 533: ``loop.is_closed()`` — не планируем."""
    name = f"closed_loop_{time.time_ns()}"
    get_circuit_breaker(name, failure_threshold=5)
    loop = asyncio.new_event_loop()
    loop.close()
    set_circuit_breaker_event_loop(loop)
    schedule_dependency_failure(name, ValueError("x"))


async def test_schedule_batch_worker_success_skips_when_loop_closed() -> None:
    import app.core.circuit_breaker as cb_mod

    loop = asyncio.new_event_loop()
    loop.close()
    cb_mod.set_circuit_breaker_event_loop(loop)
    cb_mod.schedule_batch_worker_success("noop_when_closed")


async def test_schedule_batch_worker_success_inner_failure_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строки 569–570: исключение внутри запланированной корутины не пробрасывается."""
    import app.core.circuit_breaker as cb_mod

    name = f"batch_inner_fail_{time.time_ns()}"
    cb = _make_cb()
    cb_mod._circuit_breakers[name] = cb  # noqa: SLF001

    async def _boom() -> None:
        raise RuntimeError("batch boom")

    monkeypatch.setattr(cb, "record_batch_worker_success", _boom)

    loop = asyncio.get_running_loop()
    cb_mod.set_circuit_breaker_event_loop(loop)

    def _fire() -> None:
        cb_mod.schedule_batch_worker_success(name)

    await asyncio.to_thread(_fire)
    await asyncio.sleep(0.05)

    del cb_mod._circuit_breakers[name]  # noqa: SLF001
    cb_mod.set_circuit_breaker_event_loop(None)


async def test_schedule_batch_worker_success_from_thread() -> None:
    import app.core.circuit_breaker as cb_mod

    name = f"sched_batch_{time.time_ns()}"
    cb = _make_cb(failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=2)
    cb_mod._circuit_breakers[name] = cb  # noqa: SLF001

    loop = asyncio.get_running_loop()
    set_circuit_breaker_event_loop(loop)

    with pytest.raises(_Boom):
        await cb.call(_fail)
    await asyncio.sleep(0.08)

    def _fire():
        schedule_batch_worker_success(name)

    await asyncio.to_thread(_fire)
    await asyncio.sleep(0.05)
    assert cb.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)

    del cb_mod._circuit_breakers[name]  # noqa: SLF001
    set_circuit_breaker_event_loop(None)
