# tests/test_api/test_admin_users.py
"""
Тесты для /api/admin/users/* эндпоинтов.
Целевое покрытие: 90-95% (app/api/admin_users.py)

Маршруты:
  GET    /api/admin/users/                       — список пользователей
  GET    /api/admin/users/{user_id}              — один пользователь
  POST   /api/admin/users/                       — создать пользователя
  PUT    /api/admin/users/{user_id}              — обновить пользователя
  DELETE /api/admin/users/{user_id}              — удалить пользователя
  POST   /api/admin/users/{user_id}/reset-password — сброс пароля
  POST   /api/admin/users/bulk                   — массовые операции
  GET    /api/admin/users/stats/overview         — статистика
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import status
from httpx import AsyncClient, ASGITransport

from app.core.auth import TokenData


# ─────────────────────────────────────────────────────────────
#  URL-константы
# ─────────────────────────────────────────────────────────────
BASE = "/api/admin/users"


# ─────────────────────────────────────────────────────────────
#  Фикстуры — токены
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def admin_token():
    return TokenData(sub="admin", role="admin", tenant_id=1)


# ─────────────────────────────────────────────────────────────
#  Фабрика мок-пользователей
# ─────────────────────────────────────────────────────────────

def _make_user(
    id: int = 1,
    username: str = "testuser",
    email: str = "test@example.com",
    role: str = "user",
    is_active: bool = True,
    otp_secret: str | None = None,
    hashed_password: str = "hashed",
    tenant_id: int = 1,
):
    u = MagicMock()
    u.id = id
    u.username = username
    u.email = email
    u.role = role
    u.is_active = is_active
    u.otp_secret = otp_secret
    u.hashed_password = hashed_password
    u.tenant_id = tenant_id
    return u


# ─────────────────────────────────────────────────────────────
#  Вспомогательные функции для сессии и dependency overrides
# ─────────────────────────────────────────────────────────────

def _scalar_result(obj):
    r = MagicMock()
    r.scalar_one_or_none.return_value = obj
    return r


def _scalars_result(objs: list):
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = objs
    r.scalars.return_value = scalars
    r.scalar_one.return_value = len(objs)
    return r


def _make_session(*side_effects) -> AsyncMock:
    """
    Возвращает мок сессии.
    side_effects — последовательность возвращаемых значений execute().
    Если один аргумент — используется как return_value.
    """
    session = AsyncMock()
    if len(side_effects) == 1:
        session.execute = AsyncMock(return_value=side_effects[0])
    else:
        session.execute = AsyncMock(side_effect=list(side_effects))
    return session


def _override(app, token: TokenData, session: AsyncMock):
    from app.core.auth import get_current_admin
    from app.core.database import get_db

    async def _auth():
        return token

    async def _db():
        yield session

    app.dependency_overrides[get_current_admin] = _auth
    app.dependency_overrides[get_db] = _db


def _clear(app):
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
#  GET /api/admin/users/  — список пользователей
# ═══════════════════════════════════════════════════════════════

class TestGetAllUsers:

    @pytest.mark.asyncio
    async def test_returns_user_list(self, admin_token):
        from app.main import app
        users = [_make_user(1, "alice", otp_secret="SECRETKEY"), _make_user(2, "bob")]
        session = _make_session(_scalars_result(users))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/")
            assert resp.status_code == status.HTTP_200_OK
            body = resp.json()
            assert len(body) == 2
            assert "otp_secret" not in body[0]
            assert body[0]["has_2fa"] is True
            assert body[1]["has_2fa"] is False
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_empty_list(self, admin_token):
        from app.main import app
        session = _make_session(_scalars_result([]))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/")
            assert resp.status_code == status.HTTP_200_OK
            assert resp.json() == []
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_search_filter(self, admin_token):
        """search параметр передаётся — запрос выполняется без ошибок"""
        from app.main import app
        session = _make_session(_scalars_result([_make_user(1, "alice")]))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/", params={"search": "alice"})
            assert resp.status_code == status.HTTP_200_OK
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_role_filter(self, admin_token):
        from app.main import app
        session = _make_session(_scalars_result([_make_user(role="doctor")]))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/", params={"role": "doctor"})
            assert resp.status_code == status.HTTP_200_OK
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_active_only_filter(self, admin_token):
        from app.main import app
        session = _make_session(_scalars_result([_make_user(is_active=True)]))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/", params={"active_only": True})
            assert resp.status_code == status.HTTP_200_OK
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_pagination_params(self, admin_token):
        from app.main import app
        session = _make_session(_scalars_result([]))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/", params={"skip": 10, "limit": 5})
            assert resp.status_code == status.HTTP_200_OK
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_audit_logged(self, admin_token):
        from app.main import app
        session = _make_session(_scalars_result([]))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.get(f"{BASE}/")
            mock_audit.log_operation.assert_called_once()
            assert mock_audit.log_operation.call_args.kwargs["action"] == "admin_view_users"
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  GET /api/admin/users/{user_id}  — один пользователь
# ═══════════════════════════════════════════════════════════════

class TestGetUser:

    @pytest.mark.asyncio
    async def test_returns_user(self, admin_token):
        from app.main import app
        user = _make_user(42, "alice", "alice@example.com", "doctor", otp_secret="SECRETKEY")
        session = _make_session(_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/42")
            assert resp.status_code == status.HTTP_200_OK
            body = resp.json()
            assert body["id"] == 42
            assert body["username"] == "alice"
            assert "otp_secret" not in body
            assert body["has_2fa"] is True
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_user_not_found(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(f"{BASE}/9999")
            assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_audit_logged(self, admin_token):
        from app.main import app
        user = _make_user(1)
        session = _make_session(_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.get(f"{BASE}/1")
            assert mock_audit.log_operation.call_args.kwargs["action"] == "admin_view_user"
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  POST /api/admin/users/  — создать пользователя
# ═══════════════════════════════════════════════════════════════

class TestCreateUser:

    _payload = {
        "username": "newuser",
        "email": "newuser@example.com",
        "password": "securepass123",
        "role": "user",
        "is_active": True,
    }

    @pytest.mark.asyncio
    async def test_create_success(self, admin_token):
        from app.main import app
        new_user = _make_user(10, "newuser", "newuser@example.com", "user")
        # execute: проверка username → None, проверка email → None
        # после commit/refresh возвращается new_user
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),   # username свободен
            _scalar_result(None),   # email свободен
        ])
        session.refresh = AsyncMock(side_effect=lambda u: setattr(u, "id", 10) or None)
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"), \
                 patch("app.api.admin_users.get_password_hash", return_value="hashed"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/", json=self._payload)
            assert resp.status_code == status.HTTP_201_CREATED
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_duplicate_username(self, admin_token):
        from app.main import app
        existing = _make_user(5, "newuser")
        session = _make_session(_scalar_result(existing))   # username занят
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/", json=self._payload)
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "логином" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_duplicate_email(self, admin_token):
        from app.main import app
        existing_email_user = _make_user(6, "other", "newuser@example.com")
        session = _make_session(
            _scalar_result(None),          # username свободен
            _scalar_result(existing_email_user),  # email занят
        )
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/", json=self._payload)
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "email" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_payload,expected_field", [
        ({"username": "ab", "email": "x@x.com", "password": "pass1234"}, "username"),   # too short
        ({"username": "valid", "email": "not-an-email", "password": "pass1234"}, "email"),
        ({"username": "valid", "email": "x@x.com", "password": "short"}, "password"),   # too short
        ({"username": "inv alid!", "email": "x@x.com", "password": "pass1234"}, "username"),  # bad chars
    ])
    async def test_invalid_payload(self, bad_payload, expected_field, admin_token):
        from app.main import app
        _override(app, admin_token, _make_session(_scalar_result(None)))
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/", json=bad_payload)
            assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_create_doctor_role(self, admin_token):
        from app.main import app
        payload = {**self._payload, "username": "dr_house", "email": "dr@example.com", "role": "doctor"}
        new_user = _make_user(11, "dr_house", "dr@example.com", "doctor")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[_scalar_result(None), _scalar_result(None)])
        session.refresh = AsyncMock(side_effect=lambda u: setattr(u, "id", 11) or None)
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"), \
                 patch("app.api.admin_users.get_password_hash", return_value="hashed"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/", json=payload)
            assert resp.status_code == status.HTTP_201_CREATED
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_audit_logged_on_create(self, admin_token):
        from app.main import app
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[_scalar_result(None), _scalar_result(None)])
        session.refresh = AsyncMock(side_effect=lambda u: setattr(u, "id", 99) or None)
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger") as mock_audit, \
                 patch("app.api.admin_users.get_password_hash", return_value="hashed"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post(f"{BASE}/", json=self._payload)
            assert mock_audit.log_operation.call_args.kwargs["action"] == "admin_create_user"
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  PUT /api/admin/users/{user_id}  — обновить пользователя
# ═══════════════════════════════════════════════════════════════

class TestUpdateUser:

    @pytest.mark.asyncio
    async def test_user_not_found(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(f"{BASE}/9999", json={"role": "doctor"})
            assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_cannot_update_self(self, admin_token):
        """Админ не может менять свою учётку через этот эндпоинт"""
        from app.main import app
        # user.username совпадает с current_admin.sub ("admin")
        self_user = _make_user(1, "admin", role="admin")
        session = _make_session(_scalar_result(self_user))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(f"{BASE}/1", json={"role": "user"})
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "change-password" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_update_role(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", role="user")
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_scalar_result(user))
        session.refresh = AsyncMock()
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.put(f"{BASE}/5", json={"role": "doctor"})
            assert resp.status_code == status.HTTP_200_OK
            assert user.role == "doctor"
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_update_is_active(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", is_active=True)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_scalar_result(user))
        session.refresh = AsyncMock()
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.put(f"{BASE}/5", json={"is_active": False})
            assert resp.status_code == status.HTTP_200_OK
            assert user.is_active is False
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_update_email_success(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", email="old@example.com")
        # execute: найти юзера, проверить уникальность нового email
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(user),
            _scalar_result(None),   # новый email свободен
        ])
        session.refresh = AsyncMock()
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.put(f"{BASE}/5", json={"email": "new@example.com"})
            assert resp.status_code == status.HTTP_200_OK
            assert user.email == "new@example.com"
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_update_email_duplicate(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", email="old@example.com")
        duplicate = _make_user(7, "carol", email="new@example.com")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(user),
            _scalar_result(duplicate),  # email занят другим пользователем
        ])
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put(f"{BASE}/5", json={"email": "new@example.com"})
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "email" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_reset_password(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob")
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_scalar_result(user))
        session.refresh = AsyncMock()
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"), \
                 patch("app.api.admin_users.get_password_hash", return_value="newhash"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.put(f"{BASE}/5", json={"reset_password": True, "new_password": "newpassword123"})
            assert resp.status_code == status.HTTP_200_OK
            assert user.hashed_password == "newhash"
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_reset_2fa(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", otp_secret="SECRETKEY")
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_scalar_result(user))
        session.refresh = AsyncMock()
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.put(f"{BASE}/5", json={"reset_2fa": True})
            assert resp.status_code == status.HTTP_200_OK
            assert user.otp_secret is None
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_no_changes_no_commit(self, admin_token):
        """Если нет изменений — commit не вызывается"""
        from app.main import app
        user = _make_user(5, "bob", email="bob@example.com", role="user", is_active=True)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    # Отправляем те же значения — изменений нет
                    resp = await ac.put(f"{BASE}/5", json={})
            assert resp.status_code == status.HTTP_200_OK
            session.commit.assert_not_called()
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  DELETE /api/admin/users/{user_id}  — удалить пользователя
# ═══════════════════════════════════════════════════════════════

class TestDeleteUser:

    @pytest.mark.asyncio
    async def test_requires_confirm(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete(f"{BASE}/1")   # confirm=False по умолчанию
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "подтверждение" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_user_not_found(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete(f"{BASE}/9999?confirm=true")
            assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_cannot_delete_self(self, admin_token):
        from app.main import app
        self_user = _make_user(1, "admin", role="admin")
        session = _make_session(_scalar_result(self_user))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete(f"{BASE}/1?confirm=true")
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "свою" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_cannot_delete_last_admin(self, admin_token):
        from app.main import app
        last_admin = _make_user(2, "other_admin", role="admin")
        admins_list = [last_admin]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(last_admin),      # найти пользователя
            _scalars_result(admins_list),    # список всех админов — один
        ])
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete(f"{BASE}/2?confirm=true")
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "последнего" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_delete_admin_when_multiple_exist(self, admin_token):
        """Можно удалить не-последнего админа"""
        from app.main import app
        target_admin = _make_user(2, "second_admin", role="admin")
        admin_list = [target_admin, _make_user(3, "third_admin", role="admin")]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target_admin),
            _scalars_result(admin_list),
        ])
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete(f"{BASE}/2?confirm=true")
            assert resp.status_code == status.HTTP_200_OK
            assert "second_admin" in resp.json()["message"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_delete_regular_user(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", role="user")
        session = _make_session(_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete(f"{BASE}/5?confirm=true")
            assert resp.status_code == status.HTTP_200_OK
            assert "bob" in resp.json()["message"]
            session.delete.assert_called_once_with(user)
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_audit_logged(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob", role="user")
        session = _make_session(_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.delete(f"{BASE}/5?confirm=true")
            assert mock_audit.log_operation.call_args.kwargs["action"] == "admin_delete_user"
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  POST /api/admin/users/{user_id}/reset-password
# ═══════════════════════════════════════════════════════════════

class TestResetUserPassword:

    @pytest.mark.asyncio
    async def test_reset_success(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob")
        session = _make_session(_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"), \
                 patch("app.api.admin_users.get_password_hash", return_value="newhash"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/5/reset-password", json={"new_password": "newpass1234"})
            assert resp.status_code == status.HTTP_200_OK
            assert "bob" in resp.json()["message"]
            assert user.hashed_password == "newhash"
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_user_not_found(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/9999/reset-password", json={"new_password": "newpass1234"})
            assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_cannot_reset_own_password(self, admin_token):
        from app.main import app
        self_user = _make_user(1, "admin")
        session = _make_session(_scalar_result(self_user))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/1/reset-password", json={"new_password": "newpass1234"})
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "change-password" in resp.json()["detail"]
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_short_password_rejected(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/5/reset-password", json={"new_password": "short"})
            assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_audit_logged(self, admin_token):
        from app.main import app
        user = _make_user(5, "bob")
        session = _make_session(_scalar_result(user))
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger") as mock_audit, \
                 patch("app.api.admin_users.get_password_hash", return_value="h"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post(f"{BASE}/5/reset-password", json={"new_password": "newpass1234"})
            assert mock_audit.log_operation.call_args.kwargs["action"] == "admin_reset_password"
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  POST /api/admin/users/bulk  — массовые операции
# ═══════════════════════════════════════════════════════════════

class TestBulkUserActions:

    def _bulk(self, action: str, user_ids: list = None, role: str = None) -> dict:
        payload = {"action": action, "user_ids": user_ids or [1, 2, 3]}
        if role:
            payload["role"] = role
        return payload

    def _update_result(self, rowcount: int = 3):
        r = MagicMock()
        r.rowcount = rowcount
        return r

    # ── пустой список user_ids ──────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_user_ids(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json={"action": "activate", "user_ids": []})
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "пользователи" in resp.json()["detail"].lower()
        finally:
            _clear(app)

    # ── попытка изменить себя ───────────────────────────────

    @pytest.mark.asyncio
    async def test_cannot_bulk_self(self, admin_token):
        from app.main import app
        self_user = _make_user(1, "admin")
        session = _make_session(_scalar_result(self_user))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json=self._bulk("activate", [1]))
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "своей" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── activate ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_bulk_activate(self, admin_token):
        from app.main import app
        update_res = self._update_result(3)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),   # self check
            update_res,             # UPDATE
        ])
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/bulk", json=self._bulk("activate"))
            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["affected_count"] == 3
        finally:
            _clear(app)

    # ── deactivate — нет админов в списке ───────────────────

    @pytest.mark.asyncio
    async def test_bulk_deactivate_success(self, admin_token):
        from app.main import app
        update_res = self._update_result(2)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),       # self check
            _scalar_result(None),       # нет админов среди выбранных
            update_res,
        ])
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/bulk", json=self._bulk("deactivate"))
            assert resp.status_code == status.HTTP_200_OK
        finally:
            _clear(app)

    # ── deactivate — есть админы → 400 ──────────────────────

    @pytest.mark.asyncio
    async def test_bulk_deactivate_admins_blocked(self, admin_token):
        from app.main import app
        admin_user = _make_user(2, "other_admin", role="admin")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),
            _scalars_result([admin_user]),   # есть админы
        ])
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json=self._bulk("deactivate", [2]))
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "администраторов" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── change_role — без указания роли ─────────────────────

    @pytest.mark.asyncio
    async def test_bulk_change_role_no_role(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json={"action": "change_role", "user_ids": [1, 2]})
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "роль" in resp.json()["detail"].lower()
        finally:
            _clear(app)

    # ── change_role — есть админы → 400 ─────────────────────

    @pytest.mark.asyncio
    async def test_bulk_change_role_admins_blocked(self, admin_token):
        from app.main import app
        admin_user = _make_user(2, "other_admin", role="admin")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),
            _scalars_result([admin_user]),
        ])
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json=self._bulk("change_role", [2], role="user"))
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "администраторов" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── change_role — успех ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_bulk_change_role_success(self, admin_token):
        from app.main import app
        update_res = self._update_result(2)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),
            _scalar_result(None),  # нет админов среди выбранных
            update_res,
        ])
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/bulk", json=self._bulk("change_role", role="doctor"))
            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["affected_count"] == 2
        finally:
            _clear(app)

    # ── delete — есть админы → 400 ──────────────────────────

    @pytest.mark.asyncio
    async def test_bulk_delete_admins_blocked(self, admin_token):
        from app.main import app
        admin_user = _make_user(2, "other_admin", role="admin")
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),
            _scalars_result([admin_user]),
        ])
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json=self._bulk("delete", [2]))
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "администраторов" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── delete — успех ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_bulk_delete_success(self, admin_token):
        from app.main import app
        delete_res = self._update_result(3)
        to_delete = [
            _make_user(1, "u1", tenant_id=1),
            _make_user(2, "u2", tenant_id=1),
            _make_user(3, "u3", tenant_id=1),
        ]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(None),
            _scalar_result(None),
            _scalars_result(to_delete),
            delete_res,
        ])
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(f"{BASE}/bulk", json=self._bulk("delete"))
            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["affected_count"] == 3
        finally:
            _clear(app)

    # ── неизвестное действие ────────────────────────────────

    @pytest.mark.asyncio
    async def test_unknown_action(self, admin_token):
        from app.main import app
        session = _make_session(_scalar_result(None))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(f"{BASE}/bulk", json=self._bulk("fly_to_moon"))
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "Неизвестное действие" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── audit_logger вызывается при успехе ──────────────────

    @pytest.mark.asyncio
    async def test_audit_logged_on_bulk(self, admin_token):
        from app.main import app
        update_res = self._update_result(2)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[_scalar_result(None), update_res])
        _override(app, admin_token, session)
        try:
            with patch("app.api.admin_users.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post(f"{BASE}/bulk", json=self._bulk("activate"))
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["action"] == "admin_bulk_activate"
            assert kw["success"] is True
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  GET /api/admin/users/stats/overview  — статистика
# ═══════════════════════════════════════════════════════════════

class TestGetUserStats:

    @pytest.mark.asyncio
    async def test_stats_correct_counts(self, admin_token):
        from app.main import app
        users = [
            _make_user(1, "admin1",  role="admin",  is_active=True,  otp_secret="KEY"),
            _make_user(2, "admin2",  role="admin",  is_active=True,  otp_secret=None),
            _make_user(3, "doc1",    role="doctor", is_active=True,  otp_secret=None),
            _make_user(4, "user1",   role="user",   is_active=True,  otp_secret=None),
            _make_user(5, "user2",   role="user",   is_active=False, otp_secret=None),
        ]
        session = _make_session(_scalars_result(users))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(f"{BASE}/stats/overview")
            assert resp.status_code == status.HTTP_200_OK
            body = resp.json()
            assert body["total_users"] == 5
            assert body["active_users"] == 4
            assert body["inactive_users"] == 1
            assert body["admins"] == 2
            assert body["doctors"] == 1
            assert body["regular_users"] == 2
            assert body["users_with_2fa"] == 1
        finally:
            _clear(app)

    @pytest.mark.asyncio
    async def test_stats_empty_db(self, admin_token):
        from app.main import app
        session = _make_session(_scalars_result([]))
        _override(app, admin_token, session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get(f"{BASE}/stats/overview")
            assert resp.status_code == status.HTTP_200_OK
            body = resp.json()
            assert body["total_users"] == 0
            assert body["active_users"] == 0
            assert body["users_with_2fa"] == 0
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  Pydantic схемы — юнит-тесты валидации
# ═══════════════════════════════════════════════════════════════

class TestSchemaValidation:

    def test_user_create_valid(self):
        from app.api.admin_users import UserCreateRequest
        u = UserCreateRequest(
            username="validuser",
            email="valid@example.com",
            password="securepass123",
        )
        assert u.username == "validuser"

    def test_user_create_bad_email(self):
        from app.api.admin_users import UserCreateRequest
        import pytest
        with pytest.raises(Exception):
            UserCreateRequest(username="user", email="not-email", password="pass1234")

    def test_user_create_bad_username_chars(self):
        from app.api.admin_users import UserCreateRequest
        with pytest.raises(Exception):
            UserCreateRequest(username="bad user!", email="x@x.com", password="pass1234")

    def test_user_update_email_none_allowed(self):
        from app.api.admin_users import UserUpdateRequest
        u = UserUpdateRequest(email=None)
        assert u.email is None

    def test_user_update_bad_email(self):
        from app.api.admin_users import UserUpdateRequest
        with pytest.raises(Exception):
            UserUpdateRequest(email="not-valid")

    def test_bulk_invalid_role_pattern(self):
        from app.api.admin_users import BulkUserActionRequest
        with pytest.raises(Exception):
            BulkUserActionRequest(user_ids=[1], action="change_role", role="superuser")

    def test_password_reset_min_length(self):
        from app.api.admin_users import UserPasswordResetRequest
        with pytest.raises(Exception):
            UserPasswordResetRequest(new_password="short")