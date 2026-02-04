# tests/conftest.py
import sys
import os
from pathlib import Path

from app.models.file_link import FileLink

# Добавляем корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import asyncio
import shutil
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text, delete

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import TokenData, get_current_user, get_current_doctor, get_current_admin

# Глобальный мок для audit_logger (применяется ко всем тестам)
@pytest.fixture(scope="session", autouse=True)
def patch_audit_logger():
    """Глобальный патч audit_logger для всех тестов"""
    from app.core import audit as audit_module
    
    mock_audit = MagicMock()
    mock_audit.log_operation = MagicMock()
    
    patched = []
    modules = [
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
    
    for mod_path in modules:
        try:
            mod = sys.modules.get(mod_path) or __import__(mod_path)
            if hasattr(mod, "audit_logger"):
                p = patch(f"{mod_path}.audit_logger", mock_audit)
                p.start()
                patched.append(p)
        except (ImportError, AttributeError):
            pass
    
    yield
    
    for p in patched:
        try:
            p.stop()
        except:
            pass


# Глобальный мок авторизации (doctor по умолчанию)
@pytest.fixture(autouse=True)
def mock_current_user_global():
    print("=== ГЛОБАЛЬНЫЙ МОК get_current_user активирован ===")
    app.dependency_overrides[get_current_user] = lambda: TokenData(sub="test_user", role="doctor")
    app.dependency_overrides[get_current_doctor] = lambda: TokenData(sub="test_doctor", role="doctor")
    app.dependency_overrides[get_current_admin] = lambda: TokenData(sub="test_admin", role="admin")
    yield
    app.dependency_overrides.clear()
    print("=== ГЛОБАЛЬНЫЙ МОК get_current_user отключён ===")


# Глобальный мок subprocess — блокирует все вызовы age/subprocess
@pytest.fixture(autouse=True)
def mock_subprocess_global():
    print("=== ГЛОБАЛЬНЫЙ МОК SUBPROCESS АКТИВИРОВАН ===")
    with patch("asyncio.create_subprocess_exec") as mock_sub:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_sub.return_value = mock_process
        yield
    print("=== ГЛОБАЛЬНЫЙ МОК SUBPROCESS ОТКЛЮЧЁН ===")


# Фикстура временных директорий
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
    
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    
    # Тестовые ключи
    (dirs["keys"] / "age.key").write_text("test_private_key")
    (dirs["keys"] / "age.pub").write_text("age1testpublickey123")
    
    yield dirs
    
    shutil.rmtree(base_temp, ignore_errors=True)


# Определяем режим CI
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"


# SQLite для unit-тестов и CI
@pytest.fixture(scope="function")
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
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


# PostgreSQL через testcontainers (локально) или localhost (если CI)
@pytest.fixture(scope="session")
def postgres_container():
    if IS_GITHUB_ACTIONS:
        pytest.skip("PostgresContainer skipped in CI - using SQLite")
    
    from testcontainers.postgres import PostgresContainer
    
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
def postgres_url(postgres_container=None):
    if IS_GITHUB_ACTIONS:
        return "sqlite+aiosqlite:///:memory:"
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
        # Очистка таблиц перед тестом
        await session.execute(delete(FileLink))
        await session.execute(delete(pytest.File))
        await session.commit()
        yield session


# Автоматический выбор БД
@pytest.fixture
def db_session(request):
    if "integration" in request.keywords or IS_GITHUB_ACTIONS:
        return request.getfixturevalue("postgres_db_session")
    return request.getfixturevalue("sqlite_db_session")


# Тестовый клиент
@pytest.fixture
def client(db_session, temp_dirs):
    with patch("app.core.UPLOAD_DIR", temp_dirs["upload"]), \
         patch("app.core.ENCRYPTED_DIR", temp_dirs["encrypted"]), \
         patch("app.core.DECRYPTED_DIR", temp_dirs["decrypted"]), \
         patch("app.core.PRIVATE_KEY_PATH", temp_dirs["keys"] / "age.key"):
        
        async def override_get_db():
            yield db_session
        
        app.dependency_overrides[get_db] = override_get_db
        
        with TestClient(app) as test_client:
            yield test_client
        
        app.dependency_overrides.clear()


# Мок crypto_manager
@pytest.fixture
def mock_crypto():
    with patch("app.crypto.crypto.crypto_manager") as mock:
        mock.encrypt_file = AsyncMock(return_value="test_hash_123")
        mock.decrypt_file = AsyncMock(return_value=None)
        mock.check_age_installed = MagicMock(return_value=True)
        yield mock


# Мок времени
@pytest.fixture
def mock_time():
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        yield mock_time


# Event loop
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()