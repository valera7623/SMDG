# tests/conftest.py
import sys
import os
from pathlib import Path
from app.core.auth import get_current_doctor

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
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def temp_dirs():
    """Создает временные директории для тестов"""
    base_temp = Path(tempfile.mkdtemp(prefix="smdg_test_"))
    dirs = {
        "base": base_temp,
        "upload": base_temp / "uploads",
        "encrypted": base_temp / "encrypted", 
        "decrypted": base_temp / "decrypted",
        "keys": base_temp / "keys",
    }
    
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
    
    # Создаем тестовые ключи
    (dirs["keys"] / "age.key").write_text("test_private_key")
    (dirs["keys"] / "age.pub").write_text("age1testpublickey123")
    
    yield dirs
    
    # Очистка
    shutil.rmtree(base_temp, ignore_errors=True)

@pytest.fixture(scope="function")
async def db_engine():
    """Создает тестовую БД в памяти"""
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
async def db_session(db_engine):
    """Сессия для тестовой БД"""
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session() as session:
        yield session

@pytest.fixture
def client(db_session, temp_dirs):
    """Тестовый клиент FastAPI"""
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
                                                                        
                                                                        # Подменяем зависимость БД
                                                                        async def override_get_db():
                                                                            yield db_session
                                                                        
                                                                        app.dependency_overrides[get_db] = override_get_db
                                                                        
                                                                        with TestClient(app) as test_client:
                                                                            yield test_client
                                                                        
                                                                        app.dependency_overrides.clear()

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
def client():
    """Фикстура для тестового клиента"""
    return TestClient(app)

@pytest.fixture
def mock_current_user():
    """Мок аутентифицированного пользователя"""
    user = MagicMock()
    user.sub = "test_doctor"
    user.role = "doctor"
    return user

@pytest.fixture
def mock_db_session():
    """Мок асинхронной сессии БД"""
    session = AsyncMock()
    return session

@pytest.fixture(autouse=True)
def override_dependencies(mock_current_user, mock_db_session):
    """Переопределение зависимостей для всех тестов"""
    # Переопределяем зависимости FastAPI
    app.dependency_overrides[get_current_doctor] = lambda: mock_current_user
    
    # Можно также переопределить get_db если нужно
    # app.dependency_overrides[get_db] = lambda: mock_db_session
    
    yield
    
    # Очищаем переопределения после теста
    app.dependency_overrides.clear()

# Останавливаем патчи в конце
def pytest_sessionfinish(session, exitstatus):
    for patcher in patches:
        try:
            patcher.stop()
        except:
            pass