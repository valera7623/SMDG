# app/main.py
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, logger, HTTPException
from typing import Annotated
from prometheus_fastapi_instrumentator import Instrumentator
from limits.typing import RedisClient
from app.core.auth import get_current_user, TokenData
from app.core.config import settings
from app.core.rate_limiter import limiter, check_redis_connection
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
from app.api import upload, download, list, delete, cleanup, stats, webhooks, dicom
from app.core import init_keys, file_storage, cleanup_manager, audit_logger
from app.core import encrypted_storage
from app.core.webhook import webhook_dispatcher
from app.core.auth import get_current_user
from app.core.auth_utils import TokenData
from app.core.database import engine, AsyncSessionLocal, Base
from app.models import User, File, FileLink, WebhookSubscription, WebhookDelivery, Tenant
from app.core.security import get_password_hash, verify_password
from app.core.tenant import resolve_tenant_from_request

from app.core.middleware import AuditMiddleware
from app.api.auth import router as auth_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_audit_export import router as admin_audit_export_router
from app.api.delete_user import router as delete_user_router
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core import cleanup_manager
import asyncio
import logging
import os

from app.models.webhook import DeliveryStatus, WebhookDelivery


logger = logging.getLogger(__name__)


async def webhook_retry_scheduler():
    """Фоновая задача для повторной отправки неудачных webhook доставок."""
    from sqlalchemy import select, exc
    from datetime import datetime, timezone
    import time

    # Ждём чтобы миграции успели примениться
    await asyncio.sleep(5)

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

        except (exc.ProgrammingError, exc.OperationalError) as e:
            # Таблицы ещё не существуют — ждём
            logger.debug(f"Webhook retry: таблицы ещё не готовы ({e}), повтор через 10с")
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Webhook retry scheduler error: {e}")
            await asyncio.sleep(10)

        await asyncio.sleep(30)  # Проверка каждые 30 секунд


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager для управления жизненным циклом приложения"""
    print("🚀 Запуск SMDG v0.1...")

    # Startup
    try:
        await init_keys()
        print("✅ Ключи шифрования инициализированы")
    except Exception as e:
        print(f"❌ Ошибка инициализации ключей: {e}")

    await check_redis_connection()
    print("✅ Rate limiter: Redis проверен")

    # S3 Lifecycle Policies — применяем при использовании S3
    from app.core.storage_backend import S3StorageBackend
    if isinstance(encrypted_storage, S3StorageBackend):
        if settings.s3_lifecycle_enabled:
            try:
                from app.core.s3_lifecycle import S3LifecyclePolicyManager
                import json
                
                s3_client = await encrypted_storage._get_client()
                
                # Парсим кастомные политики
                custom_policies = {}
                if settings.s3_lifecycle_custom_policies:
                    try:
                        custom_policies = json.loads(settings.s3_lifecycle_custom_policies)
                    except json.JSONDecodeError as e:
                        print(f"⚠️ Ошибка парсинга s3_lifecycle_custom_policies: {e}")
                
                lifecycle_mgr = S3LifecyclePolicyManager(
                    s3_client=s3_client,
                    bucket=encrypted_storage.bucket,
                    default_ttl_days=settings.s3_lifecycle_default_ttl_days,
                    custom_policies=custom_policies if custom_policies else None,
                )
                
                result = await lifecycle_mgr.apply_lifecycle_rules()
                if result.get("success"):
                    print(f"✅ S3 Lifecycle Policies применены: {result['rules_count']} правил")
                else:
                    print(f"⚠️ S3 Lifecycle не применены: {result.get('error')}")
                    # Fallback к APScheduler
                    await cleanup_manager.start_cleanup_task()
            except Exception as e:
                print(f"⚠️ Ошибка настройки S3 Lifecycle: {e}")
                # Fallback к APScheduler
                await cleanup_manager.start_cleanup_task()
        else:
            print("ℹ️ S3 Lifecycle отключены (s3_lifecycle_enabled=false)")
            await cleanup_manager.start_cleanup_task()
    else:
        # Локальное хранилище — используем APScheduler
        await cleanup_manager.start_cleanup_task()
        print("✅ Авто-очистка старых файлов запущена (APScheduler, локальное хранилище)")

    # Конфигурируем все SQLAlchemy мапперы
    Base.registry.configure()
    print("✅ SQLAlchemy мапперы сконфигурированы")

    # Запуск фоновой задачи retry для webhook доставок (с задержкой чтобы миграции успели примениться)
    await asyncio.sleep(2)  # Даём миграциям завершиться
    asyncio.create_task(webhook_retry_scheduler())
    print("✅ Webhook retry scheduler запущен")

    try:
        await RedisClient.set("test_key_startup", "test_value", ex=60)
        value = await RedisClient.get("test_key_startup")
        print(f"Redis тестовая запись прошла: {value}")
    except Exception as e:
        print(f"Ошибка тестовой записи в Redis: {e}")

    await create_first_admin()

    yield  # Здесь приложение работает

    # Shutdown (если нужно)
    print("🛑 Завершение работы SMDG...")
    try:
        await cleanup_manager.stop_cleanup_task()
    except Exception as e:
        print(f"⚠️ Ошибка остановки cleanup: {e}")
    try:
        await webhook_dispatcher.close()
    except Exception as e:
        print(f"⚠️ Ошибка закрытия webhook dispatcher: {e}")
    try:
        await RedisClient.close()
    except Exception as e:
        print(f"⚠️ Ошибка закрытия Redis: {e}")
    print("✅ Ресурсы освобождены")

# Создаём приложение с lifespan
app = FastAPI(
    title="SMDG",
    version="1.0",
    lifespan=lifespan,  
    docs_url="/docs",        
    redoc_url="/redoc",      
    openapi_url="/openapi.json"
)

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

# Rate limiter с логами
def custom_key_func(request: Request) -> str:
    user = request.scope.get("user")
    if user and hasattr(user, "sub"):
        key = f"rate_limit:user:{user.sub}"
        logger.info(f"Rate limit: пользователь {user.sub} → ключ {key}")
        return key
    
    ip = get_remote_address(request)
    key = f"rate_limit:ip:{ip}"
    logger.info(f"Rate limit: аноним → ключ {key}")
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

        async with db.begin():
            result = await db.execute(
                select(User).where(User.username == "admin")
            )
            existing_admin = result.scalar_one_or_none()

            if existing_admin:
                print("ℹ️  Пользователь admin уже существует")
                # Проверим, есть ли email
                if not existing_admin.email:
                    existing_admin.email = "admin@example.com"
                if not existing_admin.tenant_id:
                    existing_admin.tenant_id = default_tenant.id
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
    return {
        "status": "healthy",
        "service": "smdg",
        "version": "0.1.0",
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


# Страница DICOM Viewer
@app.get("/dicom-viewer", response_class=HTMLResponse)
@app.get("/dicom-viewer/", response_class=HTMLResponse)
async def dicom_viewer_page():
    """Страница DICOM Viewer (OHIF Viewer обёртка)."""
    try:
        from fastapi.responses import HTMLResponse as _HR
        from datetime import datetime
        with open("static/html/dicom-viewer.html", "r", encoding="utf-8") as f:
            content = f.read()
        response = HTMLResponse(content=content)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except FileNotFoundError:
        return HTMLResponse(
            status_code=500,
            content="<h1>DICOM Viewer не найден</h1>"
        )


# Страница OHIF Viewer
@app.get("/ohif-viewer", response_class=HTMLResponse)
@app.get("/ohif-viewer/", response_class=HTMLResponse)
async def ohif_viewer_page():
    """Страница OHIF-style Viewer."""
    try:
        with open("static/html/ohif-viewer.html", "r", encoding="utf-8") as f:
            content = f.read()
        response = HTMLResponse(content=content)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except FileNotFoundError:
        return HTMLResponse(
            status_code=500,
            content="<h1>OHIF Viewer не найден</h1>"
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
