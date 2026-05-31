"""
Тесты для app/api/auth.py
Покрытие: ~90-95% (все эндпоинты, все ветки ошибок, edge-cases)
"""
import base64

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import get_db
from app.core.auth import get_current_user


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def make_user(
    *,
    username="testuser",
    email="test@example.com",
    hashed_password="hashed_pw",
    role="user",
    is_active=True,
    otp_secret=None,
    otp_confirmed=True,
    id=1,
    tenant_id=1,
):
    """Создаёт мок-объект User.

    ``otp_confirmed`` по умолчанию True: когда тест задаёт ``otp_secret``,
    это означает полностью настроенную 2FA. Для сценария незавершённой
    настройки передайте ``otp_confirmed=False``.
    """
    user = MagicMock()
    user.id = id
    user.username = username
    user.email = email
    user.hashed_password = hashed_password
    user.role = role
    user.is_active = is_active
    user.otp_secret = otp_secret
    user.otp_confirmed = otp_confirmed
    user.tenant_id = tenant_id
    return user


def make_token_data(sub="testuser", role="doctor", tenant_id=1):
    """Создаёт мок TokenData (tenant_id нужен для assert_tenant_access в API)."""
    td = MagicMock()
    td.sub = sub
    td.role = role
    td.tenant_id = tenant_id
    return td


def override_current_user(sub="testuser", role="doctor"):
    """Возвращает override-функцию для get_current_user"""
    td = make_token_data(sub=sub, role=role)
    def _override():
        return td
    return _override


def make_mock_db(user=None):
    """
    Создаёт мок AsyncSession, где select(...).scalar_one_or_none() возвращает user.
    Поддерживает несколько последовательных вызовов через side_effect.
    """
    mock_db = AsyncMock(spec=AsyncSession)

    if isinstance(user, list):
        # Несколько последовательных вызовов execute
        results = []
        for u in user:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = u
            results.append(mock_result)
        mock_db.execute = AsyncMock(side_effect=results)
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


# ═══════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def base_client():
    """Базовый TestClient без override зависимостей (настраиваются в каждом тесте)"""
    yield TestClient(app)
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════
#  /auth/login
# ═══════════════════════════════════════════════════════════

class TestLogin:
    """Тесты для POST /auth/login"""

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.create_access_token", return_value="fake_jwt_token")
    @patch("app.api.auth.audit_logger")
    def test_login_success_no_2fa(self, mock_audit, mock_token, mock_verify, base_client):
        """Успешный логин без 2FA"""
        user = make_user(otp_secret=None)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "correctpass"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Успешный вход"
        assert data["username"] == "testuser"
        assert data["role"] == "user"
        assert data["2fa_enabled"] is False

        # Проверяем что cookie установлен
        assert "access_token" in response.cookies

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.create_access_token", return_value="fake_jwt_token")
    @patch("app.api.auth.audit_logger")
    def test_login_unconfirmed_2fa_does_not_require_code(
        self, mock_audit, mock_token, mock_verify, base_client
    ):
        """Секрет создан, но 2FA не подтверждена → вход без кода, форма не нужна."""
        user = make_user(otp_secret="JBSWY3DPEHPK3PXP", otp_confirmed=False)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "correctpass"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Успешный вход"
        assert data["2fa_enabled"] is False
        assert "access_token" in response.cookies

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.verify_otp_code", return_value=True)
    @patch("app.api.auth.create_access_token", return_value="fake_jwt_token")
    @patch("app.api.auth.audit_logger")
    def test_login_success_with_2fa(self, mock_audit, mock_token, mock_otp, mock_verify, base_client):
        """Успешный логин с 2FA"""
        user = make_user(otp_secret="JBSWY3DPEHPK3PXP")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "correctpass", "otp_code": "123456"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["2fa_enabled"] is True

    @patch("app.api.auth.audit_logger")
    def test_login_user_not_found(self, mock_audit, base_client):
        """Логин — пользователь не найден"""
        mock_db = make_mock_db(user=None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "nonexistent", "password": "pass"},
        )

        assert response.status_code == 401
        assert "Неверное имя пользователя или пароль" in response.json()["detail"]

    @patch("app.api.auth.audit_logger")
    def test_login_user_inactive(self, mock_audit, base_client):
        """Логин — пользователь деактивирован"""
        user = make_user(is_active=False)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "pass"},
        )

        assert response.status_code == 401

    @patch("app.api.auth.verify_password", return_value=False)
    @patch("app.api.auth.audit_logger")
    def test_login_wrong_password(self, mock_audit, mock_verify, base_client):
        """Логин — неверный пароль"""
        user = make_user()
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "wrongpass"},
        )

        assert response.status_code == 401
        assert "Неверное имя пользователя или пароль" in response.json()["detail"]

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.audit_logger")
    def test_login_2fa_required_but_not_provided(self, mock_audit, mock_verify, base_client):
        """Логин — 2FA включён, но код не передан"""
        user = make_user(otp_secret="JBSWY3DPEHPK3PXP")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "correctpass"},
        )

        assert response.status_code == 400
        assert "Требуется код 2FA" in response.json()["detail"]

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.verify_otp_code", return_value=False)
    @patch("app.api.auth.audit_logger")
    def test_login_2fa_wrong_code(self, mock_audit, mock_otp, mock_verify, base_client):
        """Логин — неверный код 2FA"""
        user = make_user(otp_secret="JBSWY3DPEHPK3PXP")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "correctpass", "otp_code": "000000"},
        )

        assert response.status_code == 401
        assert "Неверный код 2FA" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════
#  /auth/logout
# ═══════════════════════════════════════════════════════════

class TestLogout:
    """Тесты для POST /api/auth/logout"""

    def test_logout_success(self, base_client):
        """Успешный выход"""
        response = base_client.post("/api/auth/logout")

        assert response.status_code == 200
        assert response.json()["message"] == "Вы успешно вышли из системы"

        # Cookie должен быть удалён (max_age=0 или отсутствует)
        cookie_header = response.headers.get("set-cookie", "")
        assert "access_token" in cookie_header


# ═══════════════════════════════════════════════════════════
#  /auth/change-password
# ═══════════════════════════════════════════════════════════

class TestChangePassword:
    """Тесты для POST /auth/change-password"""

    @patch("app.api.auth.verify_password", side_effect=[True, False])  # old=True, new≠old=False
    @patch("app.api.auth.get_password_hash", return_value="new_hashed_pw")
    @patch("app.api.auth.generate_otp_secret", return_value="NEWSECRET123")
    @patch("app.api.auth.audit_logger")
    def test_change_password_success_no_2fa(
        self, mock_audit, mock_otp_gen, mock_hash, mock_verify, base_client
    ):
        """Успешная смена пароля (без 2FA)"""
        user = make_user(otp_secret=None)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={"old_password": "oldpass123", "new_password": "newpass456"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Пароль успешно изменён"
        assert "otp_secret" in data
        assert "otp_url" in data

    @patch("app.api.auth.verify_password", side_effect=[True, False])
    @patch("app.api.auth.verify_otp_code", return_value=True)
    @patch("app.api.auth.get_password_hash", return_value="new_hashed_pw")
    @patch("app.api.auth.generate_otp_secret", return_value="NEWSECRET123")
    @patch("app.api.auth.audit_logger")
    def test_change_password_success_with_2fa(
        self, mock_audit, mock_otp_gen, mock_hash, mock_otp_verify, mock_verify, base_client
    ):
        """Успешная смена пароля (с 2FA)"""
        user = make_user(otp_secret="OLDSECRET")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={
                "old_password": "oldpass123",
                "new_password": "newpass456",
                "otp_code": "123456",
            },
        )

        assert response.status_code == 200

    @patch("app.api.auth.audit_logger")
    def test_change_password_user_not_found(self, mock_audit, base_client):
        """Смена пароля — пользователь не найден"""
        mock_db = make_mock_db(user=None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={"old_password": "oldpass123", "new_password": "newpass456"},
        )

        assert response.status_code == 404
        assert "Пользователь не найден" in response.json()["detail"]

    @patch("app.api.auth.verify_password", return_value=False)
    @patch("app.api.auth.audit_logger")
    def test_change_password_wrong_old_password(self, mock_audit, mock_verify, base_client):
        """Смена пароля — неверный старый пароль"""
        user = make_user()
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={"old_password": "wrongold", "new_password": "newpass456"},
        )

        assert response.status_code == 401
        assert "Неверный текущий пароль" in response.json()["detail"]

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.audit_logger")
    def test_change_password_2fa_required_but_missing(self, mock_audit, mock_verify, base_client):
        """Смена пароля — 2FA включён, код не передан"""
        user = make_user(otp_secret="SECRET123")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={"old_password": "oldpass123", "new_password": "newpass456"},
        )

        assert response.status_code == 400
        assert "Требуется код 2FA" in response.json()["detail"]

    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.verify_otp_code", return_value=False)
    @patch("app.api.auth.audit_logger")
    def test_change_password_2fa_wrong_code(self, mock_audit, mock_otp, mock_verify, base_client):
        """Смена пароля — неверный код 2FA"""
        user = make_user(otp_secret="SECRET123")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={
                "old_password": "oldpass123",
                "new_password": "newpass456",
                "otp_code": "000000",
            },
        )

        assert response.status_code == 401
        assert "Неверный код 2FA" in response.json()["detail"]

    @patch("app.api.auth.verify_password", side_effect=[True, True])  # old=True, new==old=True
    @patch("app.api.auth.audit_logger")
    def test_change_password_same_as_old(self, mock_audit, mock_verify, base_client):
        """Смена пароля — новый совпадает со старым"""
        user = make_user(otp_secret=None)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/change-password",
            json={"old_password": "samepass1", "new_password": "samepass1"},
        )

        assert response.status_code == 400
        assert "Новый пароль не должен совпадать со старым" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════
#  /auth/setup-2fa
# ═══════════════════════════════════════════════════════════

class TestSetup2FA:
    """Тесты для POST /auth/setup-2fa"""

    @patch("app.api.auth.generate_otp_secret", return_value="NEWSECRET123")
    @patch("app.api.auth.get_otp_url", return_value="otpauth://totp/SMDG:testuser?secret=NEWSECRET123")
    @patch("app.api.auth.audit_logger")
    def test_setup_2fa_success(self, mock_audit, mock_url, mock_secret, base_client):
        """Успешная настройка 2FA"""
        user = make_user()
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post("/api/auth/setup-2fa")

        assert response.status_code == 200
        data = response.json()
        assert "otp_url" in data
        assert "instructions" in data
        assert len(data["instructions"]) == 4

    @patch("app.api.auth.audit_logger")
    def test_setup_2fa_user_not_found(self, mock_audit, base_client):
        """Настройка 2FA — пользователь не найден"""
        mock_db = make_mock_db(user=None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post("/api/auth/setup-2fa")

        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════
#  /auth/verify-2fa-setup
# ═══════════════════════════════════════════════════════════

class TestVerify2FASetup:
    """Тесты для POST /auth/verify-2fa-setup"""

    @patch("app.api.auth.verify_otp_code", return_value=True)
    @patch("app.api.auth.audit_logger")
    def test_verify_2fa_success(self, mock_audit, mock_otp, base_client):
        """Успешная верификация 2FA"""
        user = make_user(otp_secret="SECRET123")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/verify-2fa-setup",
            json={"code": "123456"},
        )

        assert response.status_code == 200
        assert "успешно" in response.json()["message"].lower()

    @patch("app.api.auth.verify_otp_code", return_value=False)
    @patch("app.api.auth.audit_logger")
    def test_verify_2fa_wrong_code(self, mock_audit, mock_otp, base_client):
        """Верификация 2FA — неверный код"""
        user = make_user(otp_secret="SECRET123")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/verify-2fa-setup",
            json={"code": "000000"},
        )

        assert response.status_code == 400
        assert "Неверный код" in response.json()["detail"]

    @patch("app.api.auth.audit_logger")
    def test_verify_2fa_user_not_found(self, mock_audit, base_client):
        """Верификация 2FA — пользователь не найден"""
        mock_db = make_mock_db(user=None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/verify-2fa-setup",
            json={"code": "123456"},
        )

        assert response.status_code == 404

    @patch("app.api.auth.audit_logger")
    def test_verify_2fa_not_setup(self, mock_audit, base_client):
        """Верификация 2FA — 2FA ещё не настроена"""
        user = make_user(otp_secret=None)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/verify-2fa-setup",
            json={"code": "123456"},
        )

        assert response.status_code == 400
        assert "не настроена" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════
#  /auth/disable-2fa
# ═══════════════════════════════════════════════════════════

class TestDisable2FA:
    """Тесты для POST /auth/disable-2fa"""

    @patch("app.api.auth.verify_otp_code", return_value=True)
    @patch("app.api.auth.audit_logger")
    def test_disable_2fa_success(self, mock_audit, mock_otp, base_client):
        """Успешное отключение 2FA"""
        user = make_user(otp_secret="SECRET123")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/disable-2fa",
            data={"otp_code": "123456"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "успешно" in data["message"].lower()
        assert "warning" in data

    @patch("app.api.auth.audit_logger")
    def test_disable_2fa_user_not_found(self, mock_audit, base_client):
        """Отключение 2FA — пользователь не найден"""
        mock_db = make_mock_db(user=None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/disable-2fa",
            data={"otp_code": "123456"},
        )

        assert response.status_code == 404

    @patch("app.api.auth.audit_logger")
    def test_disable_2fa_not_enabled(self, mock_audit, base_client):
        """Отключение 2FA — 2FA не включён"""
        user = make_user(otp_secret=None)
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/disable-2fa",
            data={"otp_code": "123456"},
        )

        assert response.status_code == 400
        assert "не включен" in response.json()["detail"].lower()

    @patch("app.api.auth.verify_otp_code", return_value=False)
    @patch("app.api.auth.audit_logger")
    def test_disable_2fa_wrong_code(self, mock_audit, mock_otp, base_client):
        """Отключение 2FA — неверный код"""
        user = make_user(otp_secret="SECRET123")
        mock_db = make_mock_db(user=user)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user()

        response = base_client.post(
            "/api/auth/disable-2fa",
            data={"otp_code": "000000"},
        )

        assert response.status_code == 401
        assert "Неверный код 2FA" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════
#  /auth/register
# ═══════════════════════════════════════════════════════════

class TestRegister:
    """Тесты для POST /auth/register"""

    @patch("app.api.auth.get_password_hash", return_value="hashed_new_pw")
    @patch("app.api.auth.generate_otp_secret", return_value="REGSECRET123")
    @patch("app.api.auth.audit_logger")
    def test_register_success(self, mock_audit, mock_otp, mock_hash, base_client):
        """Успешная регистрация"""
        # Два вызова execute: проверка username (None) и проверка email (None)
        mock_db = make_mock_db(user=[None, None])
        # refresh должен работать
        mock_db.refresh = AsyncMock()

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "strongpass123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Пользователь успешно зарегистрирован"
        assert data["username"] == "newuser"
        assert data["email"] == "new@example.com"
        assert data["role"] == "user"
        assert "otp_secret" in data
        assert "otp_url" in data
        assert data["2fa_enabled"] is False

    @patch("app.api.auth.audit_logger")
    def test_register_duplicate_username(self, mock_audit, base_client):
        """Регистрация — username уже занят"""
        existing_user = make_user(username="existing")
        mock_db = make_mock_db(user=existing_user)  # первый execute вернёт юзера

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/register",
            json={
                "username": "existing",
                "email": "new@example.com",
                "password": "strongpass123",
            },
        )

        assert response.status_code == 400
        assert "логином" in response.json()["detail"].lower()

    @patch("app.api.auth.audit_logger")
    def test_register_duplicate_email(self, mock_audit, base_client):
        """Регистрация — email уже занят"""
        existing_user = make_user(email="taken@example.com")
        # Первый execute (username) → None, второй (email) → existing
        mock_db = make_mock_db(user=[None, existing_user])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        response = base_client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "taken@example.com",
                "password": "strongpass123",
            },
        )

        assert response.status_code == 400
        assert "email" in response.json()["detail"].lower()

    def test_register_invalid_username_format(self, base_client):
        """Регистрация — невалидный формат username"""
        response = base_client.post(
            "/api/auth/register",
            json={
                "username": "user with spaces!",
                "email": "test@example.com",
                "password": "strongpass123",
            },
        )

        assert response.status_code == 422  # Pydantic validation

    def test_register_short_password(self, base_client):
        """Регистрация — слишком короткий пароль"""
        response = base_client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "test@example.com",
                "password": "short",
            },
        )

        assert response.status_code == 422

    def test_register_short_username(self, base_client):
        """Регистрация — слишком короткий username"""
        response = base_client.post(
            "/api/auth/register",
            json={
                "username": "ab",
                "email": "test@example.com",
                "password": "strongpass123",
            },
        )

        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════
#  UNIT-тесты утилитных функций
# ═══════════════════════════════════════════════════════════

class TestUtilityFunctions:
    """Тесты для вспомогательных функций в auth.py"""

    def test_generate_otp_secret(self):
        """generate_otp_secret возвращает валидный base32 строку"""
        from app.api.auth import generate_otp_secret

        secret = generate_otp_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 16
        # Проверяем что это валидный base32
        base64.b32decode(secret)

    def test_get_otp_url(self):
        """get_otp_url формирует корректный provisioning URI"""
        from app.api.auth import get_otp_url

        url = get_otp_url("testuser", "JBSWY3DPEHPK3PXP")
        assert "otpauth://totp/" in url
        assert "testuser" in url
        assert "SMDG" in url  # issuer_name

    def test_get_otp_url_custom_issuer(self):
        """get_otp_url с кастомным issuer"""
        from app.api.auth import get_otp_url

        url = get_otp_url("user1", "SECRET", issuer_name="MyApp")
        assert "MyApp" in url

    def test_verify_otp_code_valid(self):
        """verify_otp_code — валидный код"""
        from app.api.auth import verify_otp_code
        import pyotp

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()

        assert verify_otp_code(secret, code) is True

    def test_verify_otp_code_invalid(self):
        """verify_otp_code — невалидный код"""
        from app.api.auth import verify_otp_code
        import pyotp

        secret = pyotp.random_base32()
        assert verify_otp_code(secret, "000000") is False

    def test_verify_otp_code_empty_secret(self):
        """verify_otp_code — пустой секрет"""
        from app.api.auth import verify_otp_code

        assert verify_otp_code("", "123456") is False
        assert verify_otp_code(None, "123456") is False

    def test_verify_otp_code_empty_code(self):
        """verify_otp_code — пустой код"""
        from app.api.auth import verify_otp_code

        assert verify_otp_code("JBSWY3DPEHPK3PXP", "") is False
        assert verify_otp_code("JBSWY3DPEHPK3PXP", None) is False


# ═══════════════════════════════════════════════════════════
#  PYDANTIC VALIDATION
# ═══════════════════════════════════════════════════════════

class TestPydanticModels:
    """Тесты валидации Pydantic моделей"""

    def test_change_password_request_valid(self):
        from app.api.auth import ChangePasswordRequest

        req = ChangePasswordRequest(
            old_password="oldpass1",
            new_password="newpass12",
            otp_code="123456",
        )
        assert req.old_password == "oldpass1"
        assert req.new_password == "newpass12"
        assert req.otp_code == "123456"

    def test_change_password_request_without_otp(self):
        from app.api.auth import ChangePasswordRequest

        req = ChangePasswordRequest(
            old_password="oldpass1",
            new_password="newpass12",
        )
        assert req.otp_code is None

    def test_change_password_request_short_new_password(self):
        from app.api.auth import ChangePasswordRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChangePasswordRequest(
                old_password="oldpass1",
                new_password="short",
            )

    def test_login_request_valid(self):
        from app.api.auth import LoginRequest

        req = LoginRequest(username="user1", password="pass123")
        assert req.username == "user1"

    def test_register_request_valid(self):
        from app.api.auth import RegisterRequest

        req = RegisterRequest(
            username="valid_user",
            email="test@example.com",
            password="longpassword123",
        )
        assert req.username == "valid_user"

    def test_register_request_invalid_username(self):
        from app.api.auth import RegisterRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RegisterRequest(
                username="invalid user!",
                email="test@example.com",
                password="longpassword123",
            )

    def test_verify_2fa_request_valid(self):
        from app.api.auth import Verify2FARequest

        req = Verify2FARequest(code="123456")
        assert req.code == "123456"

    def test_verify_2fa_request_short_code(self):
        from app.api.auth import Verify2FARequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Verify2FARequest(code="123")

    def test_verify_2fa_request_long_code(self):
        from app.api.auth import Verify2FARequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Verify2FARequest(code="1234567")

