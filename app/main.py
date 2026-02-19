# app/main.py
from fastapi import FastAPI, Request, logger
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api import upload, download, list, delete, cleanup, stats
from app.core import init_keys, file_storage, cleanup_manager, audit_logger
from app.core.database import engine, AsyncSessionLocal
from app.models.user import User
from app.core.security import get_password_hash, verify_password
from app.core.config import settings
from app.core.middleware import AuditMiddleware
from app.api.auth import router as auth_router
from app.api.admin_users import router as admin_users_router
from app.core import cleanup_manager
import asyncio
import logging
import os
from app.core.rate_limiter import limiter, check_redis_connection

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Secure Medical Data Gateway v0.1",
    version="0.1.0"
)

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
    "*"                          # временно для теста (удали в прод!)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,          # если используешь куки/auth headers
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Total-Count"],  # если возвращаешь пагинацию/кастом headers
    max_age=86400,                   # кэш preflight на сутки
)


app.state.limiter = limiter
def safe_rate_limit_handler(request: Request, exc: Exception):
    if isinstance(exc, RateLimitExceeded):
        return _rate_limit_exceeded_handler(request, exc)
    
    # Если что-то другое (например ConnectionError) — возвращаем 429 с общим сообщением
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов или ошибка сервиса. Попробуйте позже.",
                 "retry_after": "60 секунд"
        },
        headers={"Retry-After": "60"}
    )

app.add_exception_handler(RateLimitExceeded, safe_rate_limit_handler)


app.add_middleware(AuditMiddleware)
app.add_middleware(SlowAPIMiddleware)

# Монтирование статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

# Подключаем API
app.include_router(upload.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(list.router, prefix="/api")
app.include_router(delete.router, prefix="/api")
app.include_router(cleanup.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")

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



# Инициализация при запуске
@app.on_event("startup")
async def startup_event():
    print("🚀 Запуск SMDG v0.1...")
    
    # Инициализация ключей
    try:
        await init_keys()
        print("✅ Ключи шифрования инициализированы")
    except Exception as e:
        print(f"❌ Ошибка инициализации ключей: {e}")

 
    # ← Добавляем проверку Redis
    await check_redis_connection()
    print("✅ Rate limiter: Redis проверен")
    
    # Запуск периодической очистки
    await cleanup_manager.start_cleanup_task()
    print("✅ Периодическая очистка запущена (каждые 30 мин)")

    # Создание админа
    await create_first_admin()
    
    
    
async def create_first_admin():
    """Создаёт первого администратора, если его ещё нет (только в dev-режиме)"""
    if not settings.dev_mode:
        print("👀 Production-режим: пропускаем создание тестового админа")
        return

    async with AsyncSessionLocal() as db:
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
                    await db.commit()
                    print("✅ Email добавлен существующему admin")
                return

            # Создаём первого админа с email
            admin = User(
                username="admin",
                email="admin@example.com",  # ← ОБЯЗАТЕЛЬНО
                hashed_password=get_password_hash("admin123"),
                role="admin",
                is_active=True
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
            "static_files": True
        },
        "directories": {
            "static": os.path.exists("static"),
            "encrypted": os.path.exists("encrypted"),
            "keys": os.path.exists("keys"),
            "audit_logs": os.path.exists("audit_logs")
        }
    }

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
