# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api import upload, download, list, delete, cleanup, stats
from app.core import init_keys, file_storage, cleanup_manager, audit_logger
from app.core.middleware import AuditMiddleware
from app.api.auth import router as auth_router
import asyncio
import os

app = FastAPI(
    title="Secure Medical Data Gateway v0.1",
    version="0.1.0"
)

app.add_middleware(AuditMiddleware)

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

# Инициализация при запуске
@app.on_event("startup")
async def startup_event():
    print("🚀 Запуск SMDG v0.1...")
    
    try:
        await init_keys()
        print("✅ Ключи шифрования инициализированы")
    except Exception as e:
        print(f"❌ Критическая ошибка при инициализации ключей: {e}")
        audit_logger.log_operation(
            action="system_start_failed",
            filename="",
            user="system",
            reason=f"Key initialization failed: {str(e)}",
            success=False
        )
        raise  # Прерываем запуск — без ключей сервис не имеет смысла
    
    try:
        audit_logger.log_operation(
            action="system_start",
            filename="",
            user="system",
            reason="SMDG v0.1 успешно запущен"
        )
    except Exception as e:
        print(f"⚠️ Ошибка записи в audit лог при старте: {e}")
    
    try:
        asyncio.create_task(cleanup_manager.start_cleanup_task())
        print("✅ Фоновая очистка зашифрованных файлов запущена")
    except Exception as e:
        print(f"⚠️ Ошибка запуска cleanup_manager: {e}")
    
    print("✅ SMDG полностью готов к работе")

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
