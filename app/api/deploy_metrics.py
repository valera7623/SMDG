"""Prometheus-метрики деплоя SMDG.

Экспонирует счётчики/gauges для мониторинга rolling updates:

- ``smdg_info`` — ярлык с ``version`` и ``git_sha`` текущего контейнера.
  Позволяет в Grafana одновременно видеть, сколько реплик какой версии
  работают во время rolling-update.
- ``smdg_build_timestamp_seconds`` — Unix-timestamp старта процесса
  (для вычисления uptime).
- ``smdg_deploy_attempts_total`` — счётчик попыток деплоя (инкрементится
  скриптом ``zero_downtime_deploy.sh`` через pushgateway).
- ``smdg_deploy_duration_seconds`` — длительность последнего успешного
  деплоя.
- ``smdg_current_replica_id`` — hostname-id текущего контейнера
  (удобно для отладки sticky-сессий).

Использование:

    from fastapi import FastAPI
    from app.api.deploy_metrics import register_deploy_metrics

    app = FastAPI()
    register_deploy_metrics(app)

Метрики сразу попадут в ``/metrics`` (через ``prometheus-fastapi-instrumentator``).
"""
from __future__ import annotations

import logging
import os
import socket
import time

from fastapi import FastAPI
from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Базовые метрики (создаём на уровне модуля, чтобы регистрация в default
# Collector registry произошла ровно один раз).
# ---------------------------------------------------------------------------

_INFO = Gauge(
    "smdg_info",
    "Информация о сборке SMDG (1 = активна)",
    labelnames=("version", "git_sha", "deployment_type", "replica"),
)

_BUILD_TS = Gauge(
    "smdg_build_timestamp_seconds",
    "Unix-timestamp старта контейнера (uptime = time() - этот gauge)",
    labelnames=("version", "replica"),
)

DEPLOY_ATTEMPTS = Counter(
    "smdg_deploy_attempts_total",
    "Количество попыток деплоя (инкрементится CI-скриптом)",
    labelnames=("status",),   # success|failed|rollback
)

DEPLOY_DURATION = Gauge(
    "smdg_deploy_duration_seconds",
    "Длительность последнего деплоя",
    labelnames=("status",),
)

CURRENT_VERSION = Gauge(
    "smdg_current_version_info",
    "Текущая версия, закодированная через info-метрику (для alerting)",
    labelnames=("version",),
)

# Gauge rolling-update готовности (1 = ready, 0 = shutting_down/overloaded)
READINESS_GAUGE = Gauge(
    "smdg_ready",
    "Готовность реплики принимать трафик (1=ready, 0=not_ready)",
    labelnames=("replica",),
)


# ---------------------------------------------------------------------------
# Публичная функция: вызывается из app/main.py в lifespan startup
# ---------------------------------------------------------------------------


def register_deploy_metrics(app: FastAPI) -> None:
    """Регистрирует статические метрики о текущей сборке.

    Значения берутся из env-переменных, которые выставляет compose/CI:
        SMDG_VERSION        — IMAGE_TAG (например, 4.0.1 или sha-abc123)
        SMDG_GIT_SHA        — полный git SHA
        DEPLOYMENT_TYPE     — intl/russia/saas/single
        HOSTNAME            — id контейнера (docker задаёт автоматически)
    """
    version = os.getenv("SMDG_VERSION", "dev")
    git_sha = os.getenv("SMDG_GIT_SHA", "unknown")
    deployment_type = os.getenv("DEPLOYMENT_TYPE", "intl")
    replica = os.getenv("HOSTNAME") or socket.gethostname()

    _INFO.labels(
        version=version,
        git_sha=git_sha,
        deployment_type=deployment_type,
        replica=replica,
    ).set(1)

    _BUILD_TS.labels(version=version, replica=replica).set(time.time())
    CURRENT_VERSION.labels(version=version).set(1)
    READINESS_GAUGE.labels(replica=replica).set(1)

    logger.info(
        "📈 deploy metrics registered: version=%s git=%s replica=%s",
        version, git_sha[:12], replica,
    )

    # Привязываем readiness-gauge к событиям жизненного цикла.
    # При graceful shutdown выставляем 0 → Prometheus/Grafana сразу видит,
    # что реплика выводится из ротации.
    @app.on_event("shutdown")
    async def _on_shutdown() -> None:  # pragma: no cover
        READINESS_GAUGE.labels(replica=replica).set(0)


def mark_deploy_success(duration_seconds: float) -> None:
    """Вызывается из CI/скрипта (через pushgateway) при успешном деплое."""
    DEPLOY_ATTEMPTS.labels(status="success").inc()
    DEPLOY_DURATION.labels(status="success").set(duration_seconds)


def mark_deploy_failed(duration_seconds: float) -> None:
    """Вызывается из CI/скрипта при неудачном деплое."""
    DEPLOY_ATTEMPTS.labels(status="failed").inc()
    DEPLOY_DURATION.labels(status="failed").set(duration_seconds)


def mark_deploy_rollback(duration_seconds: float) -> None:
    """Вызывается при авто-rollback."""
    DEPLOY_ATTEMPTS.labels(status="rollback").inc()
    DEPLOY_DURATION.labels(status="rollback").set(duration_seconds)


__all__ = [
    "register_deploy_metrics",
    "mark_deploy_success",
    "mark_deploy_failed",
    "mark_deploy_rollback",
    "DEPLOY_ATTEMPTS",
    "DEPLOY_DURATION",
    "CURRENT_VERSION",
    "READINESS_GAUGE",
]
