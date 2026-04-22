"""SLO / SLI метрики SMDG.

Этот модуль дополняет :mod:`app.core.metrics` специализированными
метриками для SLO-мониторинга (availability, latency, error budget).
Он намеренно вынесен в отдельный файл, чтобы:

1. Не ломать существующую семантику ``smdg_*_up`` gauges из
   ``metrics.py`` (бинарные 1/0 для алертинга).
   SLO-gauges ``smdg_*_availability`` хранят процент доступности
   (0..100) для отображения на дашборде.
2. Изолировать «историческую» часть (counters + histogram), на которую
   опирается расчёт compliance в :mod:`app.core.slo_collector`.

Все метрики регистрируются в глобальном ``REGISTRY`` библиотеки
prometheus_client при первом импорте модуля и экспонируются через
``/metrics`` (см. Instrumentator в ``app/main.py``).

Гигиена cardinality:
    Лэйблы ограничены: ``method`` / ``endpoint`` для API-метрик и
    ``slo_name`` для SLO-агрегатов. ``endpoint`` — это route template
    (``/api/files/{file_id}``), а не конкретный URL, поэтому карта
    labels остаётся небольшой.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# =============================================================================
# === SLI: availability =======================================================
# =============================================================================

# Общая доступность API за последнее окно (процент 2xx/все).
# Обновляется коллектором каждую минуту.
api_availability = Gauge(
    "smdg_api_availability",
    "API availability percentage over last hour (0..100)",
)

# Доступность зависимостей в процентах (не путать с бинарными
# ``smdg_db_up``/``smdg_redis_up``/``smdg_storage_up`` — те живут
# в :mod:`app.core.metrics` и используются для алертов вида == 0).
db_availability = Gauge(
    "smdg_db_availability",
    "PostgreSQL availability percentage (0..100)",
)
redis_availability = Gauge(
    "smdg_redis_availability",
    "Redis availability percentage (0..100)",
)
storage_availability = Gauge(
    "smdg_storage_availability",
    "Storage (Local/S3) availability percentage (0..100)",
)


# =============================================================================
# === SLI: latency ============================================================
# =============================================================================
# Аггрегированные гaugi с текущим значением квантилей. Рассчитываются
# коллектором на основе histogram ``smdg_slo_latency_seconds`` —
# дашборду в Grafana удобно показывать single-stat.

api_latency_p50 = Gauge(
    "smdg_api_latency_p50",
    "API latency p50 over last window (seconds)",
)
api_latency_p90 = Gauge(
    "smdg_api_latency_p90",
    "API latency p90 over last window (seconds)",
)
api_latency_p99 = Gauge(
    "smdg_api_latency_p99",
    "API latency p99 over last window (seconds)",
)


# =============================================================================
# === SLO: compliance + error budget ==========================================
# =============================================================================

# SLO compliance в процентах. Лэйбл ``slo_name`` соответствует ключу из
# ``SLO_CONFIG`` в :mod:`app.core.slo_collector`. ``target`` — строковое
# представление цели (например, ``"99.9%"``), удобно для легенды.
slo_compliance = Gauge(
    "smdg_slo_compliance",
    "SLO compliance percentage (0..100)",
    labelnames=("slo_name", "target"),
)

# Текущее значение SLI. ``sli_type`` — availability | latency.
sli_value = Gauge(
    "smdg_sli_value",
    "Current SLI value (units depend on sli_type)",
    labelnames=("slo_name", "sli_type"),
)

# Error budget (в «условных» единицах — для availability это допустимое
# количество не-2xx запросов в окне; коллектор считает остаток). Для
# latency-SLO error budget не имеет смысла — просто оставляем 0.
error_budget_remaining = Gauge(
    "smdg_error_budget_remaining_seconds",
    "Remaining error budget (seconds-equivalent)",
    labelnames=("slo_name",),
)
error_budget_spent = Gauge(
    "smdg_error_budget_spent_seconds",
    "Spent error budget (seconds-equivalent)",
    labelnames=("slo_name",),
)

# Timestamp последнего полного прохода SLO-коллектора. Prometheus-правило
# ``(time() - smdg_slo_last_update) > 300`` диагностирует «зависший» цикл.
slo_last_update = Gauge(
    "smdg_slo_last_update",
    "Unix timestamp последнего успешного обновления SLO-метрик",
)


# =============================================================================
# === Исторические метрики (сырые данные для расчёта SLO) ======================
# =============================================================================
# Counter'ы наращиваются middleware'ом на каждый запрос. На их основе
# коллектор раз в минуту считает availability и compliance.

slo_success_requests = Counter(
    "smdg_slo_success_requests_total",
    "Total successful requests counted towards SLO",
    labelnames=("slo_name",),
)
slo_total_requests = Counter(
    "smdg_slo_total_requests_total",
    "Total requests counted towards SLO",
    labelnames=("slo_name",),
)

# Латентность успешных запросов. Бакеты подобраны под REST API с P99
# в районе 1-2s; если профиль нагрузки другой — пересмотреть.
slo_latency_bucket = Histogram(
    "smdg_slo_latency_seconds",
    "Latency histogram used for SLO latency calculations",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)


__all__ = [
    "api_availability",
    "db_availability",
    "redis_availability",
    "storage_availability",
    "api_latency_p50",
    "api_latency_p90",
    "api_latency_p99",
    "slo_compliance",
    "sli_value",
    "error_budget_remaining",
    "error_budget_spent",
    "slo_last_update",
    "slo_success_requests",
    "slo_total_requests",
    "slo_latency_bucket",
]
