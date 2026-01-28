# tests/conftest_main.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Импортируем app ПЕРЕД моками
from app.main import app as original_app


@pytest.fixture
def test_client_no_startup():
    """Тестовый клиент без startup_event"""
    # Создаем копию приложения без startup_event
    test_app = original_app
    
    # Отключаем startup_event для тестов
    if hasattr(test_app.router, 'startup_event_functions'):
        test_app.router.startup_event_functions = []
    
    # Мокаем audit_logger чтобы избежать реального логирования
    with patch('app.main.audit_logger', MagicMock()):
        with patch('app.core.audit_logger', MagicMock()):
            with TestClient(test_app) as client:
                yield client


@pytest.fixture
def mock_app():
    """Полностью моканое приложение для тестов"""
    # Создаем новое приложение только для тестов
    from fastapi import FastAPI
    
    test_app = FastAPI()
    
    # Копируем основные маршруты из оригинального приложения
    for route in original_app.routes:
        test_app.routes.append(route)
    
    # Копируем mounted apps
    test_app.mount = original_app.mount
    
    # Копируем state
    test_app.state.limiter = MagicMock()
    
    # Отключаем все event handlers
    test_app.router.startup_event_functions = []
    test_app.router.shutdown_event_functions = []
    
    return test_app


@pytest.fixture
def client_without_startup(mock_app):
    """Клиент с моканым приложением без startup"""
    with TestClient(mock_app) as client:
        yield client


# Фикстуры для изолированных тестов функций
@pytest.fixture
async def mock_db_session():
    """Моканая сессия БД"""
    from unittest.mock import AsyncMock
    mock_session = AsyncMock()
    
    # Настраиваем базовые моки
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.refresh = AsyncMock()
    
    return mock_session


@pytest.fixture
def mock_settings():
    """Моканые настройки"""
    with patch('app.core.config.settings') as mock:
        mock.dev_mode = False
        mock.debug = False
        yield mock


# Event loop для async тестов
@pytest.fixture(scope="session")
def event_loop():
    """Event loop для сессии"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()