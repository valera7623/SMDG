"""Prometheus-метрики SMDG для алертинга и дашбордов.

Модуль централизует ВСЕ доменные метрики SMDG в одном месте. Экспонируются
через ``/metrics`` (регистрируется ``prometheus-fastapi-instrumentator`` в
``app/main.py``). Использование во всех местах приложения происходит через
прямой импорт нужного объекта из ``app.core.metrics``.

Рекомендации:

- Labels cardinality: избегайте unbounded labels (например, user_id, file_id,
  полный URL-путь). Для high-cardinality используйте OTLP traces или логи.
- Гигиена: НЕ логируйте и не пишите в labels PII (e-mail, phone, токены,
  имена пациентов). Метки должны оставаться безопасными при случайном
  экспорте.
- Идемпотентность импорта: prometheus_client регистрирует метрики в глобальном
  ``REGISTRY`` при создании Gauge/Counter/Histogram. Многократный импорт
  модуля безопасен (Python кэширует модули), однако повторное объявление
  метрики с тем же именем в ДРУГИХ модулях приведёт к ``ValueError``.
  Поэтому всё живёт ТОЛЬКО здесь.

Версионирование (bump `smdg_version_info`) происходит в ``app/main.py`` при
старте, чтобы Prometheus видел, какая версия обслуживает трафик.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

# =============================================================================
# === Health / доступность зависимостей =======================================
# =============================================================================
# Булевы gauges (1 = up, 0 = down) заполняются фоновым collector'ом каждые
# ~30 сек (см. ``app/core/health_collector.py``). Используются в правилах
# Prometheus ``smdg_*_up == 0`` для алертов SMDGDatabaseDown и др.

smdg_db_up = Gauge(
    "smdg_db_up",
    "PostgreSQL connectivity status (1=up, 0=down)",
)
smdg_redis_up = Gauge(
    "smdg_redis_up",
    "Redis connectivity status (1=up, 0=down)",
)
smdg_storage_up = Gauge(
    "smdg_storage_up",
    "Storage (Local/S3) connectivity status (1=up, 0=down)",
)
smdg_dicom_up = Gauge(
    "smdg_dicom_up",
    "DICOM Viewer availability (1=up, 0=down, отсутствует если фича выключена)",
)

# Timestamp последнего успешно сброшенного аудита. Prometheus-правило
# ``(time() - smdg_last_audit_timestamp) > 300`` выстрелит, если аудит молчит
# дольше 5 минут — это может означать, что сервис жив, но audit pipeline
# сломан (право-регулятивный инцидент).
smdg_last_audit_timestamp = Gauge(
    "smdg_last_audit_timestamp",
    "Unix-timestamp последней записи в audit log",
)

# Размер очередей фоновых задач. Если растёт — worker не успевает.
smdg_cleanup_queue_size = Gauge(
    "smdg_cleanup_queue_size",
    "Количество задач в очереди cleanup (APScheduler pending jobs)",
)
smdg_webhook_retry_queue_size = Gauge(
    "smdg_webhook_retry_queue_size",
    "Количество webhook-доставок в состоянии RETRYING",
)


# =============================================================================
# === Бизнес-метрики ==========================================================
# =============================================================================
# Counters инкрементируются в точке возникновения события (upload.py и т.д.).
# reason — ограниченный enum: оставляем только короткие и стабильные причины,
# чтобы не раздувать cardinality.

upload_failures_total = Counter(
    "upload_failures_total",
    "Total upload failures",
    labelnames=("reason",),  # quota_exceeded | invalid_type | storage_error | auth
)
download_failures_total = Counter(
    "download_failures_total",
    "Total download failures",
    labelnames=("reason",),  # not_found | expired | auth | storage_error
)
auth_failures_total = Counter(
    "auth_failures_total",
    "Total authentication failures",
    labelnames=("reason",),  # bad_password | user_locked | user_not_found | token_expired
)
auth_2fa_failures_total = Counter(
    "auth_2fa_failures_total",
    "Total 2FA verification failures",
)

# Rate limiting — по endpoint, а не по пользователю (cardinality!).
rate_limit_exceeded_total = Counter(
    "rate_limit_exceeded_total",
    "Rate limit exceeded events",
    labelnames=("endpoint",),
)

# Multi-tenancy: безопасность. Любой positive tick здесь — инцидент.
cross_tenant_access_total = Counter(
    "cross_tenant_access_total",
    "Cross-tenant access attempts (security incident)",
)

# Read replicas: распределение read-трафика по целям роутинга.
# target: replica_0 | replica_1 | ... | master_fallback
read_distribution_total = Counter(
    "smdg_read_distribution_total",
    "Read traffic distribution by DB target",
    labelnames=("target",),
)

archived_total = Counter(
    "archived_total",
    "Archived entities total",
    labelnames=("source_type",),
)

archive_failures_total = Counter(
    "archive_failures_total",
    "Archive operation failures total",
    labelnames=("operation", "source_type"),
)

restore_duration_seconds = Histogram(
    "restore_duration_seconds",
    "Archive restore duration in seconds",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

# DICOM операции (если включен).
dicom_render_duration_seconds = Histogram(
    "dicom_render_duration_seconds",
    "DICOM render duration (full pipeline: fetch → decode → render)",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
dicom_render_failures_total = Counter(
    "dicom_render_failures_total",
    "DICOM render failures",
)


# =============================================================================
# === Performance =============================================================
# =============================================================================
# Детализированные histogram'ы живут параллельно с ``http_request_duration_seconds``
# от prometheus-fastapi-instrumentator. Мы ведём СВОИ бакеты для критичных
# endpoints, чтобы получить точный p95 для алертов.

api_latency_seconds = Histogram(
    "api_latency_seconds",
    "API endpoint latency (server-side, без сети клиента)",
    labelnames=("method", "endpoint"),
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)


# =============================================================================
# === Resource / capacity =====================================================
# =============================================================================

smdg_active_requests = Gauge(
    "smdg_active_requests",
    "Текущее количество in-flight HTTP-запросов",
)
smdg_active_tenants = Gauge(
    "smdg_active_tenants",
    "Количество активных tenants (SaaS)",
)
smdg_total_files = Gauge(
    "smdg_total_files",
    "Количество файлов в хранилище (по данным БД)",
)
smdg_total_users = Gauge(
    "smdg_total_users",
    "Количество пользователей в разрезе ролей",
    labelnames=("role",),
)


# =============================================================================
# === Version info ============================================================
# =============================================================================
# Info — специальный тип, всегда экспортирует одну строку с меткой 1:
# ``smdg_version_info{version="4.0.0",deployment_type="saas"} 1``.

smdg_version_info = Info(
    "smdg_version",
    "SMDG build / deployment information",
)


__all__ = [
    "smdg_db_up",
    "smdg_redis_up",
    "smdg_storage_up",
    "smdg_dicom_up",
    "smdg_last_audit_timestamp",
    "smdg_cleanup_queue_size",
    "smdg_webhook_retry_queue_size",
    "upload_failures_total",
    "download_failures_total",
    "auth_failures_total",
    "auth_2fa_failures_total",
    "rate_limit_exceeded_total",
    "cross_tenant_access_total",
    "read_distribution_total",
    "archived_total",
    "archive_failures_total",
    "restore_duration_seconds",
    "dicom_render_duration_seconds",
    "dicom_render_failures_total",
    "api_latency_seconds",
    "smdg_active_requests",
    "smdg_active_tenants",
    "smdg_total_files",
    "smdg_total_users",
    "smdg_version_info",
]
