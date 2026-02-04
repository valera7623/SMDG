import sys
import os
from pathlib import Path

from app.models.file_link import FileLink

# Добавляем корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import asyncio
import tempfile
import shutil
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import delete, text

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import TokenData, get_current_user, get_current_doctor, get_current_admin

# Глобальный мок для audit_logger
mock_audit_logger = MagicMock()
mock_audit_logger.log_operation = MagicMock()

# Автоматический мок авторизации для ВСЕХ тестов
@pytest.fixture(autouse=True)
def mock_current_user_global():
    print("=== ГЛОБАЛЬНЫЙ МОК get_current_user активирован ===")
    app.dependency_overrides[get_current_user] = lambda: TokenData(sub="test_user", role="doctor")
    app.dependency_overrides[get_current_doctor] = lambda: TokenData(sub="test_doctor", role="doctor")
    app.dependency_overrides[get_current_admin] = lambda: TokenData(sub="test_admin", role="admin")
    yield
    print("=== ГЛОБАЛЬНЫЙ МОК get_current_user отключён ===")
    app.dependency_overrides.clear()

# Глобальный мок subprocess (блокирует age и любые внешние команды)
@pytest.fixture(autouse=True)
def mock_subprocess_global():
    print("=== ГЛОБАЛЬНЫЙ МОК SUBPROCESS АКТИВИРОВАН ===")
    with patch("asyncio.create_subprocess_exec") as mock_sub:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")  # stdout, stderr
        mock_process.returncode = 0  # успех
        mock_process.wait.return_value = 0
        mock_sub.return_value = mock_process
        yield
    print("=== ГЛОБАЛЬНЫЙ МОК SUBPROCESS ОТКЛЮЧЁН ===")

# Фикстура временных директорий (для всех тестов)
@pytest.fixture(scope="function")
def temp_dirs(tmp_path):
    base_temp = Path(tmp_path)
    dirs = {
        "base": base_temp,
        "upload": base_temp / "uploads",
        "encrypted": base_temp / "encrypted",
        "decrypted": base_temp / "decrypted",
        "keys": base_temp / "keys",
    }
    
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
    
    # Создаём тестовые ключи
    (dirs["keys"] / "age.key").write_text("test_private_key")
    (dirs["keys"] / "age.pub").write_text("age1testpublickey123")
    
    yield dirs
    
    shutil.rmtree(base_temp, ignore_errors=True)

# Тестовая БД — SQLite в памяти (для unit-тестов, быстро)
TEST_SQLITE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="function")
async def sqlite_engine():
    engine = create_async_engine(TEST_SQLITE_URL, connect_args={"check_same_thread": False})
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(scope="function")
async def sqlite_db_session(sqlite_engine):
    async_session = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        yield session

# Тестовая PostgreSQL через testcontainers (для интеграционных тестов)
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres_container():
    postgres = PostgresContainer(
        image="postgres:15-alpine",
        dbname="smdg",
        user="smdg_user",
        password="password"
    )
    postgres.start()
    yield postgres
    postgres.stop()

@pytest.fixture(scope="session")
def postgres_url(postgres_container):
    return postgres_container.get_connection_url().replace("psycopg2", "asyncpg")

@pytest.fixture(scope="session")
async def postgres_engine(postgres_url):
    engine = create_async_engine(postgres_url, echo=False, pool_pre_ping=True)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(scope="function")
async def postgres_db_session(postgres_engine):
    async_session = async_sessionmaker(postgres_engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Очищаем таблицы перед тестом (без TRUNCATE, чтобы не ломать FK)
        await session.execute(delete(FileLink))
        await session.execute(delete(pytest.File))
        await session.commit()
        yield session

# Выбор БД в зависимости от теста
@pytest.fixture
def db_session(request):
    """Автоматически выбирает SQLite или PostgreSQL в зависимости от маркера теста"""
    if "integration" in request.keywords:
        return request.getfixturevalue("postgres_db_session")
    else:
        return request.getfixturevalue("sqlite_db_session")

# Тестовый клиент (для всех тестов)
@pytest.fixture
def client(db_session, temp_dirs):
    """Тестовый клиент с правильными моками путей и БД"""
    with patch("app.core.UPLOAD_DIR", temp_dirs["upload"]), \
         patch("app.core.ENCRYPTED_DIR", temp_dirs["encrypted"]), \
         patch("app.core.DECRYPTED_DIR", temp_dirs["decrypted"]), \
         patch("app.core.PRIVATE_KEY_PATH", temp_dirs["keys"] / "age.key"), \
         patch("app.api.upload.UPLOAD_DIR", temp_dirs["upload"]), \
         patch("app.api.upload.ENCRYPTED_DIR", temp_dirs["encrypted"]), \
         patch("app.api.download.ENCRYPTED_DIR", temp_dirs["encrypted"]), \
         patch("app.api.download.DECRYPTED_DIR", temp_dirs["decrypted"]), \
         patch("app.api.download.PRIVATE_KEY_PATH", temp_dirs["keys"] / "age.key"), \
         patch("app.core.config.settings") as mock_settings:
        
        mock_settings.dev_mode = True
        mock_settings.debug = True
        mock_settings.MAX_UPLOAD_SIZE_MB = 100
        mock_settings.ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg"]
        mock_settings.DICOM_MAGIC = b"DICM"
        mock_settings.CLAMAV_HOST = "localhost"
        mock_settings.CLAMAV_PORT = 3310
        mock_settings.CLAMAV_TIMEOUT = 30
        
        # Подмена БД
        async def override_get_db():
            yield db_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        with TestClient(app) as test_client:
            yield test_client
        
        app.dependency_overrides.clear()

# Мок crypto_manager (для unit-тестов)
@pytest.fixture
def mock_crypto():
    with patch("app.crypto.crypto.crypto_manager") as mock:
        mock.encrypt_file = AsyncMock(return_value="test_hash_123")
        mock.decrypt_file = AsyncMock(return_value=None)
        mock.check_age_installed = MagicMock(return_value=True)
        yield mock

# Мок времени (если нужно)
@pytest.fixture
def mock_time():
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        yield mock_time

# Event loop для async тестов
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# В conftest.py — заменяем весь блок патчей на это

@pytest.fixture(scope="session", autouse=True)
def patch_audit_logger():
    """Глобальный патч audit_logger для всех тестов"""
    from app.core import audit as audit_module
    
    mock_audit = MagicMock()
    mock_audit.log_operation = MagicMock()
    
    # Патчим только существующие модули
    patched_modules = []
    
    modules_to_patch = [
        "app.core",
        "app.main",
        "app.api.upload",
        "app.api.download",
        "app.api.auth",
        "app.api.list",
        "app.api.delete",
        "app.api.stats",
        "app.core.middleware",
    ]
    
    for module_path in modules_to_patch:
        try:
            module = sys.modules.get(module_path) or __import__(module_path)
            if hasattr(module, "audit_logger"):
                patcher = patch(f"{module_path}.audit_logger", mock_audit)
                patcher.start()
                patched_modules.append(patcher)
                print(f"Патч audit_logger применён для {module_path}")
        except (ImportError, AttributeError):
            pass  # модуль не существует или нет audit_logger — пропускаем
    
    yield
    
    # Автоматическая остановка всех патчей после сессии
    for patcher in patched_modules:
        try:
            patcher.stop()
            print(f"Патч остановлен для {patcher.target}")
        except:
            pass