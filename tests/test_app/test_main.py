# tests/test_app/test_main.py
"""
Тесты для app/main.py

Фокус:
- ensure_admin_exists (новый админ, существующий валидный, существующий невалидный хэш)
- create_first_admin (dev и prod режимы)
- health_check (все сценарии директорий)
- базовые эндпоинты через TestClient (/, /admin, /health, /logs)
- обработчик ошибок rate limiting
- минимальная проверка startup и middleware

Запуск:
    pytest tests/test_app/test_main.py -v --cov=app.main --cov-report=term-missing
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from fastapi.testclient import TestClient
from fastapi import Request
from slowapi.errors import RateLimitExceeded

from app.main import (
    app,
    ensure_admin_exists,
    create_first_admin,
    health_check,
    index,
    admin,
    view_logs,
    safe_rate_limit_handler,
)


# =============================================================================
# Фикстуры
# =============================================================================

@pytest.fixture
def mock_session():
    """Правильный мок для AsyncSession — асинхронные методы awaitable"""
    session = AsyncMock()  # ← Вот здесь AsyncMock вместо MagicMock!

    # Результат выполнения запроса (тоже мок, но scalar_one_or_none обычно синхронный)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute.return_value = mock_result

    # commit и refresh — асинхронные, поэтому AsyncMock
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    # add — обычно синхронный в SQLAlchemy, оставляем MagicMock
    session.add = MagicMock()

    # Поддержка async with session.begin():
    transaction = AsyncMock()
    transaction.__aenter__ = AsyncMock(return_value=session)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=transaction)  # begin() сам синхронный, возвращает awaitable

    yield session


@pytest.fixture
def client():
    """Тестовый клиент с отключёнными тяжёлыми startup-действиями"""
    with patch("app.main.init_keys", AsyncMock()):
        with patch("app.main.cleanup_manager.start_cleanup_task", AsyncMock()):
            with patch("app.main.create_first_admin", AsyncMock()):
                yield TestClient(app)


# =============================================================================
# Тесты ensure_admin_exists
# =============================================================================


@pytest.mark.asyncio
async def test_ensure_admin_exists_prints_creation_message(mock_session, capsys):
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    await ensure_admin_exists(mock_session)

    captured = capsys.readouterr()
    assert "Создаём первого администратора" in captured.out
    assert "Админ создан" in captured.out
    
    
@pytest.mark.asyncio
async def test_create_first_admin_audit_log_called(mock_session):
    with patch("app.main.settings.dev_mode", True):
        with patch("app.main.AsyncSessionLocal") as mock_local:
            mock_local().__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = None

            with patch("app.main.audit_logger") as mock_audit:
                await create_first_admin()
                mock_audit.log_operation.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_admin_exists_new_admin_created(mock_session):
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    await ensure_admin_exists(mock_session)

    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()          # ← await здесь
    mock_session.refresh.assert_awaited_once()         # ← await здесь

    user = mock_session.add.call_args[0][0]
    assert user.username == "admin"
    assert user.role == "admin"
    assert user.is_active is True
    assert user.hashed_password.startswith("$argon2")


@pytest.mark.asyncio
async def test_ensure_admin_exists_already_exists_valid_hash_no_change(mock_session):
    existing = MagicMock()
    existing.hashed_password = "$argon2id$v=19$m=65536,t=3,p=4$valid"

    mock_session.execute.return_value.scalar_one_or_none.return_value = existing

    await ensure_admin_exists(mock_session)

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_admin_exists_invalid_hash_gets_rehashed(mock_session):
    existing = MagicMock()
    existing.hashed_password = "old_md5_or_plain"

    mock_session.execute.return_value.scalar_one_or_none.return_value = existing

    await ensure_admin_exists(mock_session)

    assert existing.hashed_password.startswith("$argon2")
    mock_session.commit.assert_awaited_once()


# =============================================================================
# Тесты create_first_admin
# =============================================================================

@pytest.mark.asyncio
async def test_create_first_admin_dev_mode_creates_user(mock_session):
    with patch("app.main.settings.dev_mode", True):
        with patch("app.main.AsyncSessionLocal") as mock_local:
            mock_local().__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = None

            await create_first_admin()

            mock_session.add.assert_called_once()
            mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_first_admin_prod_mode_skips(mock_session):
    with patch("app.main.settings.dev_mode", False):
        with patch("app.main.AsyncSessionLocal") as mock_local:
            await create_first_admin()
            mock_local.assert_not_called()


# =============================================================================
# Тесты health_check
# =============================================================================

@pytest.mark.asyncio
async def test_health_check_all_directories_exist():
    with patch("os.path.exists", return_value=True):
        result = await health_check()
        assert result["status"] == "healthy"
        assert all(result["directories"].values())


@pytest.mark.asyncio
async def test_health_check_no_directories_exist():
    with patch("os.path.exists", return_value=False):
        result = await health_check()
        assert result["status"] == "healthy"
        assert not any(result["directories"].values())


# =============================================================================
# Базовые эндпоинты через TestClient
# =============================================================================

def test_get_index_returns_html_or_fallback(client):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="<html>Secure Gateway</html>")):
            resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_get_admin_returns_html_or_fallback(client):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="<h1>Admin Panel</h1>")):
            resp = client.get("/admin")
    assert resp.status_code == 200


def test_get_health_returns_status_ok(client):
    with patch("os.path.exists", return_value=True):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_get_logs_page_renders_html(client):
    with patch("os.path.exists", return_value=True):
        with patch("os.listdir", return_value=["audit_2025-01-30.log"]):
            resp = client.get("/logs")
    assert resp.status_code == 200
    assert "Логи аудита SMDG" in resp.text


# =============================================================================
# Обработчик rate-limit ошибок
# =============================================================================

def test_safe_rate_limit_handler_handles_rle():
    mock_req = MagicMock(spec=Request)
    exc = RateLimitExceeded(MagicMock())

    with patch("app.main._rate_limit_exceeded_handler") as mock_handler:
        mock_handler.return_value = MagicMock(status_code=429)
        resp = safe_rate_limit_handler(mock_req, exc)
        assert resp.status_code == 429


def test_safe_rate_limit_handler_fallback_for_other_errors():
    mock_req = MagicMock(spec=Request)
    resp = safe_rate_limit_handler(mock_req, RuntimeError("boom"))

    assert resp.status_code == 429
    assert "Слишком много запросов" in resp.body.decode("utf-8")


# =============================================================================
# Минимальная проверка структуры приложения
# =============================================================================

def test_app_has_expected_metadata():
    assert app.title.startswith("Secure Medical Data Gateway")
    assert hasattr(app.state, "limiter")
    assert len(app.user_middleware) > 0


def test_app_has_rate_limit_exception_handler():
    from slowapi.errors import RateLimitExceeded
    assert RateLimitExceeded in app.exception_handlers
    
    
# =============================================================================
# Дополнительные тесты для 100% покрытия оставшихся строк
# =============================================================================

@pytest.mark.asyncio
async def test_create_first_admin_prints_success_message(mock_session, capsys):
    with patch("app.main.settings.dev_mode", True):
        with patch("app.main.AsyncSessionLocal") as mock_local:
            mock_local().__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = None

            await create_first_admin()

            captured = capsys.readouterr()
            assert "СОЗДАН ПЕРВЫЙ АДМИНИСТРАТОР" in captured.out
            assert "Измените пароль" in captured.out

@pytest.mark.asyncio
async def test_create_first_admin_logs_admin_created(mock_session):
    """Покрываем print и audit_logger в create_first_admin"""
    with patch("app.main.settings.dev_mode", True):
        with patch("app.main.AsyncSessionLocal") as mock_local:
            mock_local().__aenter__.return_value = mock_session
            mock_session.execute.return_value.scalar_one_or_none.return_value = None

            with patch("app.main.audit_logger") as mock_audit:
                await create_first_admin()

                # Если есть audit_logger.log_operation("system_init", ...)
                mock_audit.log_operation.assert_called()


@pytest.mark.asyncio
async def test_startup_event_calls_dependencies():
    """Минимальный тест startup_event — покрываем вызовы функций"""
    from app.main import startup_event

    with patch("app.main.init_keys", AsyncMock()) as mock_init:
        with patch("asyncio.create_task") as mock_task:
            with patch("app.main.cleanup_manager.start_cleanup_task", AsyncMock()):
                with patch("app.main.create_first_admin", AsyncMock()):
                    await startup_event()

                    mock_init.assert_called_once()
                    mock_task.assert_called_once()  # для cleanup_manager.start_cleanup_task
                    
                    
@pytest.mark.asyncio
async def test_ensure_admin_exists_handles_db_error(mock_session):
    mock_session.execute.side_effect = Exception("Database connection lost")

    with pytest.raises(Exception):
        await ensure_admin_exists(mock_session)


# Запуск тестов
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--cov=app.main", "--cov-report=term-missing"])
