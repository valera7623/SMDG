# app/main.py
import logging
import os
import signal
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.warnings_filters import apply_known_warning_filters

apply_known_warning_filters()

from app.bootstrap.api_routes import register_api_routers
from app.bootstrap.initial_admin import create_first_admin, ensure_admin_exists  # noqa: F401
from app.bootstrap.openapi_i18n import register_localized_openapi_routes
from app.core.auth import get_current_admin, get_current_user
from app.core.auth_utils import TokenData
from app.core.bulkhead import BulkheadRejectedError, BulkheadTimeoutError
from app.core.config import get_cors_allow_origins, settings
from app.core.database import AsyncSessionLocal
from app.core.feature_flags import get_deployment_info
from app.core.middleware import (
    ActiveRequestsMiddleware,
    AuditMiddleware,
    BulkheadMiddleware,
    CompressionMiddleware,
    SLOMiddleware,
    TimeoutMiddleware,
    TracingMiddleware,
)
from app.core.rate_limiter import limiter
from app.core.tenant import resolve_tenant_from_request
from app.core.timeout import TimeoutError
from app.core.tracing import setup_tracing
from app.core.version import APP_VERSION, AUDIT_EXPORT_VERSION, FASTAPI_APP_API_VERSION
from app.lifecycle.lifespan import lifespan
from app.services import email_service as _email_service  # noqa: F401
from app.templating import get_templates

# Публичная status page (SLA/SLI), см. app/status/status.html
_STATUS_PAGE_PATH = Path(__file__).resolve().parent / "status" / "status.html"


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


# Создаём приложение с lifespan
app = FastAPI(
    title="SMDG",
    version=FASTAPI_APP_API_VERSION,
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

# Разрешённые origins: localhost / OHIF + переменная CORS_ORIGINS (см. get_cors_allow_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allow_origins(),
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

    # Pre-prod load profile: avoid extra DB hit in middleware for auth capacity tests.
    if settings.load_test_mode and request.url.path == "/api/auth/login" and not token:
        tenant = SimpleNamespace(id=1, subdomain=settings.tenant_default_subdomain)
    else:
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
if not settings.load_test_mode:
    app.add_middleware(TimeoutMiddleware)
else:
    logger.warning("TimeoutMiddleware disabled because LOAD_TEST_MODE is enabled")
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

# Use shared limiter from app.core.rate_limiter to avoid dual instances
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


# Подключаем API (сначала — чтобы не пересекаться с catch-all/ mount; static ниже)
register_api_routers(app)

# Статика — после API-маршрутов (рекомендация Starlette; избегает редких 404 на /api/*)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Главная страница (Jinja2 + asset pipeline / CDN URL; без Jinja2 — static/html/index.html)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная: ``app/templates/index.html``; если Jinja2 не в окружении — ``static/html/index.html``."""
    if getattr(request.app.state, "jinja2_templates_ok", False):
        try:
            return get_templates().TemplateResponse(
                request,
                "index.html",
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("index template render failed: %s", e)
    try:
        with open("static/html/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<html><body><h1>SMDG</h1><p>Templates unavailable and static/html/index.html missing.</p></body></html>",
            status_code=500,
        )


@app.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def service_status_page():
    """Публичная страница статуса (читает JSON с ``/api/sli/status``)."""
    if not _STATUS_PAGE_PATH.is_file():
        return HTMLResponse(
            "<html><body><h1>Status page not found</h1></body></html>",
            status_code=404,
        )
    return HTMLResponse(
        _STATUS_PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Панель администратора
@app.get("/admin", response_class=HTMLResponse)
async def admin(_current_admin: Annotated[TokenData, Depends(get_current_admin)]):
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
        "version": APP_VERSION,
        "audit_export_version": AUDIT_EXPORT_VERSION,
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
async def view_logs(_current_admin: Annotated[TokenData, Depends(get_current_admin)]):
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
async def admin_users(_current_admin: Annotated[TokenData, Depends(get_current_admin)]):
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
async def admin_dlq(_current_admin: Annotated[TokenData, Depends(get_current_admin)]):
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


# Локализованные OpenAPI (/openapi.{ru,de,fr}.json, /docs/{ru,de,fr})
register_localized_openapi_routes(app)


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


def setup_signal_handlers(application: FastAPI) -> None:
    """Регистрация обработчиков сигналов для graceful shutdown.

    В тестах и некоторых окружениях ``signal.signal`` может падать —
    ошибки игнорируются, т.к. uvicorn регистрирует собственные обработчики поверх.
    """

    def _signal_handler(signum: int, frame) -> None:  # noqa: ARG001
        try:
            signame = signal.Signals(signum).name
        except ValueError:
            signame = str(signum)
        print(
            f"\n🛑 Получен сигнал {signame} ({signum}), инициируем graceful shutdown...",
            flush=True,
        )
        try:
            application.state.shutting_down = True
        except Exception:
            pass

    for sig in _SHUTDOWN_SIGNALS:
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError) as e:
            logger.debug("Не удалось зарегистрировать обработчик %s: %s", sig, e)


setup_signal_handlers(app)
