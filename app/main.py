# app/main.py
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, HTTPException
from typing import Annotated, Optional
from prometheus_fastapi_instrumentator import Instrumentator
from limits.typing import RedisClient
from app.core.auth import get_current_user, TokenData
from app.core.config import settings
from app.core.feature_flags import get_deployment_info
from app.core.rate_limiter import limiter, check_redis_connection, redis_client
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler, Limiter
from slowapi.util import get_remote_address
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from app.api import upload, download, list, delete, cleanup, stats, webhooks, dicom, test, bulkhead, archive
from app.core import init_keys, file_storage, cleanup_manager, audit_logger
from app.core import encrypted_storage, cleanup_storage
from app.core.webhook import webhook_dispatcher
from app.core.auth import get_current_user
from app.core.auth_utils import TokenData
from app.core.database import engine, AsyncSessionLocal, Base, get_engine
from app.models import User, File, FileLink, WebhookSubscription, WebhookDelivery, Tenant
from app.core.security import get_password_hash, verify_password
from app.core.tenant import resolve_tenant_from_request

from app.core.middleware import (
    AuditMiddleware,
    ActiveRequestsMiddleware,
    BulkheadMiddleware,
    CompressionMiddleware,
    TracingMiddleware,
    SLOMiddleware,
    TimeoutMiddleware,
)
from app.core.slo_collector import slo_collector
from app.core.tracing import setup_tracing, shutdown_tracing
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_audit_export import router as admin_audit_export_router
from app.api.delete_user import router as delete_user_router
from app.api.deploy_metrics import register_deploy_metrics
from app.api.tracing import router as tracing_router
from app.api.alert_webhook import router as alert_webhook_router
from app.api.slo import router as slo_router
from app.api.circuit_breaker import router as circuit_breaker_router
from app.api.dead_letter import router as dead_letter_router
from app.core.health_collector import collect_health_metrics
from app.core.database_router import init_db_router, get_db_router
from app.core.replication_monitor import monitor_replication
from app.services.archive_service import archive_service
from app.core.log_utils import ThrottledErrorLogger
from app.core.metrics import smdg_version_info
from app.core.timeout import TimeoutError
from app.core.bulkhead import BulkheadRejectedError, BulkheadTimeoutError, initialize_bulkheads
from app.core.session import session_manager
from app.core.cache import distributed_cache
from app.core.job_queue import job_queue
from app.services.dead_letter_service import dlq
from app.services import email_service as _email_service  # noqa: F401
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core import cleanup_manager
import asyncio
import logging
import os
import signal
import time

from app.models.webhook import DeliveryStatus, WebhookDelivery


# ──────────────────────────────────────────────────────────────────────
# Logging configuration
# ──────────────────────────────────────────────────────────────────────
# Python по умолчанию использует уровень WARNING для root-логгера, поэтому
# все ``logger.info(...)`` из ``app.*`` молча проглатываются. Это приводит
# к тому, что в ``docker compose logs`` видны только ``print()`` и строки
# от Uvicorn, а сообщения о старте tracing/ключей/Redis теряются.
#
# Uvicorn не настраивает root-логгер сам (он настраивает только свои
# ``uvicorn``/``uvicorn.access``), поэтому делаем это однократно здесь,
# до первого ``logger.info`` в этом модуле. Уровень управляется переменной
# окружения ``LOG_LEVEL`` (по умолчанию INFO).
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Шумные сторонние логгеры режем до WARNING, чтобы не забивать поток.
for _noisy in ("botocore", "aiobotocore", "urllib3", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Graceful shutdown: константы
# ──────────────────────────────────────────────────────────────────────

# Сколько секунд ждать завершения in-flight запросов при получении SIGTERM.
# Должно быть < ``stop_grace_period`` в docker-compose.yml (там 60s).
SHUTDOWN_GRACE_PERIOD_SEC: int = 30

# Периодичность логирования прогресса ожидания in-flight запросов.
SHUTDOWN_LOG_INTERVAL_SEC: int = 5


async def webhook_retry_scheduler():
    """Фоновая задача для повторной отправки неудачных webhook доставок.

    Логирование throttled через ``ThrottledErrorLogger`` (см.
    ``app/core/log_utils.py``): первый фейл — WARNING, повторы той же
    сигнатуры — DEBUG, каждые ~5 мин — напоминание в WARNING, при
    восстановлении — INFO. Это не даёт шедулеру затопить лог при
    длительной деградации (БД остановлена, DNS не резолвится и т.п.).

    Backoff на sleep: при штатной работе ``BASE_SLEEP``, при длительных
    сбоях растёт до ``MAX_SLEEP`` — чтобы не долбить разрушенную
    зависимость каждые 10 секунд.
    """
    from sqlalchemy import select, exc
    from datetime import datetime, timezone

    # Ждём чтобы миграции успели примениться
    await asyncio.sleep(5)

    # Backoff для sleep между итерациями.
    BASE_SLEEP: int = 10
    MAX_SLEEP: int = 60
    # Напоминание раз в 30 итераций ≈ каждые 5 минут при BASE_SLEEP=10.
    throttled = ThrottledErrorLogger(logger=logger, remind_every=30)
    # Ключ для throttled-логгера — разные типы ошибок (DB vs всё остальное)
    # пишем под одним логическим именем, чтобы recovery-сообщение было одно.
    LOG_KEY = "webhook_retry"

    while True:
        try:
            async with AsyncSessionLocal() as db:
                # Находим доставки готовые к retry
                stmt = (
                    select(WebhookDelivery)
                    .where(
                        WebhookDelivery.status == DeliveryStatus.RETRYING.value,
                        WebhookDelivery.next_retry_at <= datetime.now(timezone.utc),
                        WebhookDelivery.attempts < WebhookDelivery.max_attempts,
                    )
                    .limit(50)
                )
                result = await db.execute(stmt)
                pending_retries = result.scalars().all()

                for delivery in pending_retries:
                    # Повторяем отправку через dispatcher
                    from app.models.webhook import WebhookSubscription

                    sub_stmt = select(WebhookSubscription).where(
                        WebhookSubscription.id == delivery.subscription_id
                    )
                    sub_result = await db.execute(sub_stmt)
                    subscription = sub_result.scalar_one_or_none()

                    if subscription and subscription.is_active:
                        await webhook_dispatcher._send_with_retry(
                            subscription=subscription,
                            payload_json=delivery.payload,
                            db=db
                        )

                await db.commit()

            throttled.recovered(
                LOG_KEY,
                message="✅ %s recovered after %d failed attempts",
            )
            await asyncio.sleep(BASE_SLEEP)

        except asyncio.CancelledError:
            # Корректное завершение при shutdown — пробрасываем наверх.
            raise
        except (exc.ProgrammingError, exc.OperationalError) as e:
            # Ожидаемая деградация: миграции ещё не применены / БД легла /
            # connection pool умер. Throttled-логгер не даст спамить.
            throttled.failure(LOG_KEY, e, message="%s failed: %s")
            failures = throttled.failures(LOG_KEY)
            await asyncio.sleep(min(BASE_SLEEP * max(1, failures // 10), MAX_SLEEP))
        except Exception as e:
            # Неожиданная ошибка — первый раз пишем traceback, дальше тоже
            # throttled. Используем тот же ключ, чтобы recovery был один.
            throttled.failure(
                LOG_KEY,
                e,
                message="%s unexpected error: %s",
                include_traceback_on_new=True,
            )
            failures = throttled.failures(LOG_KEY)
            await asyncio.sleep(min(BASE_SLEEP * max(1, failures // 10), MAX_SLEEP))

        await asyncio.sleep(30)  # Проверка каждые 30 секунд


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager для управления жизненным циклом приложения.

    Startup:
        - Инициализация state для graceful shutdown
        - Ключи шифрования, Redis, SQLAlchemy мапперы, S3 lifecycle
        - Запуск фоновых задач (cleanup, webhook retry)

    Shutdown (SIGTERM/SIGINT):
        1. ``app.state.shutting_down = True`` → middleware возвращает 503
        2. Ожидание завершения in-flight запросов (таймаут 30с)
        3. Отмена фоновых задач (webhook retry)
        4. Остановка APScheduler cleanup
        5. Сброс аудит-логов на диск
        6. Закрытие соединений: Redis, S3, PostgreSQL
    """
    # ──────────────────────────────────────────────────────────────
    # Startup
    # ──────────────────────────────────────────────────────────────
    # Event loop для ``schedule_dependency_failure`` / ``schedule_batch_worker_success``
    # (OTLP export из worker-потока OpenTelemetry → async Circuit Breaker).
    from app.core.circuit_breaker import set_circuit_breaker_event_loop

    set_circuit_breaker_event_loop(asyncio.get_running_loop())

    logger.info("🚀 Запуск SMDG v%s...", _APP_VERSION)

    # Graceful shutdown state (используется ActiveRequestsMiddleware и /health/ready)
    app.state.shutting_down = False
    app.state.active_requests = 0
    app.state.active_requests_lock = asyncio.Lock()
    app.state.background_tasks: list[asyncio.Task] = []
    app.state.started_at = time.time()

    try:
        await init_keys()
        logger.info("✅ Ключи шифрования инициализированы")
    except Exception as e:
        logger.exception("❌ Ошибка инициализации ключей: %s", e)

    await check_redis_connection()
    logger.info("✅ Rate limiter: Redis проверен")

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
        replica_urls = [
            value.strip() for value in settings.DB_REPLICA_URLS.split(",") if value.strip()
        ]
        await init_db_router(
            master_url=settings.database_url,
            replica_urls=replica_urls,
            max_replica_lag_bytes=settings.READ_REPLICA_MAX_LAG_BYTES,
            health_ttl_seconds=settings.READ_REPLICA_HEALTH_TTL_SECONDS,
        )
        logger.info("✅ DB read replicas initialized: %d", len(replica_urls))

    # NB: ``setup_tracing`` намеренно НЕ вызывается здесь. FastAPIInstrumentor
    # дергает ``app.add_middleware`` под капотом, а Starlette замораживает
    # middleware-стек до первого вызова lifespan. Поэтому инициализация
    # tracing выполняется на модульном уровне (см. ниже сразу после создания
    # FastAPI-приложения), а в lifespan мы делаем только shutdown.

    # S3 Lifecycle Policies — применяем при использовании S3
    from app.core.storage_backend import S3StorageBackend
    if isinstance(encrypted_storage, S3StorageBackend):
        if settings.s3_lifecycle_enabled:
            try:
                from app.core.s3_lifecycle import S3LifecyclePolicyManager
                import json

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

    Base.registry.configure()
    logger.info("✅ SQLAlchemy мапперы сконфигурированы")

    # Webhook retry scheduler — запускаем с задержкой, чтобы миграции успели примениться.
    await asyncio.sleep(2)
    webhook_task = asyncio.create_task(
        webhook_retry_scheduler(), name="webhook_retry_scheduler"
    )
    app.state.background_tasks.append(webhook_task)
    logger.info("✅ Webhook retry scheduler запущен")

    # DLQ worker
    dlq.start()
    logger.info("✅ DLQ worker запущен")

    # Health collector — фоновый сбор метрик для алертинга. Обновляет
    # smdg_*_up gauges и бизнес-метрики. Работает полностью изолированно:
    # падение здесь не повлияет на hot-path обработки запросов.
    try:
        smdg_version_info.info({
            "version": _APP_VERSION,
            "deployment_type": get_deployment_info().get("deployment_type", "unknown"),
            "git_sha": os.getenv("GIT_SHA", "unknown"),
        })
    except Exception as _exc:  # noqa: BLE001
        logger.debug("Не удалось установить smdg_version_info: %s", _exc)
    health_task = asyncio.create_task(
        collect_health_metrics(), name="health_collector"
    )
    app.state.background_tasks.append(health_task)
    logger.info("✅ Health metrics collector запущен")

    # SLO collector — отдельная задача, рассчитывает compliance/error budget
    # раз в минуту. Работает независимо от health_collector, чтобы падение
    # одного не останавливало другой. См. ``app/core/slo_collector.py``.
    slo_task = asyncio.create_task(
        slo_collector.collect_slo_metrics(), name="slo_collector"
    )
    app.state.background_tasks.append(slo_task)
    logger.info("✅ SLO metrics collector запущен")

    if settings.READ_REPLICAS_ENABLED:
        replication_task = asyncio.create_task(
            monitor_replication(), name="replication_monitor"
        )
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

    # Предварительно регистрируем известные Circuit Breaker'ы, чтобы
    # /api/circuit-breaker/status и Prometheus показывали их ДО первого
    # реального вызова. Значения берутся из settings.*
    try:
        from app.core.circuit_breaker import get_circuit_breaker as _get_cb
        from fastapi import HTTPException as _HTTPException

        _get_cb("postgresql", exclude_exceptions=(_HTTPException,))
        _get_cb("redis")
        _get_cb("clamav")
        _get_cb("s3_storage")
        _get_cb("jaeger")
        logger.info("✅ Circuit Breakers предварительно зарегистрированы")
    except Exception as _exc:  # pragma: no cover — не критично для старта
        logger.warning("Не удалось предрегистрировать Circuit Breakers: %s", _exc)

    try:
        initialize_bulkheads()
        logger.info("✅ Bulkheads предварительно зарегистрированы")
    except Exception as _exc:  # pragma: no cover — не критично для старта
        logger.warning("Не удалось предрегистрировать Bulkheads: %s", _exc)

    logger.info("✅ Приложение готово принимать трафик")

    # ──────────────────────────────────────────────────────────────
    # Runtime
    # ──────────────────────────────────────────────────────────────
    yield

    # ──────────────────────────────────────────────────────────────
    # Graceful shutdown
    # ──────────────────────────────────────────────────────────────
    logger.info("🛑 Graceful shutdown initiated...")
    app.state.shutting_down = True

    try:
        import socket as _socket
        from app.api.deploy_metrics import READINESS_GAUGE
        _replica = os.getenv("HOSTNAME") or _socket.gethostname()
        READINESS_GAUGE.labels(replica=_replica).set(0)
    except Exception as _exc:
        logger.debug("Не удалось обновить smdg_ready gauge: %s", _exc)

    # Шаг 1: дождаться завершения in-flight запросов (новые уже получают 503).
    await _wait_for_inflight_requests(app, timeout=SHUTDOWN_GRACE_PERIOD_SEC)

    # Шаг 2: отмена фоновых задач.
    logger.info("🛑 Отмена фоновых задач...")
    for task in app.state.background_tasks:
        if not task.done():
            task.cancel()
    # Ждём завершения задач, игнорируя CancelledError.
    if app.state.background_tasks:
        results = await asyncio.gather(
            *app.state.background_tasks, return_exceptions=True
        )
        for task, result in zip(app.state.background_tasks, results):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.warning("⚠️ Фоновая задача %s завершилась с ошибкой: %s", task.get_name(), result)

    # Шаг 3: APScheduler cleanup.
    try:
        await dlq.stop()
        logger.info("🔒 DLQ worker остановлен")
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки DLQ worker: %s", e)

    # Шаг 3: APScheduler cleanup.
    try:
        await cleanup_manager.stop_cleanup_task()
        logger.info("🔒 APScheduler cleanup остановлен")
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки cleanup: %s", e)

    # Шаг 4: webhook dispatcher (aiohttp session).
    try:
        await webhook_dispatcher.close()
        logger.info("🔒 Webhook dispatcher закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия webhook dispatcher: %s", e)

    # Шаг 4a: Telegram alerter (httpx client).
    try:
        from app.services.telegram_alerter import get_telegram_alerter
        await get_telegram_alerter().close()
        logger.info("🔒 Telegram alerter закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия Telegram alerter: %s", e)

    # Шаг 5: сброс аудит-логов на диск (AuditLogger работает синхронно,
    # но принудительный flush защищает от потери последних записей).
    try:
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass
        logger.info("🔒 Аудит-логи сброшены на диск")
    except Exception as e:
        logger.warning("⚠️ Ошибка flush аудит-логов: %s", e)

    # Шаг 6: закрытие Redis.
    try:
        await redis_client.close()
        logger.info("🔒 Redis connection закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия Redis: %s", e)

    # Шаг 6a: закрытие stateless shared services (sessions/cache/job queue).
    try:
        await job_queue.close()
        await distributed_cache.close()
        await session_manager.close()
        logger.info("🔒 Stateless shared services закрыты")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия stateless services: %s", e)

    # Шаг 7: закрытие S3 клиента (если используется).
    try:
        await cleanup_storage()
        logger.info("🔒 Storage backend закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия storage: %s", e)

    # Шаг 8: закрытие пула соединений PostgreSQL.
    try:
        await get_engine().dispose()
        logger.info("🔒 PostgreSQL connection pool закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия PostgreSQL: %s", e)

    # Шаг 8a: закрытие роутера реплик.
    try:
        router_obj = get_db_router()
        if router_obj is not None:
            await router_obj.dispose()
            logger.info("🔒 Read-replica router закрыт")
    except Exception as e:
        logger.warning("⚠️ Ошибка закрытия replica router: %s", e)

    # Шаг 8b: остановка архивного воркера.
    try:
        if settings.ARCHIVE_ENABLED:
            await archive_service.stop()
            logger.info("🔒 Archive worker остановлен")
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки archive worker: %s", e)

    # Шаг 9: сброс буфера трассировки + остановка tracer provider.
    # Делаем в самом конце, чтобы захватить спаны всех предыдущих шагов.
    try:
        await shutdown_tracing()
    except Exception as e:
        logger.warning("⚠️ Ошибка остановки tracing: %s", e)

    logger.info("✅ Graceful shutdown complete")


async def _wait_for_inflight_requests(app: FastAPI, timeout: int) -> None:
    """Ожидание завершения активных HTTP-запросов с таймаутом.

    Активные запросы учитываются через :class:`ActiveRequestsMiddleware`.
    Если по истечении ``timeout`` остались незавершённые запросы —
    они будут прерваны при закрытии uvicorn worker'ом.
    """
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
        active, timeout,
    )

# Создаём приложение с lifespan
app = FastAPI(
    title="SMDG",
    version="1.0",
    lifespan=lifespan,  
    docs_url="/docs",        
    redoc_url="/redoc",      
    openapi_url="/openapi.json"
)

# ────────────────────────────────────────────────────────────────
# OpenTelemetry tracing — инициализация ДО любых ``add_middleware``.
#
# ``FastAPIInstrumentor.instrument_app()`` регистрирует собственную
# ``OpenTelemetryMiddleware`` через ``app.add_middleware()``. Starlette
# собирает middleware-стек один раз (при первом ASGI-вызове, в т.ч. при
# lifespan.startup) и после этого ``add_middleware`` бросает
# ``RuntimeError: Cannot add middleware after an application has started``.
# Поэтому trace-инициализация строго здесь — между созданием ``FastAPI`` и
# первым ``app.add_middleware``. При OTEL_ENABLED != "true" setup_tracing
# сразу возвращает None (fail-open, никаких соединений).
# ────────────────────────────────────────────────────────────────
try:
    setup_tracing(app, service_name=os.getenv("OTEL_SERVICE_NAME", "smdg"))
except Exception as _tracing_exc:  # pragma: no cover - защита от неожиданных ошибок
    logger.warning("⚠️ Не удалось инициализировать tracing: %s", _tracing_exc)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# ────────────────────────────────────────────────────────────────
# CORS - разрешаем запросы с фронта
# ────────────────────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

# Разрешённые origins (добавляй свои реальные домены в продакшене!)
origins = [
    "http://localhost",
    "http://localhost:3000",     # React/Vue dev
    "http://localhost:5173",     # Vite
    "http://localhost:8080",     # другой dev фронт
    "https://fileguardian.com.ru",  # твой домен из .env
    "https://viewer.ohif.org",   # OHIF Viewer CDN
    "https://*.ohif.org",        # OHIF subdomains
    "*"                          # временно для теста (удали в прод!)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,          # если используешь куки/auth headers
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE", "PATCH"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-Tenant-ID",
        "X-Tenant-Subdomain",
    ],
    expose_headers=["X-Total-Count"],  # если возвращаешь пагинацию/кастом headers
    max_age=86400,                   # кэш preflight на сутки
)


# ────────────────────────────────────────────────────────────────
# Middleware: добавляем пользователя в scope (должен быть ПЕРВЫМ!)
# ────────────────────────────────────────────────────────────────


# Самый первый middleware
@app.middleware("http")
async def set_user_context(request: Request, call_next):
    user = None
    tenant = None

    token = request.cookies.get("access_token")
    if not token:
        auth_hdr = request.headers.get("authorization") or ""
        if auth_hdr.lower().startswith("bearer "):
            token = auth_hdr[7:].strip()

    jwt_tenant_id = None
    jwt_role = None
    if token:
        try:
            from jwt import decode

            payload = decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"verify_exp": False},
            )
            jwt_tenant_id = payload.get("tenant_id")
            jwt_role = payload.get("role", "user")
            sub = payload.get("sub")
            if sub:
                user = TokenData(sub=sub, role=jwt_role, tenant_id=jwt_tenant_id)
        except Exception as e:
            logger.debug(f"Middleware: JWT decode → user=None ({e})")

    try:
        async with AsyncSessionLocal() as db:
            tenant = await resolve_tenant_from_request(
                db,
                request,
                jwt_tenant_id=jwt_tenant_id,
                jwt_role=jwt_role,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"Middleware: tenant resolution → tenant=None ({e})")

    request.scope["user"] = user
    request.scope["tenant"] = tenant
    request.scope["tenant_id"] = tenant.id if tenant else None
    request.state.tenant = tenant
    request.state.tenant_id = tenant.id if tenant else None
    response = await call_next(request)
    return response


app.add_middleware(SlowAPIMiddleware)
app.add_middleware(AuditMiddleware)
if settings.COMPRESSION_ENABLED:
    app.add_middleware(
        CompressionMiddleware,
        minimum_size=settings.COMPRESSION_MIN_SIZE_BYTES,
        compressible_types=settings.COMPRESSIBLE_CONTENT_TYPES,
        gzip_enabled=settings.COMPRESSION_GZIP_ENABLED,
        brotli_enabled=settings.COMPRESSION_BROTLI_ENABLED,
        gzip_level=settings.COMPRESSION_GZIP_LEVEL,
        brotli_quality=settings.COMPRESSION_BROTLI_QUALITY,
    )
    logger.info(
        "Compression middleware enabled (gzip=%s, brotli=%s)",
        settings.COMPRESSION_GZIP_ENABLED,
        settings.COMPRESSION_BROTLI_ENABLED,
    )

# SLOMiddleware: считает SLI-метрики (success/total requests, latency)
# для SLO-расчётов. Стоит ниже ActiveRequestsMiddleware — так запросы,
# которые были отклонены 503-м во время shutdown, не попадают в
# availability-статистику (это намеренный graceful shutdown, не отказ).
app.add_middleware(SLOMiddleware)

# TracingMiddleware добавляет в ответы заголовок ``X-Trace-Id`` — операторам
# достаточно ``curl -I`` чтобы получить идентификатор трассы в Jaeger.
# Регистрируется ПОСЛЕ аудита/SlowAPI, но ДО ActiveRequestsMiddleware —
# порядок в Starlette таков, что следующий add_middleware становится более
# внешним слоем. ActiveRequestsMiddleware должен оставаться самым внешним,
# а TracingMiddleware работает внутри серверного span от FastAPIInstrumentor.
app.add_middleware(TracingMiddleware)
app.add_middleware(TimeoutMiddleware)
app.add_middleware(BulkheadMiddleware)

# ────────────────────────────────────────────────────────────────
# Graceful shutdown: отслеживание активных запросов
# ────────────────────────────────────────────────────────────────
# В Starlette последний добавленный middleware становится САМЫМ ВНЕШНИМ
# слоем. ActiveRequestsMiddleware должен быть именно таким, чтобы:
#   1) подсчитывать абсолютно все in-flight HTTP-запросы;
#   2) отклонять новые запросы (503) ДО выполнения любой другой логики,
#      включая авторизацию, rate limiting и аудит.
app.add_middleware(ActiveRequestsMiddleware, fastapi_app=app)

# Rate limiter с логами
def custom_key_func(request: Request) -> str:
    # Логируем на DEBUG, т.к. функция вызывается на КАЖДЫЙ HTTP-запрос
    # (включая healthcheck'и от docker/nginx и /metrics от Prometheus).
    # На INFO это создавало шум в несколько строк/сек и затирало полезные
    # события в stdout. Для отладки rate-limit'а достаточно поднять уровень
    # логгера точечно: LOG_LEVEL=DEBUG или logger.setLevel(DEBUG) в REPL.
    user = request.scope.get("user")
    if user and hasattr(user, "sub"):
        key = f"rate_limit:user:{user.sub}"
        logger.debug("Rate limit: пользователь %s → ключ %s", user.sub, key)
        return key

    ip = get_remote_address(request)
    key = f"rate_limit:ip:{ip}"
    logger.debug("Rate limit: аноним → ключ %s", key)
    return key

limiter = Limiter(
    key_func=custom_key_func,
    storage_uri=settings.redis_url or "redis://redis:6379/0",
    default_limits=["100/minute"]
)

app.state.limiter = limiter

# Обработчик 429

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Слишком много попыток. Попробуйте позже (лимит: 5 попыток в минуту)"
        },
        headers={"Retry-After": "60"}
    )


@app.exception_handler(TimeoutError)
async def timeout_exception_handler(request: Request, exc: TimeoutError):
    return JSONResponse(status_code=504, content={"detail": str(exc)})


@app.exception_handler(BulkheadRejectedError)
async def bulkhead_rejected_exception_handler(request: Request, exc: BulkheadRejectedError):
    return JSONResponse(
        status_code=429,
        content={"detail": str(exc)},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(BulkheadTimeoutError)
async def bulkhead_timeout_exception_handler(request: Request, exc: BulkheadTimeoutError):
    return JSONResponse(status_code=504, content={"detail": str(exc)})


# Монтирование статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

# Подключаем API
app.include_router(upload.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(list.router, prefix="/api")
app.include_router(delete.router, prefix="/api")
app.include_router(cleanup.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(admin_audit_export_router, prefix="/api")
app.include_router(delete_user_router, prefix="/api")
app.include_router(dicom.router, prefix="/api")
app.include_router(test.router, prefix="/api")
app.include_router(tracing_router)
app.include_router(health_router)
app.include_router(alert_webhook_router)
app.include_router(slo_router)
app.include_router(circuit_breaker_router)
app.include_router(dead_letter_router)
app.include_router(bulkhead.router)
app.include_router(archive.router)

# Можно вынести в отдельный модуль app/core/initial_data.py
async def ensure_admin_exists(session: AsyncSession):
    result = await session.execute(
        select(User).where(User.username == "admin")
    )
    admin = result.scalar_one_or_none()

    if not admin:
        print("⚡ Создаём первого администратора...")
        admin = User(
            username="admin",
            hashed_password=get_password_hash("ChangeMe123!"),  # ← сразу меняй!
            role="admin",
            is_active=True
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        print("✅ Админ создан. Логин: admin | Пароль: ChangeMe123! (измените немедленно!)")
    else:
        # Проверяем, валиден ли хэш
        if not admin.hashed_password.startswith("$argon2"):
            print("⚠️  Обнаружен НЕВАЛИДНЫЙ хэш пароля у admin!")
            print("   Текущее значение:", repr(admin.hashed_password[:50]))
            print("   Автоматически перехэшируем...")
            admin.hashed_password = get_password_hash("ChangeMe123!")  # ← или генерировать случайный
            await session.commit()
            print("✅ Хэш пароля исправлен (argon2)")



async def create_first_admin():
    """Создаёт первого администратора, если его ещё нет (только в dev-режиме)"""
    if not settings.dev_mode:
        print("👀 Production-режим: пропускаем создание тестового админа")
        return

    async with AsyncSessionLocal() as db:
        tenant_result = await db.execute(select(Tenant).where(Tenant.subdomain == "default"))
        default_tenant = tenant_result.scalar_one_or_none()
        if not default_tenant:
            default_tenant = Tenant(name="Default Tenant", subdomain="default", settings={})
            db.add(default_tenant)
            await db.commit()
            await db.refresh(default_tenant)

        result = await db.execute(
            select(User).where(User.username == "admin")
        )
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            print("ℹ️  Пользователь admin уже существует")
            changed = False
            if not existing_admin.email:
                existing_admin.email = "admin@example.com"
                changed = True
            if not existing_admin.tenant_id:
                existing_admin.tenant_id = default_tenant.id
                changed = True
            if changed:
                await db.commit()
                print("✅ Tenant/email добавлены существующему admin")
            return

        # Создаём первого админа с email
        admin = User(
            username="admin",
            email="admin@example.com",  # ← ОБЯЗАТЕЛЬНО
            hashed_password=get_password_hash("admin123"),
            role="admin",
            is_active=True,
            tenant_id=default_tenant.id,
        )
        db.add(admin)
        await db.commit()

        print("=" * 60)
        print("🔐 СОЗДАН ПЕРВЫЙ АДМИНИСТРАТОР")
        print("   Логин:    admin")
        print("   Пароль:   admin")
        print("   Email:    admin@example.com")
        print("   Роль:     admin")
        print("=" * 60)



# Главная страница
@app.get("/", response_class=HTMLResponse)
async def index():
    """Главная страница"""
    try:
        with open("static/html/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <body>
                <h1>SMDG - Secure Medical Data Gateway</h1>
                <p>Ошибка: не найден файл index.html</p>
                <p>Проверьте структуру проекта: static/html/index.html</p>
            </body>
        </html>
        """

# Панель администратора
@app.get("/admin", response_class=HTMLResponse)
async def admin():
    """Панель администратора"""
    try:
        with open("static/html/admin.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <body>
                <h1>Панель администратора SMDG</h1>
                <p>Ошибка: не найден файл admin.html</p>
            </body>
        </html>
        """

# Проверка здоровья
@app.get("/health")
async def health_check():
    """Проверка работоспособности системы"""
    dep = get_deployment_info()
    return {
        "status": "healthy",
        "service": "smdg",
        "version": "3.1.0",
        "deployment_type": dep["deployment_type"],
        "features": {
            "encryption": True,
            "cleanup": True,
            "audit_logging": True,
            "api": True,
            "web_interface": True,
            "static_files": True,
            "dicom_viewer": settings.dicom_viewer_enabled,
        },
        "directories": {
            "static": os.path.exists("static"),
            "encrypted": os.path.exists("encrypted"),
            "keys": os.path.exists("keys"),
            "audit_logs": os.path.exists("audit_logs")
        }
    }


def _serve_static_html(html_path: str, missing_title: str) -> HTMLResponse:
    """Отдать HTML-файл из static/ с no-cache заголовками.

    Args:
        html_path: Путь к файлу относительно корня проекта.
        missing_title: Заголовок (используется как тело), если файл не найден.
    """
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        response = HTMLResponse(content=content)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except FileNotFoundError:
        return HTMLResponse(
            status_code=500,
            content=f"<h1>{missing_title}</h1>",
        )


# Страница DICOM Viewer
@app.get("/dicom-viewer", response_class=HTMLResponse)
@app.get("/dicom-viewer/", response_class=HTMLResponse)
async def dicom_viewer_page():
    """Страница DICOM Viewer (OHIF Viewer обёртка)."""
    return _serve_static_html(
        "static/html/dicom-viewer.html", "DICOM Viewer не найден"
    )


# Страница OHIF Viewer
@app.get("/ohif-viewer", response_class=HTMLResponse)
@app.get("/ohif-viewer/", response_class=HTMLResponse)
async def ohif_viewer_page():
    """Страница OHIF-style Viewer."""
    return _serve_static_html(
        "static/html/ohif-viewer.html", "OHIF Viewer не найден"
    )


# Страница для просмотра логов (опционально)
@app.get("/logs")
async def view_logs():
    """Просмотр логов аудита"""
    try:
        log_files = []
        if os.path.exists("audit_logs"):
            for file in os.listdir("audit_logs"):
                if file.endswith(".log"):
                    log_files.append(file)
        
        html = """
        <html>
        <head><title>SMDG - Логи аудита</title></head>
        <body>
            <h1>📝 Логи аудита SMDG</h1>
            <a href="/">← На главную</a>
            <h2>Доступные логи:</h2>
            <ul>
        """
        
        for log_file in sorted(log_files, reverse=True):
            html += f'<li><a href="/static/audit_logs/{log_file}" target="_blank">{log_file}</a></li>'
        
        html += """
            </ul>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Ошибка</h1><p>{str(e)}</p>")
    



@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users():
    """Страница управления пользователями"""
    try:
        with open("static/html/admin_users.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <body>
                <h1>Управление пользователями</h1>
                <p>Ошибка: не найден файл admin_users.html</p>
            </body>
        </html>
        """


@app.get("/admin/dlq", response_class=HTMLResponse)
async def admin_dlq():
    """Страница управления DLQ."""
    try:
        with open("static/html/admin_dlq.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <body>
                <h1>Управление DLQ</h1>
                <p>Ошибка: не найден файл admin_dlq.html</p>
            </body>
        </html>
        """
    
@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):
    response = await call_next(request)
    # Можно добавить заголовки X-RateLimit-*
    return response

@app.get("/api/whoami")
async def whoami(current_user: Annotated[TokenData, Depends(get_current_user)]):
    return {
        "sub": current_user.sub,
        "role": current_user.role,
        "token_valid": True  # nosec b105
    }


# ────────────────────────────────────────────────────────────────
# Localised OpenAPI specifications
#
# The canonical schema lives at ``/openapi.json`` and is always in
# English (source of truth).  The endpoints below expose translated
# copies of the ``title`` / ``description`` metadata so that API
# consumers can load a Swagger UI in their language of choice.  Path
# descriptions, field names and error messages remain English by
# design — clients translate them on the client side.
# ────────────────────────────────────────────────────────────────

_OPENAPI_LOCALES: dict[str, dict[str, str]] = {
    "ru": {
        "title": "SMDG API (Русская документация)",
        "description": (
            "API для безопасного обмена медицинскими файлами.\n\n"
            "Возможности:\n"
            "- Сквозное шифрование (age)\n"
            "- Временные одноразовые ссылки\n"
            "- Двухфакторная аутентификация (TOTP)\n"
            "- Полный аудит действий\n"
            "- DICOM Viewer с измерениями\n"
            "- Экспорт аудита в Excel/PDF/CSV"
        ),
    },
    "de": {
        "title": "SMDG API (Deutsche Dokumentation)",
        "description": (
            "API für den sicheren Austausch medizinischer Dateien.\n\n"
            "Funktionen:\n"
            "- Ende-zu-Ende-Verschlüsselung (age)\n"
            "- Temporäre Einmal-Links\n"
            "- Zwei-Faktor-Authentifizierung (TOTP)\n"
            "- Vollständiges Audit aller Aktionen\n"
            "- DICOM-Viewer mit Messungen\n"
            "- Audit-Export in Excel/PDF/CSV"
        ),
    },
    "fr": {
        "title": "SMDG API (Documentation française)",
        "description": (
            "API pour l'échange sécurisé de fichiers médicaux.\n\n"
            "Fonctionnalités :\n"
            "- Chiffrement de bout en bout (age)\n"
            "- Liens temporaires à usage unique\n"
            "- Authentification à deux facteurs (TOTP)\n"
            "- Audit complet des actions\n"
            "- Visualiseur DICOM avec mesures\n"
            "- Export d'audit en Excel/PDF/CSV"
        ),
    },
}

_APP_VERSION = "4.0.0"


def _build_localised_openapi(lang: str) -> dict:
    """Return the OpenAPI schema with localised ``info`` metadata.

    The rest of the schema (paths, components, security) is reused as-is
    from the canonical English specification because endpoint-level
    descriptions are kept in English per the project language policy.
    """
    meta = _OPENAPI_LOCALES[lang]
    schema = get_openapi(
        title=meta["title"],
        version=_APP_VERSION,
        description=meta["description"],
        routes=app.routes,
    )
    schema.setdefault("info", {})["x-language"] = lang
    return schema


@app.get("/openapi.ru.json", include_in_schema=False)
async def get_openapi_ru() -> JSONResponse:
    """OpenAPI specification with Russian ``info`` metadata."""
    return JSONResponse(_build_localised_openapi("ru"))


@app.get("/openapi.de.json", include_in_schema=False)
async def get_openapi_de() -> JSONResponse:
    """OpenAPI specification with German ``info`` metadata."""
    return JSONResponse(_build_localised_openapi("de"))


@app.get("/openapi.fr.json", include_in_schema=False)
async def get_openapi_fr() -> JSONResponse:
    """OpenAPI specification with French ``info`` metadata."""
    return JSONResponse(_build_localised_openapi("fr"))


@app.get("/docs/ru", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui_ru() -> HTMLResponse:
    """Swagger UI pre-configured for the Russian OpenAPI document."""
    return _swagger_ui_html("/openapi.ru.json", "SMDG API — Русская документация")


@app.get("/docs/de", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui_de() -> HTMLResponse:
    """Swagger UI pre-configured for the German OpenAPI document."""
    return _swagger_ui_html("/openapi.de.json", "SMDG API — Deutsche Dokumentation")


@app.get("/docs/fr", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui_fr() -> HTMLResponse:
    """Swagger UI pre-configured for the French OpenAPI document."""
    return _swagger_ui_html("/openapi.fr.json", "SMDG API — Documentation française")


def _swagger_ui_html(openapi_url: str, title: str) -> HTMLResponse:
    """Render a minimal Swagger UI shell pointing at ``openapi_url``."""
    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <title>{title}</title>
    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css\">
</head>
<body>
    <div id=\"swagger-ui\"></div>
    <script src=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
    <script>
        window.ui = SwaggerUIBundle({{
            url: '{openapi_url}',
            dom_id: '#swagger-ui',
            deepLinking: true,
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(html)


# ────────────────────────────────────────────────────────────────
# Обработчики Unix-сигналов
# ────────────────────────────────────────────────────────────────
# Uvicorn сам обрабатывает SIGTERM/SIGINT и корректно закрывает lifespan,
# запуская наш shutdown-блок. Но на случай, если SMDG стартует через иной
# ASGI-сервер (gunicorn + uvicorn worker, hypercorn и т.п.), регистрируем
# явные обработчики, которые:
#   1) логируют полученный сигнал;
#   2) выставляют ``app.state.shutting_down = True`` как можно раньше,
#      чтобы новые запросы начали получать 503 ещё до того, как сервер
#      инициирует закрытие lifespan;
#   3) НЕ вызывают sys.exit() — пусть ASGI-сервер сам запустит shutdown.
#
# SIGKILL (kill -9) перехватить невозможно по определению ядра Linux,
# при таком сигнале graceful shutdown не произойдёт — это ожидаемо.
# ────────────────────────────────────────────────────────────────

_SHUTDOWN_SIGNALS: tuple[int, ...] = (signal.SIGTERM, signal.SIGINT)


def _signal_handler(signum: int, frame) -> None:  # noqa: ARG001
    """Синхронный обработчик сигнала, помечающий приложение как shutting_down."""
    try:
        signame = signal.Signals(signum).name
    except ValueError:
        signame = str(signum)
    print(
        f"\n🛑 Получен сигнал {signame} ({signum}), инициируем graceful shutdown...",
        flush=True,
    )
    try:
        app.state.shutting_down = True
    except Exception:
        pass


def setup_signal_handlers() -> None:
    """Регистрация обработчиков сигналов для graceful shutdown.

    Вызывается при импорте модуля ``app.main``. В тестах и некоторых
    окружениях (например, внутри потоков) ``signal.signal`` может
    падать — такие ошибки игнорируются, т.к. uvicorn регистрирует
    собственные обработчики поверх.
    """
    for sig in _SHUTDOWN_SIGNALS:
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError) as e:
            logger.debug("Не удалось зарегистрировать обработчик %s: %s", sig, e)


setup_signal_handlers()
