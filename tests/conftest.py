# tests/conftest.py - обновлённая версия
import os
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from dotenv import load_dotenv
from typer.testing import CliRunner
# Загружаем переменные окружения ДО импорта приложения
load_dotenv('.env.test')

# Добавляем корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.core.database import Base, get_db
from app.core.auth import get_current_user
from app.core.config import settings

# ========== ИМПОРТ ФАБРИК ==========
from tests.factories import UserFactory, FileFactory, FileLinkFactory

# ========== НАСТРОЙКА ТЕСТОВОЙ БД ==========

# Проверяем, что DATABASE_URL установлен
if not settings.database_url:
    raise ValueError("DATABASE_URL not set in .env.test")

print(f"🔧 Используется БД: {settings.database_url}")

# Создаём движок для тестов
test_engine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,
)

TestingSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
async def setup_test_db():
    """Создаём таблицы перед тестами"""
    async with test_engine.begin() as conn:
        # Удаляем и создаём таблицы заново
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Таблицы созданы")
    yield
    # Очищаем после тестов
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("🗑️ Таблицы удалены")


@pytest.fixture
async def db_session(setup_test_db) -> AsyncGenerator[AsyncSession, None]:
    """Фикстура для сессии БД"""
    async with TestingSessionLocal() as session:
        # Настраиваем фабрики на использование этой сессии
        UserFactory._meta.sqlalchemy_session = session
        FileFactory._meta.sqlalchemy_session = session
        FileLinkFactory._meta.sqlalchemy_session = session
        
        yield session
        # Откатываем после теста
        await session.rollback()


# ========== ФИКСТУРЫ ДЛЯ ТЕСТОВЫХ ДАННЫХ ==========

@pytest.fixture
async def test_user(db_session):
    """Создаёт тестового обычного пользователя"""
    user = await UserFactory.create()
    return user


@pytest.fixture
async def test_doctor(db_session):
    """Создаёт тестового врача"""
    user = await UserFactory.create(doctor=True)
    return user


@pytest.fixture
async def test_admin(db_session):
    """Создаёт тестового администратора"""
    user = await UserFactory.create(admin=True)
    return user


@pytest.fixture
async def test_inactive_user(db_session):
    """Создаёт неактивного пользователя"""
    user = await UserFactory.create(inactive=True)
    return user


# ========== ПЕРЕОПРЕДЕЛЕНИЕ ЗАВИСИМОСТЕЙ ==========

@pytest.fixture
def mock_current_user(test_doctor):
    """Мок текущего пользователя (врач)"""
    from app.core.auth import TokenData
    
    def _get_current_user():
        return TokenData(sub=str(test_doctor.id), role=test_doctor.role)
    
    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ========== ТЕСТОВЫЙ КЛИЕНТ ==========

@pytest.fixture
def client(db_session, mock_current_user) -> Generator:
    """Тестовый клиент FastAPI"""
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()


# ========== ВРЕМЕННЫЕ ДИРЕКТОРИИ ==========

@pytest.fixture
def temp_storage():
    """Создаёт временные директории для хранения файлов"""
    with tempfile.TemporaryDirectory() as tmpdir:
        uploads = Path(tmpdir) / "uploads"
        encrypted = Path(tmpdir) / "encrypted"
        decrypted = Path(tmpdir) / "decrypted"
        keys = Path(tmpdir) / "keys"
        
        for d in [uploads, encrypted, decrypted, keys]:
            d.mkdir(parents=True, exist_ok=True)
        
        (keys / "age.key").write_text("test-key")
        (keys / "age.pub").write_text("test-pub")
        
        yield {
            "upload": uploads,
            "encrypted": encrypted,
            "decrypted": decrypted,
            "keys": keys,
        }


# ========== МОКИ ==========

@pytest.fixture
def mock_crypto():
    """Мок криптографического модуля"""
    with patch("app.crypto.crypto.crypto_manager") as mock:
        mock.encrypt_file = AsyncMock(return_value="test_hash_123")
        mock.decrypt_file = AsyncMock(return_value=True)
        mock.check_age_installed = MagicMock(return_value=True)
        yield mock
        



@pytest.fixture
def cli_runner():
    """Фикстура для запуска CLI команд"""
    return CliRunner()


@pytest.fixture
def mock_async_session():
    """Фикстура для мока асинхронной сессии"""
    with patch("app.cli.AsyncSessionLocal") as mock_session_local:
        mock_session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = mock_session
        yield mock_session
        
# tests/conftest.py (добавьте в конец файла)

# Глобальный мок Redis для всех тестов
@pytest.fixture(autouse=True)
def mock_redis_global():
    """Глобальный мок Redis для предотвращения ошибок подключения"""
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=None)
    mock_instance.set = AsyncMock(return_value=True)
    mock_instance.incr = AsyncMock(return_value=1)
    mock_instance.expire = AsyncMock(return_value=True)
    mock_instance.close = AsyncMock()
    
    with patch("app.main.RedisClient", return_value=mock_instance), \
         patch("app.core.rate_limiter.redis_client", mock_instance):
        yield mock_instance


# Глобальный мок cleanup_manager
@pytest.fixture(autouse=True)
def mock_cleanup_manager():
    """Глобальный мок cleanup_manager"""
    # Создаём мок инстанса FileCleanupManager
    mock_instance = MagicMock()
    mock_instance.start_cleanup_task = AsyncMock()
    mock_instance.get_cleanup_stats = MagicMock(return_value={"cleaned": 0, "errors": 0})
    
    # Патчим импорт cleanup_manager в main.py
    with patch("app.main.cleanup_manager", mock_instance):
        yield mock_instance
        



# Глобальный мок для init_keys и других функций
@pytest.fixture(autouse=True)
def mock_core_functions():
    """Мок для ключевых функций"""
    with patch("app.main.init_keys", new_callable=AsyncMock) as mock_init, \
         patch("app.main.check_redis_connection", new_callable=AsyncMock) as mock_check_redis, \
         patch("app.main.create_first_admin", new_callable=AsyncMock) as mock_create_admin, \
         patch("app.main.ensure_admin_exists", new_callable=AsyncMock) as mock_ensure_admin:
        
        yield {
            "init_keys": mock_init,
            "check_redis": mock_check_redis,
            "create_admin": mock_create_admin,
            "ensure_admin": mock_ensure_admin
        }