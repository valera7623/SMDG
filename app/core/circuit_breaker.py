"""Асинхронный Circuit Breaker для SMDG.

Реализация паттерна Circuit Breaker для защиты критичных зависимостей
(PostgreSQL, Redis, S3/MinIO, Jaeger) от каскадных отказов.

Состояния
---------

* ``CLOSED``    — нормальная работа, вызовы проходят; при ``failure_threshold``
                  подряд идущих ошибках → ``OPEN``.
* ``OPEN``      — вызовы блокируются мгновенно (``CircuitBreakerOpenError``).
                  Через ``recovery_timeout`` → ``HALF_OPEN``.
* ``HALF_OPEN`` — «пробный» режим: пропускается не более ``half_open_max_calls``
                  одновременных вызовов. Любая ошибка → ``OPEN``.
                  ``half_open_max_calls`` подряд успехов → ``CLOSED``.

Потокобезопасность
------------------
Все изменения состояния защищены ``asyncio.Lock``. Сам вызов защищаемой
функции выполняется ВНЕ лока (иначе один медленный вызов заблокировал бы
весь брейкер), поэтому статистика обновляется атомарно через лок.

Устойчивость к шумным ошибкам
-----------------------------
Параметр ``exclude_exceptions`` позволяет НЕ считать некоторые исключения
ошибками зависимости: например, ``HTTPException(status=400)`` от валидации
или ``FileNotFoundError`` от штатных проверок — это не признак деградации
downstream-сервиса и не должно открывать брейкер.

Метрики
-------
Модуль дружит с ``app.core.circuit_breaker_metrics``: при каждом изменении
состояния / фиксации ошибки обновляются Prometheus Counter / Gauge.
Импорт metrics выполняется ленью внутри методов, чтобы исключить цикл
импорта (metrics → config → circuit_breaker).
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, Iterable, Optional, TypeVar

# Event loop приложения (устанавливается из ``lifespan``) — для
# ``run_coroutine_threadsafe`` из worker-потоков (OTLP export).
_cb_event_loop: Optional[asyncio.AbstractEventLoop] = None

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Состояния Circuit Breaker. ``str``-enum удобен для JSON-сериализации."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Числовое представление состояния для Prometheus Gauge.
_STATE_NUMERIC: dict[CircuitState, int] = {
    CircuitState.CLOSED: 0,
    CircuitState.OPEN: 1,
    CircuitState.HALF_OPEN: 2,
}


class CircuitBreakerOpenError(Exception):
    """Брошено, когда Circuit Breaker отклоняет вызов без обращения к зависимости.

    Вызывающий код может отличать эту ошибку от реальных ошибок зависимости
    и применять fallback-логику (например, пропустить rate-limiting
    или вернуть HTTP 503).
    """

    def __init__(self, name: str, state: CircuitState, message: Optional[str] = None):
        self.name = name
        self.state = state
        super().__init__(
            message
            or f"Circuit breaker '{name}' is {state.value.upper()}, call rejected"
        )


class CircuitBreaker:
    """Асинхронный Circuit Breaker.

    Args:
        name: Уникальное имя (используется в логах и метках Prometheus).
        failure_threshold: Количество ошибок подряд в ``CLOSED`` для открытия.
        recovery_timeout: Сколько секунд держим ``OPEN`` перед пробой ``HALF_OPEN``.
        half_open_max_calls: Сколько одновременных пробных вызовов разрешено.
            Столько же подряд успехов нужно, чтобы вернуться в ``CLOSED``.
        half_open_timeout: Если в ``HALF_OPEN`` не набралось ни успеха, ни
            провала в течение этого времени — возвращаем ``OPEN`` (страховка
            от зависшего downstream).
        exclude_exceptions: Классы исключений, которые НЕ считаются ошибками
            зависимости. Такой Exception пробрасывается вызывающему, но не
            увеличивает счётчик ошибок и не открывает брейкер.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        half_open_timeout: float = 30.0,
        exclude_exceptions: Iterable[type[BaseException]] = (),
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if half_open_max_calls < 1:
            raise ValueError("half_open_max_calls must be >= 1")

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = float(recovery_timeout)
        self.half_open_max_calls = half_open_max_calls
        self.half_open_timeout = float(half_open_timeout)
        self.exclude_exceptions: tuple[type[BaseException], ...] = tuple(exclude_exceptions)

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: Optional[float] = None
        self._opened_at: Optional[float] = None
        self._half_open_entered_at: Optional[float] = None
        self._half_open_in_flight: int = 0
        self._half_open_success_count: int = 0
        self._half_open_failure_count: int = 0

        # Сумма всех ошибок за всё время — для метрики (гистограмма считается
        # Counter'ом в circuit_breaker_metrics).
        self._total_failures: int = 0
        self._total_opens: int = 0

        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Выполнить асинхронную функцию под защитой брейкера.

        Raises:
            CircuitBreakerOpenError: если брейкер сейчас отклоняет вызовы.
            Exception: оригинальное исключение из ``func`` (если было).
        """
        await self._before_call()
        try:
            result = await func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — нужен самый широкий ловец
            await self._after_call(error=exc)
            raise
        else:
            await self._after_call(error=None)
            return result

    async def reset(self) -> None:
        """Принудительно вернуть брейкер в ``CLOSED`` (админская операция)."""
        async with self._lock:
            logger.info("Circuit breaker '%s' manually reset → CLOSED", self.name)
            self._transition(CircuitState.CLOSED)
            self._failure_count = 0
            self._half_open_success_count = 0
            self._half_open_failure_count = 0
            self._half_open_in_flight = 0

    def get_state(self) -> dict[str, Any]:
        """Снимок состояния для API ``/api/circuit-breaker/status``."""
        return {
            "name": self.name,
            "state": self._state.value,
            "state_numeric": _STATE_NUMERIC[self._state],
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "half_open_max_calls": self.half_open_max_calls,
            "half_open_timeout": self.half_open_timeout,
            "half_open_in_flight": self._half_open_in_flight,
            "half_open_success_count": self._half_open_success_count,
            "half_open_failure_count": self._half_open_failure_count,
            "last_failure_time": self._last_failure_time,
            "opened_at": self._opened_at,
            "half_open_entered_at": self._half_open_entered_at,
            "total_failures": self._total_failures,
            "total_opens": self._total_opens,
        }

    # ---------------------------------------------------------------
    # Внутренние переходы
    # ---------------------------------------------------------------

    async def _before_call(self) -> None:
        """Проверить/поменять состояние перед вызовом; зарезервировать slot."""
        async with self._lock:
            self._maybe_transition_from_timeouts()

            if self._state is CircuitState.OPEN:
                raise CircuitBreakerOpenError(self.name, self._state)

            if self._state is CircuitState.HALF_OPEN:
                # В HALF_OPEN пропускаем только ограниченное число одновременных
                # пробных вызовов. Иначе под восстанавливающийся сервис
                # прилетит шквал и мы снова его уроним.
                if self._half_open_in_flight >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        self.name,
                        self._state,
                        message=(
                            f"Circuit breaker '{self.name}' is HALF_OPEN "
                            f"and probe-slot limit reached "
                            f"({self._half_open_in_flight}/{self.half_open_max_calls})"
                        ),
                    )
                self._half_open_in_flight += 1

    async def _after_call(self, *, error: Optional[BaseException]) -> None:
        """Учесть результат вызова и, возможно, сменить состояние."""
        # Исключённые исключения — не касаемся статистики.
        if error is not None and self.exclude_exceptions and isinstance(error, self.exclude_exceptions):
            async with self._lock:
                if self._state is CircuitState.HALF_OPEN:
                    self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            return

        if error is None:
            await self._record_success()
        else:
            await self._record_failure(error)

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._half_open_success_count += 1
                logger.info(
                    "Circuit breaker '%s' HALF_OPEN success (%d/%d)",
                    self.name,
                    self._half_open_success_count,
                    self.half_open_max_calls,
                )
                if self._half_open_success_count >= self.half_open_max_calls:
                    logger.info(
                        "Circuit breaker '%s' transition HALF_OPEN → CLOSED",
                        self.name,
                    )
                    self._transition(CircuitState.CLOSED)
                    self._failure_count = 0
            elif self._state is CircuitState.CLOSED:
                # Успех в CLOSED обнуляет накопленные «подряд» ошибки.
                if self._failure_count:
                    logger.debug(
                        "Circuit breaker '%s' success — resetting failure counter (%d → 0)",
                        self.name,
                        self._failure_count,
                    )
                self._failure_count = 0

    async def record_batch_worker_success(self) -> None:
        """Успех фоновой доставки (например OTLP batch) без пары ``_before_call``.

        Worker-потоки (OpenTelemetry) не идут через :meth:`call`, поэтому
        ``half_open_in_flight`` не используем — в HALF_OPEN считаем только
        подряд идущие удачные батчи для восстановления CLOSED.
        """
        async with self._lock:
            self._maybe_transition_from_timeouts()
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_success_count += 1
                logger.info(
                    "Circuit breaker '%s' batch HALF_OPEN success (%d/%d)",
                    self.name,
                    self._half_open_success_count,
                    self.half_open_max_calls,
                )
                if self._half_open_success_count >= self.half_open_max_calls:
                    logger.info(
                        "Circuit breaker '%s' transition HALF_OPEN → CLOSED (batch)",
                        self.name,
                    )
                    self._transition(CircuitState.CLOSED)
            elif self._state is CircuitState.CLOSED:
                if self._failure_count:
                    logger.debug(
                        "Circuit breaker '%s' batch success — resetting failure counter",
                        self.name,
                    )
                self._failure_count = 0

    async def _record_failure(self, error: BaseException) -> None:
        async with self._lock:
            self._last_failure_time = time.time()
            self._total_failures += 1
            self._notify_metrics_failure()

            if self._state is CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._half_open_failure_count += 1
                logger.warning(
                    "Circuit breaker '%s' HALF_OPEN failure → OPEN: %r",
                    self.name,
                    error,
                )
                self._transition(CircuitState.OPEN)
                return

            if self._state is CircuitState.CLOSED:
                self._failure_count += 1
                logger.warning(
                    "Circuit breaker '%s' failure %d/%d: %r",
                    self.name,
                    self._failure_count,
                    self.failure_threshold,
                    error,
                )
                if self._failure_count >= self.failure_threshold:
                    logger.error(
                        "Circuit breaker '%s' transition CLOSED → OPEN "
                        "(failures=%d/%d)",
                        self.name,
                        self._failure_count,
                        self.failure_threshold,
                    )
                    self._transition(CircuitState.OPEN)

            # В OPEN мы сюда попасть не должны — _before_call блокирует вызов.

    def _maybe_transition_from_timeouts(self) -> None:
        """Посмотреть на часы и, если прошли нужные таймауты, сменить состояние.

        Вызывается под локом.
        """
        now = time.monotonic()

        if self._state is CircuitState.OPEN:
            if self._opened_at is None:
                # Защита от нештатной инициализации.
                self._opened_at = now
                return
            if (now - self._opened_at) >= self.recovery_timeout:
                logger.info(
                    "Circuit breaker '%s' recovery_timeout reached → HALF_OPEN",
                    self.name,
                )
                self._transition(CircuitState.HALF_OPEN)
            return

        if self._state is CircuitState.HALF_OPEN:
            # Страховка от «зависшего» HALF_OPEN — если слишком долго нет
            # ни успеха, ни провала, возвращаем OPEN, чтобы подождать ещё.
            if (
                self._half_open_entered_at is not None
                and self._half_open_in_flight == 0
                and (now - self._half_open_entered_at) >= self.half_open_timeout
            ):
                logger.warning(
                    "Circuit breaker '%s' HALF_OPEN timeout (%.1fs > %.1fs) → OPEN",
                    self.name,
                    now - self._half_open_entered_at,
                    self.half_open_timeout,
                )
                self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        """Сменить состояние + обновить таймстемпы + толкнуть метрики."""
        now = time.monotonic()
        prev = self._state
        self._state = new_state

        if new_state is CircuitState.OPEN:
            self._opened_at = now
            self._half_open_entered_at = None
            self._half_open_in_flight = 0
            self._half_open_success_count = 0
            self._half_open_failure_count = 0
            if prev is not CircuitState.OPEN:
                self._total_opens += 1
                self._notify_metrics_opened()
        elif new_state is CircuitState.HALF_OPEN:
            self._half_open_entered_at = now
            self._half_open_in_flight = 0
            self._half_open_success_count = 0
            self._half_open_failure_count = 0
        elif new_state is CircuitState.CLOSED:
            self._opened_at = None
            self._half_open_entered_at = None
            self._half_open_in_flight = 0
            self._half_open_success_count = 0
            self._half_open_failure_count = 0
            self._failure_count = 0

        self._notify_metrics_state()

    # ---------------------------------------------------------------
    # Интеграция с Prometheus (ленивый импорт против циклических зависимостей)
    # ---------------------------------------------------------------

    def _notify_metrics_state(self) -> None:
        try:
            from app.core.circuit_breaker_metrics import (  # local import
                circuit_breaker_state,
            )
        except Exception:  # pragma: no cover — метрики не критичны для работы
            return
        try:
            circuit_breaker_state.labels(name=self.name).set(
                _STATE_NUMERIC[self._state]
            )
        except Exception:  # pragma: no cover
            pass

    def _notify_metrics_failure(self) -> None:
        try:
            from app.core.circuit_breaker_metrics import circuit_breaker_failures
        except Exception:  # pragma: no cover
            return
        try:
            circuit_breaker_failures.labels(name=self.name).inc()
        except Exception:  # pragma: no cover
            pass

    def _notify_metrics_opened(self) -> None:
        try:
            from app.core.circuit_breaker_metrics import circuit_breaker_opens
        except Exception:  # pragma: no cover
            return
        try:
            circuit_breaker_opens.labels(name=self.name).inc()
        except Exception:  # pragma: no cover
            pass


# =====================================================================
# Глобальный реестр брейкеров + хелперы
# =====================================================================

_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    *,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[float] = None,
    half_open_max_calls: Optional[int] = None,
    half_open_timeout: Optional[float] = None,
    exclude_exceptions: Iterable[type[BaseException]] = (),
) -> CircuitBreaker:
    """Получить (или создать) именованный CircuitBreaker.

    Значения по умолчанию берутся из ``app.core.config.settings``.
    Повторный вызов с тем же именем возвращает тот же экземпляр — параметры
    при повторе игнорируются (истина — у первого инициализатора).
    """
    cb = _circuit_breakers.get(name)
    if cb is not None:
        return cb

    # Ленивый импорт, чтобы модуль можно было импортировать без полного
    # боотстрапа settings (важно для юнит-тестов).
    try:
        from app.core.config import settings

        ft = failure_threshold if failure_threshold is not None else settings.circuit_breaker_failure_threshold
        rt = recovery_timeout if recovery_timeout is not None else settings.circuit_breaker_recovery_timeout
        hc = half_open_max_calls if half_open_max_calls is not None else settings.circuit_breaker_half_open_max_calls
        ht = half_open_timeout if half_open_timeout is not None else settings.circuit_breaker_half_open_timeout
    except Exception:  # pragma: no cover — fallback для раннего старта
        ft = failure_threshold if failure_threshold is not None else 5
        rt = recovery_timeout if recovery_timeout is not None else 60.0
        hc = half_open_max_calls if half_open_max_calls is not None else 3
        ht = half_open_timeout if half_open_timeout is not None else 30.0

    cb = CircuitBreaker(
        name=name,
        failure_threshold=ft,
        recovery_timeout=rt,
        half_open_max_calls=hc,
        half_open_timeout=ht,
        exclude_exceptions=exclude_exceptions,
    )
    _circuit_breakers[name] = cb
    # Инициализируем Gauge начальным состоянием, чтобы панель Grafana
    # не показывала «No data» до первого события.
    cb._notify_metrics_state()
    return cb


def get_all_circuit_breakers() -> dict[str, CircuitBreaker]:
    """Снимок (копия) реестра брейкеров. Полезен для API/метрик."""
    return dict(_circuit_breakers)


def set_circuit_breaker_event_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """Сохранить event loop API-приложения (вызывать из ``lifespan``).

    Нужен worker-потокам (OpenTelemetry ``BatchSpanProcessor``) чтобы
    зафиксировать сбой/успех в том же :class:`CircuitBreaker`, которым
    пользуется async-код, через ``run_coroutine_threadsafe``.
    """
    global _cb_event_loop
    _cb_event_loop = loop


def schedule_dependency_failure(name: str, error: Exception) -> None:
    """Зафиксировать сбой зависимости из **не-async** worker-потока.

    Планирует на основном event loop выполнение «фиктивного» сбойного
    вызова под тем же :func:`get_circuit_breaker`, чтобы FSM брейкера
    (CLOSED→OPEN, HALF_OPEN→OPEN, …) оставалась согласованной с HTTP/API
    путями. Без заранее заданного loop — no-op (fail-open).
    """
    loop = _cb_event_loop
    if loop is None or loop.is_closed():
        return
    cb = get_circuit_breaker(name)

    async def _work() -> None:
        # Используем ``call`` с функцией, которая бросает исходное
        # исключение: ``_after_call`` корректно увеличит счётчики.
        err = error

        async def _raise() -> None:
            raise err

        try:
            await cb.call(_raise)
        except Exception:
            pass  # сбой уже учтён, исключение не для вызывающего

    try:
        asyncio.run_coroutine_threadsafe(_work(), loop)
    except Exception:  # pragma: no cover
        logger.debug("schedule_dependency_failure: cannot schedule to loop", exc_info=True)


def schedule_batch_worker_success(name: str) -> None:
    """Успешный фоновый батч (OTLP) — инкремент «проб» в HALF_OPEN / сброс CLOSED.

    См. :meth:`CircuitBreaker.record_batch_worker_success`.
    """
    loop = _cb_event_loop
    if loop is None or loop.is_closed():
        return
    cb = get_circuit_breaker(name)

    async def _work() -> None:
        try:
            await cb.record_batch_worker_success()
        except Exception:
            logger.debug("record_batch_worker_success failed for %s", name, exc_info=True)

    try:
        asyncio.run_coroutine_threadsafe(_work(), loop)
    except Exception:  # pragma: no cover
        logger.debug("schedule_batch_worker_success: cannot schedule to loop", exc_info=True)


def circuit_breaker(
    name: str,
    *,
    exclude_exceptions: Iterable[type[BaseException]] = (),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Декоратор для защиты async-функции именованным брейкером."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            cb = get_circuit_breaker(name, exclude_exceptions=exclude_exceptions)
            return await cb.call(func, *args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
    "circuit_breaker",
    "get_all_circuit_breakers",
    "get_circuit_breaker",
    "schedule_batch_worker_success",
    "schedule_dependency_failure",
    "set_circuit_breaker_event_loop",
]
