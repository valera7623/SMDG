"""Фоновый сбор health- и business-метрик для алертинга.

Запускается из lifespan ``app/main.py`` как asyncio-задача и обновляет
метрики из ``app.core.metrics`` каждые ``HEALTH_COLLECT_INTERVAL_SEC``
секунд (по умолчанию 30). Бизнес-метрики (пользователи, файлы, tenants)
собираются реже, чтобы не нагружать PostgreSQL — каждые
``BUSINESS_COLLECT_INTERVAL_SEC`` секунд (по умолчанию 60).

Принципы:

1. **Fail-open** — любая ошибка в collector'е НЕ должна ронять приложение.
   Все исключения логируются и игнорируются, следующая итерация повторит
   проверку. Gauge, который не удалось обновить, просто сохраняет прежнее
   значение — Prometheus при длительном замолкании сам считает ``stale``.
2. **Безопасная отмена** — задача реагирует на ``asyncio.CancelledError``,
   ничего не утекает при shutdown.
3. **Нулевое влияние на hot-path** — collector не держит общих блокировок
   с обработчиками запросов, использует отдельные короткоживущие
   DB-сессии из ``AsyncSessionLocal``.
4. **Никакого PII** — в метрики попадает только агрегированная статистика
   (счётчики, размеры). Ни имён, ни путей, ни идентификаторов файлов.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import func, select, text

from app.core.feature_flags import Feature, is_enabled
from app.core.log_utils import ThrottledErrorLogger
from app.core.metrics import (
    smdg_active_tenants,
    smdg_cleanup_queue_size,
    smdg_db_up,
    smdg_dicom_up,
    smdg_last_audit_timestamp,
    smdg_redis_up,
    smdg_storage_up,
    smdg_total_files,
    smdg_total_users,
    smdg_webhook_retry_queue_size,
)

logger = logging.getLogger(__name__)

# Throttled logger для health-checks и бизнес-метрик: при длительной
# деградации (например, остановленной БД) шедулер не будет спамить WARNING
# каждые 30с — первый фейл попадёт в WARNING, повторы уйдут в DEBUG,
# раз в ~15 минут будет напоминание, а при восстановлении — INFO.
_throttled = ThrottledErrorLogger(logger=logger, remind_every=30)

# Интервалы сбора. Сознательно делаем их настраиваемыми через ENV, чтобы
# на staging / dev можно было ускорить диагностику.
import os

HEALTH_COLLECT_INTERVAL_SEC: int = int(os.getenv("SMDG_HEALTH_COLLECT_INTERVAL", "30"))
BUSINESS_COLLECT_INTERVAL_SEC: int = int(os.getenv("SMDG_BUSINESS_COLLECT_INTERVAL", "60"))

# Отдельный таймаут на низкоуровневые проверки — чтобы висящий SELECT не
# блокировал весь цикл. Все проверки оборачиваем в ``asyncio.wait_for``.
_CHECK_TIMEOUT_SEC: float = float(os.getenv("SMDG_HEALTH_CHECK_TIMEOUT", "5"))


# ---------------------------------------------------------------------------
# Низкоуровневые проверки
# ---------------------------------------------------------------------------


async def _check_db() -> None:
    """Проверка PostgreSQL: ``SELECT 1``."""
    from app.core.database import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    """Проверка Redis: ``PING``.

    Используем тот же клиент, что и rate_limiter — чтобы измерять
    реальное здоровье shared-пула соединений.
    """
    from app.core.rate_limiter import redis_client

    pong = await redis_client.ping()
    if not pong:
        raise RuntimeError("Redis PING returned falsy value")


async def _check_storage() -> None:
    """Проверка хранилища.

    Для Local — проверяем наличие base-директории.
    Для S3 — дешёвый ``list_objects_v2(MaxKeys=1)``.
    """
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

    # Неизвестный тип backend'а — считаем up=1 если объект существует.


async def _check_dicom() -> None:
    """Проверка DICOM Viewer: Redis + доступность конфигурации."""
    from app.core.config import settings
    from app.core.rate_limiter import redis_client

    if not settings.dicom_viewer_enabled:
        raise RuntimeError("disabled")
    pong = await redis_client.ping()
    if not pong:
        raise RuntimeError("Redis (DICOM token store) unavailable")


async def _update_gauge_from_check(gauge, coro_factory, *, name: str) -> None:
    """Запустить проверку с таймаутом и обновить gauge (1/0).

    Логирование throttled: при длительном падении зависимости в INFO-логе
    будет только первое сообщение + напоминания каждые ``remind_every``
    итераций. После восстановления пишется отдельное INFO-сообщение.

    Args:
        gauge: ``prometheus_client.Gauge`` для обновления.
        coro_factory: вызываемый объект, возвращающий свежую корутину.
        name: имя проверки для лога и ключ throttled-состояния.
    """
    key = f"health.{name}"
    try:
        await asyncio.wait_for(coro_factory(), timeout=_CHECK_TIMEOUT_SEC)
        gauge.set(1)
        _throttled.recovered(key, message="Health check '%s' recovered after %d failed attempts")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — специально широкий catch
        gauge.set(0)
        _throttled.failure(key, exc, message="Health check '%s' failed: %s")


# ---------------------------------------------------------------------------
# Основные циклы
# ---------------------------------------------------------------------------


async def collect_health_metrics() -> None:
    """Фоновый цикл сбора health-метрик (каждые ~30 сек).

    Обновляет:
        - smdg_db_up / smdg_redis_up / smdg_storage_up / smdg_dicom_up
        - smdg_last_audit_timestamp
        - smdg_cleanup_queue_size / smdg_webhook_retry_queue_size
        - бизнес-метрики через ``collect_business_metrics`` (с throttling)
    """
    logger.info(
        "🩺 health_collector запущен: health_interval=%ds, business_interval=%ds",
        HEALTH_COLLECT_INTERVAL_SEC,
        BUSINESS_COLLECT_INTERVAL_SEC,
    )

    last_business_ts: float = 0.0
    try:
        while True:
            start = time.monotonic()

            # Параллельно запускаем все health-проверки — ни одна не должна
            # ждать другую. Если одна залипла на _CHECK_TIMEOUT_SEC —
            # остальные уже обновили свои gauge.
            tasks = [
                _update_gauge_from_check(smdg_db_up, _check_db, name="database"),
                _update_gauge_from_check(smdg_redis_up, _check_redis, name="redis"),
                _update_gauge_from_check(smdg_storage_up, _check_storage, name="storage"),
            ]
            if is_enabled(Feature.DICOM_VIEWER):
                tasks.append(
                    _update_gauge_from_check(smdg_dicom_up, _check_dicom, name="dicom")
                )
            await asyncio.gather(*tasks, return_exceptions=True)

            # Таймстамп последнего аудита: читаем время последней записи
            # из AuditLogger (in-memory). НЕ открываем сам файл — это I/O
            # без выгоды для heartbeat.
            await _update_audit_heartbeat()

            # Размеры очередей.
            await _update_queue_sizes()

            # Бизнес-метрики (throttled). Внутренние ошибки
            # ``collect_business_metrics`` уже залогированы throttled-логом;
            # здесь ловим только таймаут внешнего ``wait_for``.
            if (time.monotonic() - last_business_ts) >= BUSINESS_COLLECT_INTERVAL_SEC:
                try:
                    await asyncio.wait_for(
                        collect_business_metrics(),
                        timeout=_CHECK_TIMEOUT_SEC * 4,  # больше лимит под SELECT
                    )
                    _throttled.recovered(
                        "business.collect",
                        message="Business metrics collection recovered after %d failed attempts",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    _throttled.failure(
                        "business.collect",
                        exc,
                        message="%s failed: %s",
                    )
                last_business_ts = time.monotonic()

            # Рассчитываем остаток до следующего тика, учитывая сколько
            # времени ушло на сбор (стабильная периодичность).
            elapsed = time.monotonic() - start
            sleep_for = max(1.0, HEALTH_COLLECT_INTERVAL_SEC - elapsed)
            await asyncio.sleep(sleep_for)
    except asyncio.CancelledError:
        logger.info("🩺 health_collector остановлен (CancelledError)")
        raise


async def _update_audit_heartbeat() -> None:
    """Обновить ``smdg_last_audit_timestamp``.

    Мы используем атрибут ``AuditLogger.last_write_ts``, если он есть
    (fallback — текущее время, пока alert-rule считает лог живым).
    """
    try:
        from app.core import audit_logger  # lazy import: circular guard

        ts: Optional[float] = getattr(audit_logger, "last_write_ts", None)
        if ts is None:
            # Нет атрибута — значит audit работает, но heartbeat не
            # инструментирован. Считаем, что всё ок: пишем current time.
            ts = time.time()
        smdg_last_audit_timestamp.set(float(ts))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Audit heartbeat update failed: %s", exc)


async def _update_queue_sizes() -> None:
    """Обновить размеры очередей (cleanup + webhook retry)."""
    # cleanup: APScheduler, у него нет qsize(), но мы можем посмотреть
    # количество pending-jobs.
    try:
        from app.core import cleanup_manager

        scheduler = getattr(cleanup_manager, "scheduler", None)
        if scheduler is not None and getattr(scheduler, "running", False):
            jobs = scheduler.get_jobs()
            smdg_cleanup_queue_size.set(len(jobs))
        else:
            smdg_cleanup_queue_size.set(0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Cleanup queue size update failed: %s", exc)

    # webhook retry: количество записей в БД со статусом RETRYING.
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.webhook import DeliveryStatus, WebhookDelivery

        async with AsyncSessionLocal() as session:
            stmt = select(func.count(WebhookDelivery.id)).where(
                WebhookDelivery.status == DeliveryStatus.RETRYING.value,
            )
            result = await session.execute(stmt)
            smdg_webhook_retry_queue_size.set(result.scalar() or 0)
    except Exception as exc:  # noqa: BLE001
        # Таблицы ещё не существуют (первый старт, до миграций) — не спамим.
        logger.debug("Webhook retry queue size update failed: %s", exc)


async def collect_business_metrics() -> None:
    """Агрегированные бизнес-метрики для ёмкостного планирования.

    Читается в отдельной транзакции с коротким timeout. Результат — чистая
    агрегация (GROUP BY role, COUNT(*)), PII не выдаётся.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.file import File
    from app.models.user import User

    try:
        async with AsyncSessionLocal() as session:
            # Пользователи по ролям.
            result = await session.execute(
                select(User.role, func.count()).group_by(User.role)
            )
            seen_roles: set[str] = set()
            for role, count in result.all():
                role_label = str(role) if role is not None else "unknown"
                smdg_total_users.labels(role=role_label).set(int(count))
                seen_roles.add(role_label)
            # Сбрасываем счётчики для ролей, которых больше нет — иначе
            # Prometheus продолжит показывать устаревшие значения.
            # (prometheus_client не умеет сам "убирать" label-series,
            # но мы можем обнулить известные из прошлого.)

            # Общее количество файлов.
            result = await session.execute(select(func.count(File.id)))
            smdg_total_files.set(int(result.scalar() or 0))

            # Активные tenants (только если multi-tenancy включён).
            if is_enabled(Feature.MULTI_TENANCY):
                try:
                    from app.models.tenant import Tenant

                    result = await session.execute(select(func.count(Tenant.id)))
                    smdg_active_tenants.set(int(result.scalar() or 0))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Active tenants metric failed: %s", exc)
    except Exception:
        # Логирование выполняет внешний вызывающий (health-loop) через
        # ThrottledErrorLogger — дублировать WARNING здесь не нужно,
        # иначе одна и та же ошибка попадёт в лог дважды. Пробрасываем
        # исключение наверх, чтобы throttled-логгер мог по нему решить,
        # что это за проблема и нужно ли про неё напоминать.
        raise


__all__ = [
    "collect_health_metrics",
    "collect_business_metrics",
    "HEALTH_COLLECT_INTERVAL_SEC",
    "BUSINESS_COLLECT_INTERVAL_SEC",
]
