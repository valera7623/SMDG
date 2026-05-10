"""Lifespan startup/shutdown для FastAPI-приложения."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deploy_metrics import register_deploy_metrics
from app.bootstrap.initial_admin import create_first_admin
from app.core import cleanup_manager, encrypted_storage
from app.core.cache import distributed_cache
from app.core.config import settings
from app.core.database import get_engine
from app.core.database_router import get_db_router, init_db_router
from app.core.feature_flags import get_deployment_info
from app.core.health_collector import collect_health_metrics
from app.core.job_queue import job_queue
from app.core.metrics import smdg_version_info
from app.core.rate_limiter import check_redis_connection, redis_client
from app.core.replication_monitor import monitor_replication
from app.core.session import session_manager
from app.core.slo_collector import slo_collector
from app.core.version import APP_VERSION
from app.core.webhook import webhook_dispatcher
from app.lifecycle.webhook_scheduler import webhook_retry_scheduler
from app.services.archive_service import archive_service
from app.services.dead_letter_service import dlq

logger = logging.getLogger(__name__)

SHUTDOWN_GRACE_PERIOD_SEC: int = 30
SHUTDOWN_LOG_INTERVAL_SEC: int = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager для управления жизненным циклом приложения."""
    from app.core.circuit_breaker import set_circuit_breaker_event_loop

    set_circuit_breaker_event_loop(asyncio.get_running_loop())

    logger.info("🚀 Запуск SMDG v%s...", APP_VERSION)

    app.state.shutting_down = False
    app.state.active_requests = 0
    app.state.active_requests_lock = asyncio.Lock()
    app.state.background_tasks = []
    app.state.started_at = time.time()

    from app.core import init_keys

    try:
        await init_keys()
        logger.info("✅ Ключи шифрования инициализированы")
    except Exception as e:
        logger.exception("❌ Ошибка инициализации ключей: %s", e)
        raise

    await check_redis_connection()
    logger.info("✅ Rate limiter: Redis проверен")

    from app.core.asset_pipeline import init_asset_pipeline
    from app.services.cdn_service import init_cdn_service
    from app.templating import update_jinja_globals

    init_asset_pipeline(
        settings.static_dir_resolved,
        settings.STATIC_URL,
        cdn_url=settings.CDN_URL if settings.CDN_ENABLED else None,
        auto_generate=settings.ASSET_MANIFEST_AUTO_GENERATE,
        fingerprinting=settings.ASSET_FINGERPRINTING,
    )
    cdn_invalidation = settings.CDN_INVALIDATION_ENABLED and (
        (settings.CDN_PROVIDER == "cloudfront" and bool(settings.CLOUDFRONT_DISTRIBUTION_ID))
        or (
            settings.CDN_PROVIDER == "cloudflare"
            and bool(settings.CLOUDFLARE_ZONE_ID)
            and bool(settings.CLOUDFLARE_API_TOKEN)
        )
    )
    init_cdn_service(
        {
            "provider": settings.CDN_PROVIDER,
            "enabled": cdn_invalidation,
            "distribution_id": settings.CLOUDFRONT_DISTRIBUTION_ID,
            "domain": settings.CLOUDFLARE_DOMAIN or settings.CLOUDFRONT_DOMAIN,
            "zone_id": settings.CLOUDFLARE_ZONE_ID,
            "api_token": settings.CLOUDFLARE_API_TOKEN,
        }
    )
    app.state.jinja2_templates_ok = False
    try:
        update_jinja_globals()
        app.state.jinja2_templates_ok = True
    except (AssertionError, ImportError) as e:
        logger.error(
            "Jinja2 недоступен (%s) — «/» отдаёт static/html/index.html. "
            "В Docker: пересоберите образ; в pyproject: dependency jinja2; Dockerfile ставит jinja2 явно.",
            e,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("update_jinja_globals не выполнен: %s", e)
    if app.state.jinja2_templates_ok:
        logger.info("✅ Asset pipeline / CDN, Jinja2 готовы")
    else:
        logger.info("✅ Asset pipeline / CDN (шаблон главной: fallback static/html/index.html)")

    if settings.HORIZONTAL_SCALING_ENABLED:
        try:
            await session_manager.init()
            await distributed_cache.init()
            await job_queue.init()
            job_queue.start()
            logger.info(
                "✅ Stateless services initialized (instance_id=%s, instance_name=%s)",
                settings.INSTANCE_ID,
                settings.INSTANCE_NAME,
            )
        except Exception as e:
            logger.exception("⚠️ Stateless services init failed: %s", e)

    if settings.READ_REPLICAS_ENABLED:
        replica_urls = [value.strip() for value in settings.DB_REPLICA_URLS.split(",") if value.strip()]
        await init_db_router(
            master_url=settings.database_url,
            replica_urls=replica_urls,
            max_replica_lag_bytes=settings.READ_REPLICA_MAX_LAG_BYTES,
            health_ttl_seconds=settings.READ_REPLICA_HEALTH_TTL_SECONDS,
        )
        logger.info("✅ DB read replicas initialized: %d", len(replica_urls))

    from app.core.storage_backend import S3StorageBackend as _S3

    if isinstance(encrypted_storage, _S3):
        if settings.s3_lifecycle_enabled:
            try:
                import json

                from app.core.s3_lifecycle import S3LifecyclePolicyManager

                s3_client = await encrypted_storage._get_client()

                custom_policies = {}
                if settings.s3_lifecycle_custom_policies:
                    try:
                        custom_policies = json.loads(settings.s3_lifecycle_custom_policies)
                    except json.JSONDecodeError as e:
                        logger.warning("⚠️ Ошибка парсинга s3_lifecycle_custom_policies: %s", e)

                lifecycle_mgr = S3LifecyclePolicyManager(
                    s3_client=s3_client,
                    bucket=encrypted_storage.bucket,
                    default_ttl_days=settings.s3_lifecycle_default_ttl_days,
                    custom_policies=custom_policies if custom_policies else None,
                )

                result = await lifecycle_mgr.apply_lifecycle_rules()
                if result.get("success"):
                    logger.info("✅ S3 Lifecycle Policies применены: %d правил", result["rules_count"])
                else:
                    logger.warning("⚠️ S3 Lifecycle не применены: %s", result.get("error"))
                    await cleanup_manager.start_cleanup_task()
            except Exception as e:
                logger.exception("⚠️ Ошибка настройки S3 Lifecycle: %s", e)
                await cleanup_manager.start_cleanup_task()
        else:
            logger.info("ℹ️ S3 Lifecycle отключены (s3_lifecycle_enabled=false)")
            await cleanup_manager.start_cleanup_task()
    else:
        await cleanup_manager.start_cleanup_task()
        logger.info("✅ Авто-очистка старых файлов запущена (APScheduler, локальное хранилище)")

    from app.core.database import Base

    Base.registry.configure()
    logger.info("✅ SQLAlchemy мапперы сконфигурированы")

    await asyncio.sleep(2)
    webhook_task = asyncio.create_task(webhook_retry_scheduler(), name="webhook_retry_scheduler")
    app.state.background_tasks.append(webhook_task)
    logger.info("✅ Webhook retry scheduler запущен")

    dlq.start()
    logger.info("✅ DLQ worker запущен")

    try:
        smdg_version_info.info(
            {
                "version": APP_VERSION,
                "deployment_type": get_deployment_info().get("deployment_type", "unknown"),
                "git_sha": os.getenv("GIT_SHA", "unknown"),
            }
        )
    except Exception as _exc:  # noqa: BLE001
        logger.debug("Не удалось установить smdg_version_info: %s", _exc)
    health_task = asyncio.create_task(collect_health_metrics(), name="health_collector")
    app.state.background_tasks.append(health_task)
    logger.info("✅ Health metrics collector запущен")

    slo_task = asyncio.create_task(slo_collector.collect_slo_metrics(), name="slo_collector")
    app.state.background_tasks.append(slo_task)
    logger.info("✅ SLO metrics collector запущен")

    if settings.READ_REPLICAS_ENABLED:
        replication_task = asyncio.create_task(monitor_replication(), name="replication_monitor")
        app.state.background_tasks.append(replication_task)
        logger.info("✅ Replication monitor запущен")

    if settings.ARCHIVE_ENABLED:
        archive_service.start()
        logger.info("✅ Archive worker запущен")

    try:
        await redis_client.set("test_key_startup", "test_value", ex=60)
        value = await redis_client.get("test_key_startup")
        logger.info("Redis тестовая запись прошла: %s", value)
    except Exception as e:
        logger.warning("Ошибка тестовой записи в Redis: %s", e)

    await create_first_admin()

    register_deploy_metrics(app)

    try:
        from fastapi import HTTPException as _HTTPException

        from app.core.circuit_breaker import get_circuit_breaker as _get_cb

        _get_cb("postgresql", exclude_exceptions=(_HTTPException,))
        _get_cb("redis")
        _get_cb("s3_storage")
        _get_cb("jaeger")
        logger.info("✅ Circuit Breakers предварительно зарегистрированы")
    except Exception as _exc:
        logger.warning("Не удалось предрегистрировать Circuit Breakers: %s", _exc)

    try:
        from app.core.bulkhead import initialize_bulkheads

        initialize_bulkheads()
        logger.info("✅ Bulkheads предварительно зарегистрированы")
    except Exception as _exc:
        logger.warning("Не удалось предрегистрировать Bulkheads: %s", _exc)

    logger.info("✅ Приложение готово принимать трафик")

    yield

    logger.info("🛑 Graceful shutdown initiated...")
    app.state.shutting_down = True

    try:
        import socket as _socket

        from app.api.deploy_metrics import READINESS_GAUGE

        _replica = os.getenv("HOSTNAME") or _socket.gethostname()
        READINESS_GAUGE.labels(replica=_replica).set(0)
    except Exception as _exc:
        logger.debug("Не удалось обновить smdg_ready gauge: %s", _exc)

    await _wait_for_inflight_requests(app, timeout=SHUTDOWN_GRACE_PERIOD_SEC)

    logger.info("🛑 Отмена фоновых задач...")
    for task in app.state.background_tasks:
        if not task.done():
            task.cancel()
    if app.state.background_tasks:
        results = await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
        for task, result in zip(app.state.background_tasks, results):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.warning("⚠️ Фоновая задача %s завершилась с ошибкой: %s", task.get_name(), result)

    try:
        await dlq.stop()
        logger.info("🔒 DLQ worker остановлен")
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки DLQ worker: %s", e)

    try:
        await cleanup_manager.stop_cleanup_task()
        logger.info("🔒 APScheduler cleanup остановлен")
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки cleanup: %s", e)

    try:
        await webhook_dispatcher.close()
        logger.info("🔒 Webhook dispatcher закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия webhook dispatcher: %s", e)

    try:
        from app.services.telegram_alerter import get_telegram_alerter

        await get_telegram_alerter().close()
        logger.info("🔒 Telegram alerter закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия Telegram alerter: %s", e)

    try:
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass
        logger.info("🔒 Аудит-логи сброшены на диск")
    except Exception as e:
        logger.warning("⚠️ Ошибка flush аудит-логов: %s", e)

    try:
        await redis_client.close()
        logger.info("🔒 Redis connection закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия Redis: %s", e)

    try:
        await job_queue.close()
        await distributed_cache.close()
        await session_manager.close()
        logger.info("🔒 Stateless shared services закрыты")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия stateless services: %s", e)

    from app.core import cleanup_storage

    try:
        await cleanup_storage()
        logger.info("🔒 Storage backend закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия storage: %s", e)

    try:
        await get_engine().dispose()
        logger.info("🔒 PostgreSQL connection pool закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия PostgreSQL: %s", e)

    try:
        router_obj = get_db_router()
        if router_obj is not None:
            await router_obj.dispose()
            logger.info("🔒 Read-replica router закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия replica router: %s", e)

    try:
        if settings.ARCHIVE_ENABLED:
            await archive_service.stop()
            logger.info("🔒 Archive worker остановлен")
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки archive worker: %s", e)

    from app.core.tracing import shutdown_tracing

    try:
        await shutdown_tracing()
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки tracing: %s", e)

    logger.info("✅ Graceful shutdown complete")


async def _wait_for_inflight_requests(app: FastAPI, timeout: int) -> None:
    lock: asyncio.Lock = app.state.active_requests_lock
    async with lock:
        active = app.state.active_requests

    if active <= 0:
        logger.info("✅ Нет активных запросов — сразу переходим к закрытию соединений")
        return

    logger.info("⏳ Ожидаем завершения %d in-flight запросов (таймаут: %ds)", active, timeout)

    remaining = timeout
    while remaining > 0:
        await asyncio.sleep(1)
        async with lock:
            active = app.state.active_requests
        if active <= 0:
            logger.info("✅ Все in-flight запросы завершены")
            return
        remaining -= 1
        if remaining % SHUTDOWN_LOG_INTERVAL_SEC == 0:
            logger.info("⏳ Ещё %d активных запросов, осталось %ds...", active, remaining)

    logger.warning(
        "⚠️ Таймаут graceful shutdown: %d запросов не успели завершиться за %ds, прерываем",
        active,
        timeout,
    )
