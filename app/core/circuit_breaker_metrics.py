"""Prometheus-метрики для Circuit Breaker'ов SMDG.

Модуль вынесен отдельно от ``app.core.circuit_breaker`` по двум причинам:

1. Избежание циклического импорта: сам брейкер импортируется из очень
   ранних слоёв приложения (config-валидация, DI), а метрики зависят от
   ``prometheus_client``, который тянет за собой глобальный ``REGISTRY``.
2. Для корректной регистрации метрик ``prometheus_client`` требует, чтобы
   имя было зарегистрировано РОВНО один раз. Если разные модули случайно
   переопределят Gauge с тем же именем, получим ``ValueError``. Держим
   объявления в одном месте — как и остальные метрики SMDG
   (см. ``app.core.metrics``).

Семантика меток
---------------
* ``name`` — имя брейкера, совпадает с ``CircuitBreaker.name``. Низкая
  кардинальность (десяток значений: ``postgresql``, ``redis``,
  ``s3_storage``, ``jaeger``, …).
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge

# Gauge — текущее состояние брейкера.
#   0 = CLOSED  (нормально)
#   1 = OPEN    (вызовы блокируются)
#   2 = HALF_OPEN (идёт проба восстановления)
circuit_breaker_state = Gauge(
    "smdg_circuit_breaker_state",
    "Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)",
    labelnames=("name",),
)

# Counter — общее количество зафиксированных брейкером ошибок зависимости.
circuit_breaker_failures = Counter(
    "smdg_circuit_breaker_failures_total",
    "Total failures recorded by circuit breaker",
    labelnames=("name",),
)

# Counter — сколько раз брейкер переходил в состояние OPEN.
# Рост этого счётчика — сигнал к алерту «дерёт каскад».
circuit_breaker_opens = Counter(
    "smdg_circuit_breaker_opens_total",
    "Times circuit breaker opened (CLOSED → OPEN or HALF_OPEN → OPEN)",
    labelnames=("name",),
)

# Counter — отказ в вызове из-за OPEN/HALF_OPEN (fast-fail перед downstream).
# Считается на вызывающей стороне: в тех местах, где мы ловим
# ``CircuitBreakerOpenError``.
circuit_breaker_rejected_calls = Counter(
    "smdg_circuit_breaker_rejected_calls_total",
    "Calls rejected without reaching the downstream (circuit OPEN/HALF_OPEN)",
    labelnames=("name",),
)


def record_rejected_call(name: str) -> None:
    """Удобный хелпер: инкрементировать ``rejected_calls`` без падения,
    даже если ``prometheus_client`` по какой-то причине недоступен.
    """
    try:
        circuit_breaker_rejected_calls.labels(name=name).inc()
    except Exception:  # pragma: no cover — метрики никогда не должны ронять
        pass


__all__ = [
    "circuit_breaker_state",
    "circuit_breaker_failures",
    "circuit_breaker_opens",
    "circuit_breaker_rejected_calls",
    "record_rejected_call",
]
