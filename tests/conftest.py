# tests/conftest.py
import sys
import os
from pathlib import Path
from app.core.auth import TokenData, get_current_doctor, get_current_admin, get_current_user

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

# Глобальный мок для audit_logger
mock_audit_logger = MagicMock()
mock_audit_logger.log_operation = MagicMock()

# Создаем динамические патчи только для модулей, которые существуют
def safe_patch(module_path, attr_name, mock_obj):
    """Безопасный патч, пропускает если модуль или атрибут не существует"""
    try:
        # Проверяем существует ли модуль
        module_parts = module_path.split('.')
        try:
            __import__(module_path)
            module = sys.modules[module_path]
            
            # Проверяем есть ли атрибут
            if hasattr(module, attr_name):
                return patch(f"{module_path}.{attr_name}", mock_obj)
            else:
                # Если атрибута нет, создаем его
                setattr(module, attr_name, mock_obj)
                print(f"⚠️  Создан атрибут {attr_name} в {module_path}")
                return None
        except ImportError:
            # Модуль не существует, пропускаем
            print(f"⚠️  Модуль {module_path} не найден, пропускаем")
            return None
    except Exception as e:
        print(f"⚠️  Ошибка при проверке {module_path}.{attr_name}: {e}")
        return None

# Список модулей для патчинга (только те, которые точно существуют)
modules_to_patch = [
    "app.core",
    "app.main", 
    "app.api.upload",
    "app.api.download",
    "app.api.auth",
    "app.api.list",
    "app.api.delete",
    "app.api.stats",
    # "app.api.cleanup" - убираем, так как в cleanup.py нет audit_logger
    "app.core.middleware",
]

# Применяем патчи
patches = []
for module_path in modules_to_patch:
    patcher = safe_patch(module_path, "audit_logger", mock_audit_logger)
    if patcher:
        patches.append(patcher)
        patcher.start()

# Теперь безопасно импортируем
from app.main import app
from app.core.database import Base, get_db

# Тестовая БД в памяти
TEST_DATABASE_URL = "postgresql+asyncpg://smdg_user:password@localhost:5432/smdg"
# ИЛИ используем PostgreSQL из docker-compose
POSTGRES_TEST_URL = "postgresql+asyncpg://smdg_user:password@localhost:5432/smdg"

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
    
    # Очищаем decrypted от старых файлов (на всякий случай)
    for item in dirs["decrypted"].iterdir():
        if item.is_file():
            item.unlink()
    
    # Создаем тестовые ключи
    (dirs["keys"] / "age.key").write_text("test_private_key")
    (dirs["keys"] / "age.pub").write_text("age1testpublickey123")
    
    yield dirs
    
    # Очистка
    shutil.rmtree(base_temp, ignore_errors=True)

@pytest.fixture(scope="function")
async def db_engine():
    """Создает тестовую БД в памяти (SQLite)"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(scope="function")
async def test_engine():
    """PostgreSQL engine для интеграционных тестов"""
    engine = create_async_engine(
        POSTGRES_TEST_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    # Создаём таблицы один раз
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Удаляем таблицы после всех тестов
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(scope="function")
async def db_session(db_engine):
    """Сессия для тестовой БД (SQLite)"""
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session() as session:
        yield session

@pytest.fixture(scope="function")
async def test_db_session(test_engine):
    """Сессия для каждого теста — с rollback в конце (PostgreSQL)"""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with async_session() as session:
        # Начинаем транзакцию
        async with session.begin():
            yield session
            # rollback в конце теста — таблицы очищаются автоматически
            await session.rollback()

@pytest.fixture
def mock_time():
    with patch("app.core.storage.time") as mock_time:
        mock_time.time.return_value = 1000.0  
        yield mock_time

# УДАЛЯЕМ старую фикстуру client и создаем новую с правильным именем
@pytest.fixture
def test_client_with_mocks(db_session, temp_dirs):
    """Тестовый клиент FastAPI с моками (для unit тестов)"""
    # Мокаем пути
    with patch("app.core.UPLOAD_DIR", temp_dirs["upload"]):
        with patch("app.core.ENCRYPTED_DIR", temp_dirs["encrypted"]):
            with patch("app.core.DECRYPTED_DIR", temp_dirs["decrypted"]):
                with patch("app.core.PRIVATE_KEY_PATH", temp_dirs["keys"] / "age.key"):
                    with patch("app.core.BASE_DIR", temp_dirs["base"]):
                        # Мокаем API модули
                        with patch("app.api.upload.UPLOAD_DIR", temp_dirs["upload"]):
                            with patch("app.api.upload.ENCRYPTED_DIR", temp_dirs["encrypted"]):
                                with patch("app.api.download.ENCRYPTED_DIR", temp_dirs["encrypted"]):
                                    with patch("app.api.download.DECRYPTED_DIR", temp_dirs["decrypted"]):
                                        with patch("app.api.download.PRIVATE_KEY_PATH", temp_dirs["keys"] / "age.key"):
                                            with patch("app.api.list.ENCRYPTED_DIR", temp_dirs["encrypted"]):
                                                with patch("app.api.delete.ENCRYPTED_DIR", temp_dirs["encrypted"]):
                                                    with patch("app.api.stats.ENCRYPTED_DIR", temp_dirs["encrypted"]):
                                                        with patch("app.api.stats.DECRYPTED_DIR", temp_dirs["decrypted"]):
                                                            with patch("app.api.stats.UPLOAD_DIR", temp_dirs["upload"]):
                                                                with patch("app.api.cleanup.DECRYPTED_DIR", temp_dirs["decrypted"]):
                                                                    # Мокаем настройки
                                                                    with patch("app.core.config.settings") as mock_settings:
                                                                        mock_settings.debug = True
                                                                        mock_settings.dev_mode = True
                                                                        mock_settings.MAX_UPLOAD_SIZE_MB = 100
                                                                        mock_settings.ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg"]
                                                                        mock_settings.DICOM_MAGIC = b"DICM"
                                                                        mock_settings.CLAMAV_HOST = "localhost"
                                                                        mock_settings.CLAMAV_PORT = 3310
                                                                        mock_settings.CLAMAV_TIMEOUT = 30
                                                                        mock_settings.database_url = TEST_DATABASE_URL
                                                                        mock_settings.jwt_secret_key = "test_secret"
                                                                        mock_settings.jwt_algorithm = "HS256"
                                                                        mock_settings.jwt_access_expires_minutes = 60
                                                                        
                                                                        # Мокаем ClamAV чтобы не было проблем с подключением
                                                                        with patch("clamd.ClamdNetworkSocket") as mock_clamd:
                                                                            mock_clamd_instance = MagicMock()
                                                                            mock_clamd_instance.ping.return_value = "PONG"
                                                                            mock_clamd_instance.instream.return_value = ("OK",)
                                                                            mock_clamd.return_value = mock_clamd_instance
                                                                            
                                                                            # Подменяем зависимость БД
                                                                            async def override_get_db():
                                                                                yield db_session
                                                                            
                                                                            app.dependency_overrides[get_db] = override_get_db
                                                                            
                                                                            # Переопределяем авторизацию по умолчанию
                                                                            from app.core.auth import TokenData
                                                                            test_user = TokenData(sub="test_user", role="doctor")
                                                                            app.dependency_overrides[get_current_doctor] = lambda: test_user
                                                                            app.dependency_overrides[get_current_admin] = lambda: TokenData(sub="admin", role="admin")
                                                                            
                                                                            with TestClient(app) as test_client:
                                                                                yield test_client
                                                                            
                                                                            app.dependency_overrides.clear()

@pytest.fixture
def client():
    """Простой тестовый клиент без моков (для интеграционных тестов)"""
    # Очищаем все зависимости перед созданием клиента
    app.dependency_overrides.clear()
    return TestClient(app)

@pytest.fixture
def mock_crypto():
    """Мок для crypto_manager"""
    with patch("app.crypto.crypto.crypto_manager") as mock:
        mock.encrypt_file = AsyncMock(return_value="test_hash_123")
        mock.decrypt_file = AsyncMock(return_value=None)
        mock.check_age_installed = MagicMock(return_value=True)
        yield mock

@pytest.fixture(scope="session")
def event_loop():
    """Event loop для async тестов"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
    
@pytest.fixture
def mock_settings():
    with patch("app.main.settings") as mocked_settings:
        mocked_settings.dev_mode = True
        mocked_settings.debug = False
        yield mocked_settings

@pytest.fixture
def mock_current_user():
    """Мок аутентифицированного пользователя (доктор)"""
    user = MagicMock()
    user.sub = "test_doctor"
    user.role = "doctor"
    return user

@pytest.fixture
def mock_current_admin():
    """Мок аутентифицированного администратора"""
    user = MagicMock()
    user.sub = "test_admin"
    user.role = "admin"
    return user

@pytest.fixture
def mock_db_session():
    """Синхронный mock для большинства операций + правильный async context"""
    mock_session = MagicMock()  # основной объект — синхронный

    # Результат execute — тоже синхронный
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute.return_value = mock_result

    # commit, add, refresh — синхронные
    mock_session.commit = MagicMock()
    mock_session.add = MagicMock()
    mock_session.refresh = MagicMock()

    # Для async with session.begin():
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_session)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin = MagicMock(return_value=mock_transaction)

    yield mock_session

@pytest.fixture(autouse=True)
def override_dependencies(mock_current_user, mock_db_session):
    """Переопределение зависимостей для всех тестов"""
    # Переопределяем зависимости FastAPI
    from app.core.auth import TokenData
    
    # Создаем реальные объекты TokenData вместо Mock
    doctor_user = TokenData(sub="test_doctor", role="doctor")
    admin_user = TokenData(sub="test_admin", role="admin")
    
    app.dependency_overrides[get_current_doctor] = lambda: doctor_user
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    
    yield
    
    # Очищаем переопределения после теста
    app.dependency_overrides.clear()
    
    
@pytest.fixture(autouse=True)
def mock_subprocess_global():
    """Глобальный мок subprocess — блокирует все вызовы age в тестах"""
    print("=== ГЛОБАЛЬНЫЙ МОК SUBPROCESS АКТИВИРОВАН ===")
    with patch("asyncio.create_subprocess_exec") as mock_sub:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")  # stdout, stderr
        mock_process.returncode = 0  # успех
        mock_sub.return_value = mock_process
        yield
    print("=== ГЛОБАЛЬНЫЙ МОК SUBPROCESS ОТКЛЮЧЁН ===")
    
    
        
@pytest.fixture(autouse=True)
def mock_current_user_global():
    """Глобальный мок авторизации для ВСЕХ интеграционных тестов"""
    print("=== ГЛОБАЛЬНЫЙ МОК get_current_user активирован ===")
    app.dependency_overrides[get_current_user] = lambda: TokenData(sub="test_user", role="doctor")
    yield
    print("=== ГЛОБАЛЬНЫЙ МОК get_current_user отключён ===")
    app.dependency_overrides.clear()
    
    
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres_container():
    postgres = PostgresContainer(
        image="postgres:15-alpine",
        dbname="smdg",
        user="smdg_user",
        password="password",
        port_to_expose=5432
    )
    postgres.start()
    yield postgres
    postgres.stop()


@pytest.fixture(scope="session")
def test_database_url(postgres_container):
    return postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
        
    
# Останавливаем патчи в конце
def pytest_sessionfinish(session, exitstatus):
    for patcher in patches:
        try:
            patcher.stop()
        except:
            pass