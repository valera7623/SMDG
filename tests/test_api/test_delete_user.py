# tests/test_api/test_delete_user.py
"""
Тесты для эндпоинтов удаления файлов пользователя:
  POST   /api/delete-user-file          — удаление по имени файла
  DELETE /api/delete-user-file/{file_id} — удаление по ID
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import status
from httpx import AsyncClient, ASGITransport

from app.core.auth import TokenData


# ─────────────────────────────────────────────────────────────
#  Константы маршрутов
# ─────────────────────────────────────────────────────────────
URL_BY_NAME = "/api/delete-user-file"
URL_BY_ID   = "/api/delete-user-file/{file_id}"


# ─────────────────────────────────────────────────────────────
#  Фикстуры
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def user_token():
    return TokenData(sub="testuser", role="user")


@pytest.fixture
def admin_token():
    return TokenData(sub="admin", role="admin")


@pytest.fixture
def make_db_file():
    def _make(
        id: int = 1,
        user_id: int = 42,
        encrypted_name: str = "secret.pdf.age",
        original_name: str = "secret.pdf",
        original_size: int = 1024,
    ):
        f = MagicMock()
        f.id = id
        f.user_id = user_id
        f.encrypted_name = encrypted_name
        f.original_name = original_name
        f.original_size = original_size
        return f
    return _make


@pytest.fixture
def make_db_user():
    def _make(id: int = 42, username: str = "testuser"):
        u = MagicMock()
        u.id = id
        u.username = username
        return u
    return _make


# ─────────────────────────────────────────────────────────────
#  Вспомогательные функции
# ─────────────────────────────────────────────────────────────

def _make_path(exists: bool, name: str = "secret.pdf.age", size: int = 1024) -> MagicMock:
    """Создаёт мок Path с нужным поведением exists() / stat()."""
    p = MagicMock(spec=Path)
    p.__str__ = lambda self: f"/tmp/enc/{name}"
    p.exists.return_value = exists
    stat = MagicMock()
    stat.st_size = size
    p.stat.return_value = stat
    p.name = name
    return p


def _make_session(file_obj=None, user_obj=None) -> AsyncMock:
    """Собирает мок AsyncSession с нужными ответами execute()."""
    session = AsyncMock()

    def _result(obj):
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        return r

    if user_obj is None:
        session.execute = AsyncMock(return_value=_result(file_obj))
    else:
        session.execute = AsyncMock(
            side_effect=[_result(file_obj), _result(user_obj)]
        )
    return session


def _override(app, token: TokenData, session: AsyncMock):
    """Переопределяет get_current_user и get_db в app."""
    from app.core.auth import get_current_user
    from app.core.database import get_db

    async def _auth():
        return token

    async def _db():
        yield session

    app.dependency_overrides[get_current_user] = _auth
    app.dependency_overrides[get_db] = _db


def _clear(app):
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
#  POST /api/delete-user-file  — по имени файла
# ═══════════════════════════════════════════════════════════════

class TestDeleteUserFileByName:

    # ── 404: файл не найден на диске ─────────────────────────

    @pytest.mark.asyncio
    async def test_file_not_found_on_disk(self, user_token):
        from app.main import app

        session = _make_session(file_obj=None)
        _override(app, user_token, session)

        try:
            missing = _make_path(exists=False, name="missing.pdf")

            with patch("app.api.delete_user.sanitize_filename", return_value="missing.pdf"), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=missing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "missing.pdf", "confirm": "false"})

            assert resp.status_code == status.HTTP_404_NOT_FOUND
            detail = resp.json()["detail"]
            assert "missing.pdf" in detail
        finally:
            _clear(app)

    # ── 403: не владелец ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_forbidden_not_owner(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(user_id=99)           # чужой файл
        own_user = make_db_user(id=42)               # текущий пользователь
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True)

            with patch("app.api.delete_user.sanitize_filename", return_value="secret.pdf.age"), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "secret.pdf.age", "confirm": "false"})

            assert resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            _clear(app)

    # ── 200 + confirmation_required: без confirm ──────────────

    @pytest.mark.asyncio
    async def test_requires_confirmation(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=2048)

            with patch("app.api.delete_user.sanitize_filename", return_value="secret.pdf.age"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="abc" * 20), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "secret.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["requires_confirmation"] is True
            assert body["file_info"]["name"] == "secret.pdf.age"
        finally:
            _clear(app)

    # ── 200 success: владелец подтверждает удаление ──────────

    @pytest.mark.asyncio
    async def test_owner_can_delete_confirmed(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=1024)

            with patch("app.api.delete_user.sanitize_filename", return_value="secret.pdf.age"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="dead" * 16), \
                 patch("app.api.delete_user.os.remove") as mock_remove, \
                 patch("app.api.delete_user.audit_logger") as mock_audit, \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "secret.pdf.age", "confirm": "true"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["success"] is True
            assert body["filename"] == "secret.pdf.age"
            mock_remove.assert_called_once()
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["success"] is True
            assert kw["action"] == "user_delete_file"
            assert kw["user"] == "testuser"
        finally:
            _clear(app)

    # ── 200 success: администратор удаляет чужой файл ────────

    @pytest.mark.asyncio
    async def test_admin_can_delete_any_file(self, make_db_file, make_db_user, admin_token):
        from app.main import app

        db_file = make_db_file(user_id=99)
        other_user = make_db_user(id=99, username="other")
        session = _make_session(file_obj=db_file, user_obj=other_user)
        _override(app, admin_token, session)

        try:
            existing = _make_path(exists=True, size=512)

            with patch("app.api.delete_user.sanitize_filename", return_value="secret.pdf.age"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="cafe" * 16), \
                 patch("app.api.delete_user.os.remove"), \
                 patch("app.api.delete_user.audit_logger"), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "secret.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["success"] is True
        finally:
            _clear(app)

    # ── auto .age: файл найден с расширением .age ────────────

    @pytest.mark.asyncio
    async def test_auto_adds_age_extension(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(user_id=42, encrypted_name="report.pdf.age")
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            path_no_age   = _make_path(exists=False, name="report.pdf")
            path_with_age = _make_path(exists=True,  name="report.pdf.age", size=500)

            def _truediv(name):
                return path_with_age if str(name).endswith(".age") else path_no_age

            with patch("app.api.delete_user.sanitize_filename", return_value="report.pdf"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="aa" * 32), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(side_effect=_truediv)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "report.pdf", "confirm": "false"})

            body = resp.json()
            # Файл нашёлся с .age → возвращает запрос на подтверждение
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
        finally:
            _clear(app)

    # ── 500: os.remove падает ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_os_remove_error_returns_500(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=512)

            with patch("app.api.delete_user.sanitize_filename", return_value="secret.pdf.age"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="ff" * 32), \
                 patch("app.api.delete_user.os.remove", side_effect=PermissionError("Access denied")), \
                 patch("app.api.delete_user.audit_logger") as mock_audit, \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "secret.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["success"] is False
        finally:
            _clear(app)

    # ── параметризованный: все truthy-значения confirm ────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirm_val", ["yes", "1", "on", "confirmed", "true"])
    async def test_confirm_truthy_values(self, confirm_val, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=100)

            with patch("app.api.delete_user.sanitize_filename", return_value="secret.pdf.age"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="x" * 64), \
                 patch("app.api.delete_user.os.remove"), \
                 patch("app.api.delete_user.audit_logger"), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "secret.pdf.age", "confirm": confirm_val})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["success"] is True
        finally:
            _clear(app)

    # ── файл без записи в БД (orphan) удаляется с confirm ────

    @pytest.mark.asyncio
    async def test_file_without_db_record_deleted(self, user_token):
        from app.main import app

        session = _make_session(file_obj=None)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=200, name="orphan.pdf.age")

            with patch("app.api.delete_user.sanitize_filename", return_value="orphan.pdf.age"), \
                 patch("app.api.delete_user.calculate_hash_async", new_callable=AsyncMock, return_value="bb" * 32), \
                 patch("app.api.delete_user.os.remove"), \
                 patch("app.api.delete_user.audit_logger"), \
                 patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL_BY_NAME, data={"filename": "orphan.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["success"] is True
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  DELETE /api/delete-user-file/{file_id}  — по ID
# ═══════════════════════════════════════════════════════════════

class TestDeleteUserFileById:

    # ── 404: ID не найден в БД ────────────────────────────────

    @pytest.mark.asyncio
    async def test_file_id_not_found_in_db(self, user_token):
        from app.main import app

        session = _make_session(file_obj=None)
        _override(app, user_token, session)

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete("/api/delete-user-file/9999")

            assert resp.status_code == status.HTTP_404_NOT_FOUND
            assert "9999" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── 403: не владелец ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_forbidden_not_owner_by_id(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(id=5, user_id=99)
        wrong_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=wrong_user)
        _override(app, user_token, session)

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.delete("/api/delete-user-file/5")

            assert resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            _clear(app)

    # ── 404: запись в БД есть, файла на диске нет ────────────

    @pytest.mark.asyncio
    async def test_file_missing_on_disk_by_id(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(id=7, user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            missing = _make_path(exists=False)

            with patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=missing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete("/api/delete-user-file/7")

            assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            _clear(app)

    # ── 200 + confirmation_required: без confirm ──────────────

    @pytest.mark.asyncio
    async def test_requires_confirmation_by_id(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(id=10, user_id=42, original_size=4096)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=4096)

            with patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete("/api/delete-user-file/10")   # confirm=False по умолчанию

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["file_info"]["requires_confirmation"] is True
            assert body["file_info"]["id"] == 10
            assert body["file_info"]["size"] == 4096
        finally:
            _clear(app)

    # ── 200 success: владелец + confirm=true ──────────────────

    @pytest.mark.asyncio
    async def test_owner_delete_by_id_confirmed(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(id=20, user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True, size=1024)

            with patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir, \
                 patch("app.api.delete_user.os.remove") as mock_remove, \
                 patch("app.api.delete_user.audit_logger") as mock_audit:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete("/api/delete-user-file/20?confirm=true")

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["success"] is True
            assert body["id"] == 20
            assert body["original_name"] == db_file.original_name
            mock_remove.assert_called_once()
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["success"] is True
            assert kw["action"] == "user_delete_file"
        finally:
            _clear(app)

    # ── 500: os.remove падает ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_error_returns_500_by_id(self, make_db_file, make_db_user, user_token):
        from app.main import app

        db_file = make_db_file(id=30, user_id=42)
        own_user = make_db_user(id=42)
        session = _make_session(file_obj=db_file, user_obj=own_user)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True)

            with patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir, \
                 patch("app.api.delete_user.os.remove", side_effect=OSError("disk full")), \
                 patch("app.api.delete_user.audit_logger") as mock_audit:
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete("/api/delete-user-file/30?confirm=true")

            assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["success"] is False
        finally:
            _clear(app)

    # ── администратор удаляет чужой файл по ID ───────────────

    @pytest.mark.asyncio
    async def test_admin_delete_any_file_by_id(self, make_db_file, make_db_user, admin_token):
        from app.main import app

        db_file = make_db_file(id=50, user_id=99)
        other_user = make_db_user(id=99, username="other")
        session = _make_session(file_obj=db_file, user_obj=other_user)
        _override(app, admin_token, session)

        try:
            existing = _make_path(exists=True)

            with patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir, \
                 patch("app.api.delete_user.os.remove"), \
                 patch("app.api.delete_user.audit_logger"):
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete("/api/delete-user-file/50?confirm=true")

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["success"] is True
        finally:
            _clear(app)

    # ── файл без user_id (публичный) удаляется без проверки ──

    @pytest.mark.asyncio
    async def test_file_without_user_id_deleted(self, make_db_file, user_token):
        from app.main import app

        db_file = make_db_file(id=60, user_id=None)  # user_id=None → проверка прав пропускается
        session = _make_session(file_obj=db_file)
        _override(app, user_token, session)

        try:
            existing = _make_path(exists=True)

            with patch("app.api.delete_user.ENCRYPTED_DIR") as mock_dir, \
                 patch("app.api.delete_user.os.remove"), \
                 patch("app.api.delete_user.audit_logger"):
                mock_dir.__truediv__ = MagicMock(return_value=existing)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.delete("/api/delete-user-file/60?confirm=true")

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["success"] is True
        finally:
            _clear(app)
