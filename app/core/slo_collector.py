"""Фоновый сбор SLO-метрик и расчёт compliance.

Запускается из lifespan ``app/main.py`` как отдельная asyncio-задача,
работает параллельно с :mod:`app.core.health_collector`. Почему они
разделены:

- ``health_collector`` отвечает за оперативные сигналы (up / down)
  и бизнес-счётчики. Его выходы — входы для алертов вида
  ``smdg_db_up == 0``.
- ``slo_collector`` считает «производные» показатели: проценты
  доступности, квантили латентности, потреблённый error budget.
  Его выходы — вход для SLO-дашборда и SLO-алертов.

Принципы реализации повторяют :mod:`app.core.health_collector`:

1. **Fail-open**: ни одна ошибка внутри цикла не должна ронять процесс.
   Все исключения логируются (throttled) и итерация продолжается.
2. **Безопасная отмена**: обрабатываем ``asyncio.CancelledError``.
3. **Нулевое влияние на hot-path**: коллектор не держит shared-locks
   с обработчиками запросов и использует короткоживущие DB-сессии.
4. **Никакого PII**: в метрики попадает только агрегированная
   статистика.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.core.log_utils import ThrottledErrorLogger
from app.core.slo_metrics import (
    api_availability,
    api_latency_p50,
    api_latency_p90,
    api_latency_p99,
    db_availability,
    error_budget_remaining,
    error_budget_spent,
    redis_availability,
    sli_value,
    slo_compliance,
    slo_last_update,
    slo_latency_bucket,
    slo_success_requests,
    slo_total_requests,
    storage_availability,
)

logger = logging.getLogger(__name__)
_throttled = ThrottledErrorLogger(logger=logger, remind_every=30)

# Интервал основного цикла. На проде 60с — достаточно, чтобы тренды
# были «гладкими», и не создаёт лишнюю нагрузку.
SLO_COLLECT_INTERVAL_SEC: int = int(os.getenv("SMDG_SLO_COLLECT_INTERVAL", "60"))

# Таймаут на low-level проверки зависимостей. Меньше SLO-интервала,
# чтобы залипшая проверка не блокировала весь цикл.
_CHECK_TIMEOUT_SEC: float = float(os.getenv("SMDG_SLO_CHECK_TIMEOUT", "5"))


# =============================================================================
# SLO-конфигурация.
#
# ``target`` — целевое значение (для availability — проценты, для
# latency — p99 seconds). ``window_days`` зарезервирован для будущего
# долгосрочного расчёта error budget через Prometheus recording rules.
# =============================================================================
SLO_CONFIG: Dict[str, Dict[str, Any]] = {
    "api_availability": {"target": 99.9, "window_days": 30, "weight": 1.0},
    "api_latency": {"target": 0.5, "window_days": 30, "weight": 0.5},
    "db_availability": {"target": 99.99, "window_days": 30, "weight": 1.0},
    "redis_availability": {"target": 99.99, "window_days": 30, "weight": 0.8},
    "storage_availability": {"target": 99.9, "window_days": 30, "weight": 0.9},
}


# ---------------------------------------------------------------------------
# Health-проверки зависимостей
# ---------------------------------------------------------------------------


async def _check_db() -> None:
    """SELECT 1 в отдельном коннекшене (короткая транзакция)."""
    from app.core.database import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    """PING через shared-пул rate-limiter'а."""
    from app.core.rate_limiter import redis_client

    pong = await redis_client.ping()
    if not pong:
        raise RuntimeError("Redis PING returned falsy")


async def _check_storage() -> None:
    """Лёгкая проверка storage-бекенда (зависит от типа)."""
    from app.core import encrypted_storage
    from app.core.storage_backend import LocalStorageBackend, S3StorageBackend

    if isinstance(encrypted_storage, LocalStorageBackend):
        base = getattr(encrypted_storage, "base_dir", None)
        if not base or not base.exists():
            raise RuntimeError(f"Local storage base dir missing: {base}")
        return

    if isinstance(encrypted_storage, S3StorageBackend):
        client = await encrypted_storage._get_client()
        await client.list_objects_v2(Bucket=encrypted_storage.bucket, MaxKeys=1)
        return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _measure_availability(coro_factory, *, name: str) -> float:
    """Вернуть 100.0, если проверка прошла за таймаут, иначе 0.0.

    В будущем можно перейти на скользящее окно (EMA) — сейчас
    достаточно «мгновенного» значения: collector запускается раз в
    минуту, и Prometheus сам агрегирует ``avg_over_time`` за 1h/24h
    на стороне запроса.
    """
    key = f"slo.{name}"
    try:
        await asyncio.wait_for(coro_factory(), timeout=_CHECK_TIMEOUT_SEC)
        _throttled.recovered(
            key, message="SLO dep '%s' recovered after %d failed attempts"
        )
        return 100.0
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — широкий catch намеренно
        _throttled.failure(key, exc, message="SLO dep '%s' check failed: %s")
        return 0.0


def _histogram_quantile(histogram: Any, quantile: float) -> float:
    """Приближённая оценка квантиля по in-process histogram.

    ``prometheus_client.Histogram`` хранит сырые счётчики бакетов в
    ``_buckets`` / ``_sum``. Для отображения on-dashboard мы используем
    PromQL ``histogram_quantile``, но для internal SLO compliance
    нужна in-process оценка. Алгоритм — линейная интерполяция внутри
    бакета, как в PromQL-функции.

    Возвращает 0.0, если в histogram'е ещё нет наблюдений, или
    ``+Inf``-бакет пустой (метрика не инициализирована).
    """
    try:
        # prometheus_client 0.20+ хранит ``_upper_bounds`` и ``_buckets``.
        upper_bounds = list(histogram._upper_bounds)
        buckets = [b.get() for b in histogram._buckets]
    except Exception:  # noqa: BLE001
        return 0.0

    total = buckets[-1] if buckets else 0.0
    if total <= 0:
        return 0.0

    rank = quantile * total
    # Ищем первый бакет, в котором накоплено >= rank.
    prev_count = 0.0
    prev_bound = 0.0
    for bound, count in zip(upper_bounds, buckets):
        if count >= rank:
            if bound == float("inf"):
                # Для +Inf возвращаем предыдущую границу (лучше, чем inf).
                return prev_bound
            # Линейная интерполяция внутри бакета.
            if count == prev_count:
                return bound
            fraction = (rank - prev_count) / (count - prev_count)
            return prev_bound + fraction * (bound - prev_bound)
        prev_count = count
        prev_bound = bound if bound != float("inf") else prev_bound
    return prev_bound


# ---------------------------------------------------------------------------
# Collector class
# ---------------------------------------------------------------------------


class SLOCollector:
    """Сбор и расчёт SLO-метрик.

    Состояние минимально: ``start_time`` используется только как
    точка отсчёта для логов. Реальные sliding-window'ы делает
    Prometheus на стороне запроса (``avg_over_time`` и т.п.).
    """

    def __init__(self) -> None:
        self.start_time: float = time.time()
        self._stopped: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # 1. Availability
    # ------------------------------------------------------------------
    async def collect_availability_metrics(self) -> None:
        """Обновить availability gauges для API и зависимостей."""
        # API availability — из исторических счётчиков middleware.
        total = _counter_value(slo_total_requests, "api_availability")
        success = _counter_value(slo_success_requests, "api_availability")
        availability_pct = 100.0 if total == 0 else (success / total) * 100.0
        api_availability.set(availability_pct)

        # Dependencies — параллельно, чтобы медленная проверка не блокировала остальные.
        db_pct, redis_pct, storage_pct = await asyncio.gather(
            _measure_availability(_check_db, name="database"),
            _measure_availability(_check_redis, name="redis"),
            _measure_availability(_check_storage, name="storage"),
        )
        db_availability.set(db_pct)
        redis_availability.set(redis_pct)
        storage_availability.set(storage_pct)

    # ------------------------------------------------------------------
    # 2. Latency
    # ------------------------------------------------------------------
    def update_latency_quantiles(self) -> None:
        """Посчитать p50/p90/p99 по in-process histogram'у.

        Эти значения нужны для SLO-compliance расчёта (latency SLO)
        и как fallback для Grafana-панелей, если PromQL недоступен
        (например, в unit-тестах).
        """
        api_latency_p50.set(_histogram_quantile(slo_latency_bucket, 0.50))
        api_latency_p90.set(_histogram_quantile(slo_latency_bucket, 0.90))
        api_latency_p99.set(_histogram_quantile(slo_latency_bucket, 0.99))

    # ------------------------------------------------------------------
    # 3. Error budget
    # ------------------------------------------------------------------
    def calculate_error_budget(self, slo_name: str, target: float) -> float:
        """Расчёт error budget для availability-SLO.

        Возвращает текущее значение availability (%) — оно же идёт
        в SLI. Error budget: допустимое количество ошибок - фактическое.
        Единицы — «запросы», но ради унификации с Grafana-формулами
        мы кладём их в ``*_error_budget_*_seconds`` без конвертации
        (это условное значение, важное — знак / тренд).
        """
        total = _counter_value(slo_total_requests, slo_name)
        success = _counter_value(slo_success_requests, slo_name)
        errors = max(0.0, total - success)
        availability = 100.0 if total == 0 else (success / total) * 100.0

        allowed_errors = total * ((100.0 - target) / 100.0)
        remaining = max(0.0, allowed_errors - errors)
        spent = min(allowed_errors, errors) if total > 0 else 0.0

        error_budget_remaining.labels(slo_name=slo_name).set(remaining)
        error_budget_spent.labels(slo_name=slo_name).set(spent)
        return availability

    # ------------------------------------------------------------------
    # 4. Compliance
    # ------------------------------------------------------------------
    def calculate_slo_compliance(self) -> None:
        """Посчитать compliance для каждого сконфигурированного SLO."""
        for slo_name, config in SLO_CONFIG.items():
            target = float(config["target"])
            compliance = 100.0
            current_value: float = 0.0

            if slo_name == "api_availability":
                current_value = self.calculate_error_budget(slo_name, target)
                compliance = _pct_of_target(current_value, target)
                sli_value.labels(slo_name=slo_name, sli_type="availability").set(current_value)

            elif slo_name == "api_latency":
                current_value = api_latency_p99._value.get()  # type: ignore[attr-defined]
                # Чем ниже p99, тем выше compliance. Линейный score с
                # отсечкой в 0 при превышении target в 2x.
                if current_value <= 0:
                    compliance = 100.0
                elif current_value <= target:
                    compliance = 100.0
                else:
                    ratio = (current_value - target) / target
                    compliance = max(0.0, (1.0 - ratio) * 100.0)
                sli_value.labels(slo_name=slo_name, sli_type="latency").set(current_value)

            elif slo_name in ("db_availability", "redis_availability", "storage_availability"):
                gauge = {
                    "db_availability": db_availability,
                    "redis_availability": redis_availability,
                    "storage_availability": storage_availability,
                }[slo_name]
                current_value = gauge._value.get()  # type: ignore[attr-defined]
                compliance = _pct_of_target(current_value, target)
                sli_value.labels(slo_name=slo_name, sli_type="availability").set(current_value)

            slo_compliance.labels(slo_name=slo_name, target=f"{target}%").set(compliance)

        slo_last_update.set(time.time())

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def collect_once(self) -> None:
        """Один полный проход — удобно для тестов."""
        await self.collect_availability_metrics()
        self.update_latency_quantiles()
        self.calculate_slo_compliance()

    async def collect_slo_metrics(self) -> None:
        """Основной бесконечный цикл сбора.

        Должен запускаться в отдельной задаче и отменяться через
        ``task.cancel()`` при shutdown (см. ``app/main.py`` lifespan).
        """
        logger.info(
            "📊 slo_collector запущен: interval=%ds, slos=%s",
            SLO_COLLECT_INTERVAL_SEC,
            ", ".join(SLO_CONFIG),
        )
        try:
            while not self._stopped.is_set():
                start = time.monotonic()
                try:
                    await self.collect_once()
                    _throttled.recovered(
                        "slo.cycle",
                        message="SLO collection recovered after %d failed attempts",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    _throttled.failure("slo.cycle", exc, message="%s failed: %s")

                elapsed = time.monotonic() - start
                sleep_for = max(1.0, SLO_COLLECT_INTERVAL_SEC - elapsed)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=sleep_for)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.info("📊 slo_collector остановлен (CancelledError)")
            raise

    def stop(self) -> None:
        """Мягкая остановка (дополнительно к ``task.cancel()``)."""
        self._stopped.set()


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _counter_value(counter: Any, slo_name: str) -> float:
    """Прочитать текущее значение Counter с labels, не бросая исключений.

    ``prometheus_client.Counter.labels(...)._value.get()`` — приватный
    API, но он стабилен уже много лет и используется в официальных
    интеграциях. В случае смены внутренней структуры (релиз
    prometheus_client) мы просто вернём 0, не валя процесс.
    """
    try:
        return float(counter.labels(slo_name=slo_name)._value.get())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0.0


def _pct_of_target(value: float, target: float) -> float:
    """Compliance как доля от target, клэмпнутая к [0..100]."""
    if target <= 0:
        return 100.0
    return max(0.0, min(100.0, (value / target) * 100.0))


# Глобальный экземпляр — используется в ``app/main.py`` и тестах.
slo_collector: SLOCollector = SLOCollector()


__all__ = [
    "SLOCollector",
    "slo_collector",
    "SLO_CONFIG",
    "SLO_COLLECT_INTERVAL_SEC",
]
