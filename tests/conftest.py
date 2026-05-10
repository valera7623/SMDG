# tests/conftest.py - обновлённая версия
import os
from dotenv import load_dotenv
load_dotenv(".env.test", override=True)
from app.core.rate_limiter import limiter
limiter.enabled = False
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from dotenv import load_dotenv
from typer.testing import CliRunner

# Загружаем переменные окружения ДО импорта приложения
TEST_AUDIT_DIR = Path(tempfile.mkdtemp(prefix="smdg_test_audit_"))
TEST_AUDIT_DIR.mkdir(exist_ok=True)

os.environ["AUDIT_LOG_DIR"] = str(TEST_AUDIT_DIR)

sys.path.insert(0, '.')

with patch.dict('sys.modules', {'app.core.audit': None}):
    pass
# Добавляем корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.warnings_filters import apply_known_warning_filters

apply_known_warning_filters()

from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
import app.core as _pytest_app_core

# Реальный ``init_keys`` до подмены mock_core_functions (для unit-тестов в test_core/test_init.py).
_PYTEST_REAL_INIT_KEYS_REF = _pytest_app_core.init_keys

from app.core.database import Base, dispose_async_engine, get_db
from app.core.auth import get_current_user
from app.core.config import settings
from app.models.tenant import Tenant
from app.core.dependencies import get_db_auto, get_db_for_read, get_db_for_write
from fastapi import Request
from app.core.storage_backend import ObjectMetadata

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
    connect_args={"ssl": False},
)

TestingSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
async def _dispose_async_engine_after_each_test():
    """Сброс async-пула между тестами.

    Смешение ``AsyncClient`` (pytest-asyncio loop) и sync ``TestClient`` (anyio
    portal / другой loop) иначе оставляет asyncpg-соединения на «чужом» loop —
    middleware tenant падает с pool/loop errors → 400.

    Важно: middleware использует ``app.core.database.get_engine()``, а не
    ``test_engine`` из этого conftest — сбрасываем оба пула.

    ``TestClient`` с lifespan (см. ``tests/security/test_api_security``) при
    выходе из контекста ставит ``app.state.shutting_down`` — без сброса
    последующие запросы получают 503.
    """
    app.state.shutting_down = False
    yield
    await test_engine.dispose()
    await dispose_async_engine()


@pytest.fixture(scope="session")
async def setup_test_db():
    """Создаём таблицы перед тестами"""
    async with test_engine.begin() as conn:
        # Удаляем и создаём таблицы заново
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        session.add(Tenant(id=1, name="Default Tenant", subdomain="default", settings={}))
        await session.commit()
        print("✅ Таблицы созданы")
    yield
    # Очищаем после тестов
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("🗑️ Таблицы удалены")


@pytest.fixture(scope="session", autouse=True)
async def _autouse_setup_test_db(setup_test_db):
    """Всегда создаём схему и дефолтный tenant до API-тестов.

    ``set_user_context`` в ``app/main.py`` резолвит tenant через реальный
    ``AsyncSessionLocal``, не через ``get_db`` из dependency_overrides —
    без строки tenant запросы получают 400.
    """
    yield


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


@pytest.fixture
async def override_app_db(db_session) -> AsyncGenerator[AsyncSession, None]:
    """Подмена всех DI-сессий БД на тестовую (в т.ч. get_db_for_read/write)."""
    from app.main import app

    async def _get_db():
        yield db_session

    async def _get_db_req(_request: Request):
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_db_for_read] = _get_db_req
    app.dependency_overrides[get_db_for_write] = _get_db_req
    app.dependency_overrides[get_db_auto] = _get_db_req
    yield db_session
    for dep in (get_db, get_db_for_read, get_db_for_write, get_db_auto):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def stub_encrypted_storage(monkeypatch):
    """Заглушка хранилища: «файл есть», фиктивные stat/download/delete."""
    import time
    from app.core import encrypted_storage

    async def _exists(_key: str) -> bool:
        return True

    async def _stat(key: str) -> ObjectMetadata:
        return ObjectMetadata(key=key, size=4096, last_modified=time.time())

    async def _download(key: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"stub")
        return dest

    async def _delete(_key: str) -> None:
        return None

    monkeypatch.setattr(encrypted_storage, "exists", _exists)
    monkeypatch.setattr(encrypted_storage, "stat", _stat)
    monkeypatch.setattr(encrypted_storage, "download", _download)
    monkeypatch.setattr(encrypted_storage, "delete", _delete)


# ========== ФИКСТУРЫ ДЛЯ ТЕСТОВЫХ ДАННЫХ ==========

@pytest.fixture
async def test_user(db_session):
    """Создаёт тестового обычного пользователя"""
    user = UserFactory.create()
    return user


@pytest.fixture
async def test_doctor(db_session):
    """Создаёт тестового врача"""
    user = UserFactory.create(doctor=True)
    return user


@pytest.fixture
async def test_admin(db_session):
    """Создаёт тестового администратора"""
    user = UserFactory.create(admin=True)
    return user


@pytest.fixture
async def test_inactive_user(db_session):
    """Создаёт неактивного пользователя"""
    user = UserFactory.create(inactive=True)
    return user


# ========== ПЕРЕОПРЕДЕЛЕНИЕ ЗАВИСИМОСТЕЙ ==========

@pytest.fixture
def mock_current_user(test_doctor):
    """Мок текущего пользователя (врач)"""
    from app.core.auth import TokenData
    
    def _get_current_user():
        tid = getattr(test_doctor, "tenant_id", None) or 1
        return TokenData(sub=str(test_doctor.id), role=test_doctor.role, tenant_id=tid)
    
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
        


# Глобальный мок Redis для всех тестов

@pytest.fixture(autouse=True)
def mock_redis_global():
    """Глобальный мок Redis + правильный close для lifespan"""
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=None)
    mock_instance.set = AsyncMock(return_value=True)
    mock_instance.incr = AsyncMock(return_value=1)
    mock_instance.expire = AsyncMock(return_value=True)
    mock_instance.close = AsyncMock()                    # awaitable close (legacy)
    mock_instance.aclose = AsyncMock()                   # awaitable aclose (redis>=5)

    with patch("app.core.rate_limiter.redis_client", mock_instance), \
         patch("app.lifecycle.lifespan.redis_client", mock_instance):
        yield mock_instance
        

# ========== Фабрики типовых моков (устраняют дублирование фикстур) ==========

def _build_cleanup_manager_mock() -> MagicMock:
    """Типовой мок FileCleanupManager, используемый тестами."""
    m = MagicMock()
    m.start_cleanup_task = AsyncMock()
    m.stop_cleanup_task = AsyncMock()
    m.get_cleanup_stats = MagicMock(return_value={"cleaned": 0, "errors": 0})
    return m


def _build_crypto_manager_mock() -> MagicMock:
    """Типовой мок CryptoManager — чтобы тесты не зависели от наличия age."""
    m = MagicMock()
    m.check_age_installed = MagicMock(return_value=True)
    m.generate_keypair = AsyncMock(return_value=("age1mockpublickey1234567890", "/tmp/mock_age.key"))
    m.generate_new_keypair = AsyncMock(return_value=(Path("/tmp/mock.key"), "age1mockpublickey1234567890"))
    m.encrypt = AsyncMock(return_value="fake_encrypt_hash_123")
    m.decrypt = AsyncMock(return_value="fake_decrypt_hash_456")
    m.encrypt_file = AsyncMock(return_value="fake_encrypt_hash_123")
    m.decrypt_file = AsyncMock()
    m.reencrypt_file = AsyncMock()
    m.rotate_keys = AsyncMock(return_value="age1mockrotatedpubkey123")
    return m


@pytest.fixture(autouse=True)
def mock_cleanup_manager():
    """Глобальный мок cleanup_manager (lifespan импортирует из ``app.core``)."""
    mock_instance = _build_cleanup_manager_mock()
    with patch("app.lifecycle.lifespan.cleanup_manager", mock_instance):
        yield mock_instance


# Глобальный мок для init_keys и других функций
@pytest.fixture(autouse=True)
def mock_core_functions():
    """Мок для ключевых функций"""
    with patch("app.core.init_keys", new_callable=AsyncMock) as mock_init, \
         patch("app.lifecycle.lifespan.check_redis_connection", new_callable=AsyncMock) as mock_check_redis, \
         patch("app.lifecycle.lifespan.create_first_admin", new_callable=AsyncMock) as mock_create_admin, \
         patch("app.bootstrap.initial_admin.ensure_admin_exists", new_callable=AsyncMock) as mock_ensure_admin:

        yield {
            "init_keys": mock_init,
            "check_redis": mock_check_redis,
            "create_admin": mock_create_admin,
            "ensure_admin": mock_ensure_admin
        }


@pytest.fixture(autouse=True)
def mock_crypto_manager():
    """Полный мок CryptoManager, чтобы тесты crypto не падали из-за отсутствия age в venv"""
    mock_instance = _build_crypto_manager_mock()
    with patch("app.crypto.crypto.crypto_manager", mock_instance), \
         patch("app.crypto.crypto.CryptoManager", return_value=mock_instance):
        yield mock_instance
