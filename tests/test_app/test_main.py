# tests/test_app/test_main.py
import pytest
import jwt
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from app.core.config import settings

from app.main import (
    app,
    create_first_admin,
    ensure_admin_exists,
    lifespan,
    rate_limit_handler,
    set_user_context,   # добавляем для теста middleware
)


# ====================== LIFESPAN ======================
@pytest.mark.asyncio
async def test_lifespan_startup_shutdown(
    mock_core_functions, mock_cleanup_manager, mock_redis_global
):
    """Покрывает lifespan полностью"""
    mock_cleanup_manager.stop_cleanup_task = AsyncMock()

    async with lifespan(app):
        mock_core_functions["init_keys"].assert_awaited_once()
        mock_core_functions["check_redis"].assert_awaited_once()
        mock_cleanup_manager.start_cleanup_task.assert_awaited_once()
        mock_core_functions["create_admin"].assert_awaited_once()

    mock_cleanup_manager.stop_cleanup_task.assert_awaited_once()


# ====================== BASIC ======================
def test_app_creation():
    assert app.title == "SMDG"
    assert app.version == "1.0"


# ====================== ENDPOINTS ======================
def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200


def test_admin_page(client):
    response = client.get("/admin")
    assert response.status_code == 200


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_logs_page(client):
    Path("audit_logs").mkdir(exist_ok=True)
    (Path("audit_logs") / "test.log").write_text("test")
    response = client.get("/logs")
    assert response.status_code == 200
    assert "Логи аудита" in response.text


def test_admin_users_page(client):
    response = client.get("/admin/users")
    assert response.status_code == 200


def test_whoami(client, mock_current_user):
    response = client.get("/api/whoami")
    assert response.status_code == 200


# ====================== MIDDLEWARE set_user_context ======================
def test_set_user_context_valid_token(client):
    token = jwt.encode(
        {"sub": "123", "role": "doctor"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.cookies.set("access_token", token)
    response = client.get("/")
    client.cookies.clear()  # чистим после теста
    assert response.status_code == 200
    
def test_set_user_context_invalid_token(client):
    client.cookies.set("access_token", "invalid.token.here")
    response = client.get("/")
    client.cookies.clear()
    assert response.status_code == 200


def test_set_user_context_no_token(client):
    """Тест middleware без токена"""
    response = client.get("/")
    assert response.status_code == 200


# ====================== RATE LIMITER ======================
@pytest.mark.asyncio
async def test_rate_limit_handler():
    request = MagicMock(spec=Request)
    limit_mock = MagicMock()
    limit_mock.error_message = "Too Many Requests"
    exc = RateLimitExceeded(limit=limit_mock)

    response = await rate_limit_handler(request, exc)

    assert response.status_code == 429
    body_text = response.body.decode("utf-8")
    assert "Слишком много попыток" in body_text
    assert response.headers.get("Retry-After") == "60"


# ====================== ADMIN CREATION ======================
@pytest.mark.asyncio
async def test_create_first_admin(db_session):
    settings.dev_mode = True
    await create_first_admin()

    from sqlalchemy import select
    from app.models.user import User
    result = await db_session.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one_or_none()
    assert admin is not None
    assert admin.role == "admin"


@pytest.mark.asyncio
async def test_ensure_admin_exists(db_session):
    await ensure_admin_exists(db_session)

    from sqlalchemy import select
    from app.models.user import User
    result = await db_session.execute(select(User).where(User.username == "admin"))
    assert result.scalar_one_or_none() is not None


# ====================== FALLBACK HTML ======================


def test_index_fallback_when_file_missing(client, monkeypatch):
    """Покрывает except FileNotFoundError в index()"""
    # Патчим audit_logger, чтобы он не падал при попытке записи лога
    mock_audit = MagicMock()
    mock_audit.log_operation = MagicMock()
    
    with patch("app.core.middleware.audit_logger", mock_audit), \
         patch("builtins.open", side_effect=FileNotFoundError):
        
        response = client.get("/")
        assert response.status_code == 200
        assert "Ошибка" in response.text or "SMDG" in response.text


def test_admin_fallback_when_file_missing(client, monkeypatch):
    """Покрывает except FileNotFoundError в admin()"""
    mock_audit = MagicMock()
    mock_audit.log_operation = MagicMock()
    
    with patch("app.core.middleware.audit_logger", mock_audit), \
         patch("builtins.open", side_effect=FileNotFoundError):
        
        response = client.get("/admin")
        assert response.status_code == 200
        
# ====================== CUSTOM RATE LIMIT KEY FUNC ======================
def test_custom_key_func_with_user(client, monkeypatch):
    token = jwt.encode(
        {"sub": "999", "role": "doctor"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.cookies.set("access_token", token)
    with patch("app.main.logger.info"):
        response = client.get("/")
    client.cookies.clear()
    assert response.status_code == 200


def test_custom_key_func_without_user(client, monkeypatch):
    """Покрывает custom_key_func для анонима (по IP)"""
    with patch("app.main.logger.info"):
        response = client.get("/")
    assert response.status_code == 200


# ====================== ADD_RATE_LIMIT_HEADERS ======================
def test_add_rate_limit_headers_middleware(client):
    """Покрывает middleware add_rate_limit_headers"""
    response = client.get("/health")
    assert response.status_code == 200
    
# ====================== PRODUCTION MODE ADMIN ======================
@pytest.mark.asyncio
async def test_create_first_admin_in_production(db_session):
    """Покрывает ветку when not settings.dev_mode"""
    settings.dev_mode = False
    await create_first_admin()  # должно просто пропустить и ничего не создать


@pytest.mark.asyncio
async def test_ensure_admin_exists_in_production(db_session):
    """Покрывает ensure_admin_exists (уже покрыто, но усиливает)"""
    settings.dev_mode = False
    await ensure_admin_exists(db_session)


# ====================== LIFESPAN REDIS TEST BRANCH ======================
@pytest.mark.asyncio
async def test_lifespan_redis_error_handling(
    mock_core_functions, mock_cleanup_manager, mock_redis_global
):
    """Покрывает except в lifespan при ошибке Redis"""
    mock_redis_global.get.side_effect = Exception("Redis down")

    async with lifespan(app):
        pass  # главное — чтобы не упало приложение


# ====================== RATE LIMIT CUSTOM KEY ======================
def test_custom_key_func_anonymous(client, monkeypatch):
    """Покрывает else-ветку custom_key_func (аноним по IP)"""
    with patch("app.main.logger.info") as mock_log:
        response = client.get("/health")
        assert response.status_code == 200
        
        # Проверяем, что вызывался лог с анонимным ключом (с любым суффиксом)
        calls = [call[0][0] for call in mock_log.call_args_list]
        assert any("аноним → ключ rate_limit:ip:" in msg for msg in calls)


# ====================== ADD RATE LIMIT HEADERS ======================
def test_add_rate_limit_headers_middleware(client):
    """Покрывает middleware add_rate_limit_headers"""
    response = client.get("/health")
    assert response.status_code == 200
    