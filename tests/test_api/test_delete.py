# tests/test_api/test_delete.py
"""
Тесты для /api/delete эндпоинтов.
Целевое покрытие: 90-95% (app/api/delete.py)

Маршруты:
  POST /api/delete  — удалить зашифрованный файл (admin-only)
  GET  /api/delete  — отключён, чтобы не обходить admin-auth через query string

Особенности кода:
  - ENCRYPTED_DIR патчится как MagicMock с __truediv__
  - stat() запускается через loop.run_in_executor, патчим Path.stat
  - calculate_hash_async патчится глобально в модуле
"""
import uuid
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import status
from httpx import AsyncClient, ASGITransport

from datetime import datetime, timezone, timedelta

from app.core.auth import TokenData
from app.models.file import File
from app.core.storage_backend import ObjectMetadata


# ─────────────────────────────────────────────────────────────
#  Константы
# ─────────────────────────────────────────────────────────────
URL = "/api/delete"
FAKE_HASH = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


# ─────────────────────────────────────────────────────────────
#  Фикстуры
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def admin_token():
    return TokenData(sub="admin", role="admin", tenant_id=1)


@pytest.fixture
async def delete_post_ctx(admin_token, override_app_db, stub_encrypted_storage, tmp_path, monkeypatch):
    """POST /delete: админ + тестовая БД + заглушка encrypted_storage."""
    from app.main import app
    from app.core.auth import get_current_admin

    enc = tmp_path / "enc"
    enc.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.api.delete.ENCRYPTED_DIR", enc)

    async def _adm():
        return admin_token

    app.dependency_overrides[get_current_admin] = _adm
    yield app, override_app_db
    app.dependency_overrides.pop(get_current_admin, None)


async def _insert_file(db, encrypted_name: str, tenant_id: int = 1, **kw):
    f = File(
        tenant_id=tenant_id,
        encrypted_name=encrypted_name,
        encrypted_path=kw.get("encrypted_path", f"/tmp/enc/{encrypted_name}"),
        original_name=kw.get("original_name", "orig.pdf"),
        user_id=kw.get("user_id"),
        original_size=kw.get("original_size", 2048),
        encrypted_size=kw.get("encrypted_size", 2048),
        original_hash=kw.get("original_hash", uuid.uuid4().hex),
        mime_type="application/pdf",
        uploaded_at=kw.get("uploaded_at", datetime.now(timezone.utc)),
        expires_at=kw.get("expires_at", datetime.now(timezone.utc) + timedelta(days=7)),
    )
    db.add(f)
    await db.flush()
    return f


# ─────────────────────────────────────────────────────────────
#  Вспомогательные функции (legacy Path-моки для редких веток)
# ─────────────────────────────────────────────────────────────

def _make_path(exists: bool, name: str = "file.pdf.age", size: int = 2048) -> MagicMock:
    """Мок Path-объекта с контролируемым exists() / stat()."""
    p = MagicMock(spec=Path)
    p.__str__ = lambda self: f"/tmp/enc/{name}"
    p.exists.return_value = exists
    stat_mock = MagicMock()
    stat_mock.st_size = size
    p.stat.return_value = stat_mock
    p.name = name
    return p


def _override(app, token: TokenData):
    """Переопределяет get_current_admin."""
    from app.core.auth import get_current_admin

    async def _auth():
        return token

    app.dependency_overrides[get_current_admin] = _auth


def _clear(app):
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────
#  Общий контекст-менеджер для патчей ENCRYPTED_DIR
# ─────────────────────────────────────────────────────────────

def _patch_enc_dir(primary_path: MagicMock, secondary_path: MagicMock = None):
    """
    Патчит app.api.delete.ENCRYPTED_DIR.
    primary_path  — возвращается при ENCRYPTED_DIR / safe_filename
    secondary_path — возвращается при ENCRYPTED_DIR / f"{safe_filename}.age"
                     (используется для тестов auto-.age)
    """
    mock_dir = MagicMock()
    if secondary_path is None:
        mock_dir.__truediv__ = MagicMock(return_value=primary_path)
    else:
        mock_dir.__truediv__ = MagicMock(side_effect=[primary_path, secondary_path])
    return patch("app.api.delete.ENCRYPTED_DIR", mock_dir)


# ═══════════════════════════════════════════════════════════════
#  POST /api/delete
# ═══════════════════════════════════════════════════════════════

class TestDeleteFilePost:

    # ── 404: файл не найден, имя уже содержит .age ───────────

    @pytest.mark.asyncio
    async def test_not_found_with_age_extension(self, admin_token):
        """Файл с .age в имени не найден → 404 сразу."""
        from app.main import app
        _override(app, admin_token)
        try:
            missing = _make_path(exists=False, name="secret.pdf.age")

            with patch("app.api.delete.sanitize_filename", return_value="secret.pdf.age"), \
                 _patch_enc_dir(missing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "secret.pdf.age", "confirm": "false"})

            assert resp.status_code == status.HTTP_404_NOT_FOUND
            assert "secret.pdf.age" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── 404: файл без .age не найден, .age-вариант тоже нет ──

    @pytest.mark.asyncio
    async def test_not_found_without_age_both_missing(self, admin_token):
        """Файл без .age → проверяет с .age → тоже нет → 404."""
        from app.main import app
        _override(app, admin_token)
        try:
            no_age = _make_path(exists=False, name="report.pdf")
            no_age_ext = _make_path(exists=False, name="report.pdf.age")

            with patch("app.api.delete.sanitize_filename", return_value="report.pdf"), \
                 _patch_enc_dir(no_age, no_age_ext):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "report.pdf", "confirm": "false"})

            assert resp.status_code == status.HTTP_404_NOT_FOUND
            assert "report.pdf" in resp.json()["detail"]
        finally:
            _clear(app)

    # ── авто-добавление .age: файл без .age → найден с .age ──

    @pytest.mark.asyncio
    async def test_auto_age_extension_found(self, delete_post_ctx):
        """Файл без .age → в БД есть .age → продолжает выполнение."""
        app, db = delete_post_ctx
        await _insert_file(db, "report.pdf.age", encrypted_size=1024)
        try:
            with patch("app.api.delete.sanitize_filename", return_value="report.pdf"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "report.pdf", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["name"] == "report.pdf.age"
        finally:
            pass

    # ── confirmation_required без confirm ─────────────────────

    @pytest.mark.asyncio
    async def test_requires_confirmation_default(self, delete_post_ctx):
        """confirm не передан (default 'false') → запрос на подтверждение."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=4096)
        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["requires_confirmation"] is True
            assert body["file_info"]["name"] == "file.pdf.age"
            assert body["file_info"]["size"] == 4096
            assert body["file_info"]["hash"].endswith("...")
        finally:
            pass

    # ── параметризованный: все falsy-значения confirm ─────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirm_val", ["false", "no", "0", "off", "False", "FALSE"])
    async def test_confirm_falsy_values(self, confirm_val, delete_post_ctx):
        """Все falsy-значения confirm → возвращает confirmation_required."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=512)
        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": confirm_val})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["confirmation_required"] is True
        finally:
            pass

    # ── параметризованный: все truthy-значения confirm ────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirm_val", ["true", "yes", "1", "on", "confirmed"])
    async def test_confirm_truthy_values(self, confirm_val, delete_post_ctx):
        """Все truthy-значения confirm → файл удаляется."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=100)
        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": confirm_val})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["message"] == "✅ Файл успешно удален"
        finally:
            pass

    # ── успешное удаление с reason ────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_success_with_reason(self, delete_post_ctx, monkeypatch):
        """Успешное удаление с явным reason → audit_logger получает reason."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=2048)

        import time as _time

        async def _stat2048(key: str):
            return ObjectMetadata(key=key, size=2048, last_modified=_time.time())

        from app.core import encrypted_storage as _es

        monkeypatch.setattr(_es, "stat", _stat2048)

        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={
                        "filename": "file.pdf.age",
                        "confirm": "true",
                        "reason": "Тестовая причина",
                    })

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["filename"] == "file.pdf.age"
            assert body["hash"] == FAKE_HASH
            assert body["size"] == 2048
            assert body["audit_logged"] is True
            assert body["timestamp"] is None

            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["action"] == "delete"
            assert kw["success"] is True
            assert kw["reason"] == "Тестовая причина"
        finally:
            pass

    # ── успешное удаление без reason → дефолтный reason ──────

    @pytest.mark.asyncio
    async def test_delete_success_default_reason(self, delete_post_ctx):
        """Пустой reason → audit_logger получает дефолтную строку."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=512)
        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_200_OK
            kw = mock_audit.log_operation.call_args.kwargs
            assert "администратором" in kw["reason"]
        finally:
            pass

    # ── timestamp присутствует если файл ещё существует ──────

    @pytest.mark.asyncio
    async def test_delete_timestamp_if_file_still_exists(self, delete_post_ctx):
        """Ответ успешного удаления не содержит timestamp (поле зарезервировано)."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=100)
        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["timestamp"] is None
        finally:
            pass

    # ── 500: os.remove падает ────────────────────────────────

    @pytest.mark.asyncio
    async def test_os_remove_raises_500(self, delete_post_ctx, monkeypatch):
        """Ошибка encrypted_storage.delete → 500 и audit_logger с success=False."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=1024)
        try:

            async def _boom(_k):
                raise PermissionError("Permission denied")

            from app.core import encrypted_storage

            monkeypatch.setattr(encrypted_storage, "delete", _boom)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Delete failed" in resp.json()["detail"]
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["success"] is False
            assert kw["action"] == "delete"
        finally:
            pass

    # ── 500: audit_logger получает дефолтный reason при ошибке

    @pytest.mark.asyncio
    async def test_error_audit_default_reason(self, delete_post_ctx, monkeypatch):
        """При ошибке удаления audit_logger получает сообщение с текстом ошибки."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age", encrypted_size=256)
        try:

            async def _boom(_k):
                raise OSError("disk error")

            from app.core import encrypted_storage

            monkeypatch.setattr(encrypted_storage, "delete", _boom)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            kw = mock_audit.log_operation.call_args.kwargs
            assert "удаление" in kw["reason"].lower()
        finally:
            pass

    # ── stat(): FileNotFoundError → file_info заполняется корректно

    @pytest.mark.asyncio
    async def test_stat_file_not_found_branch(self, delete_post_ctx, monkeypatch):
        """encrypted_storage.stat бросает → размер в превью остаётся 0."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age")

        async def _stat(_k):
            raise FileNotFoundError("gone")

        from app.core import encrypted_storage

        monkeypatch.setattr(encrypted_storage, "stat", _stat)

        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["size"] == 0
        finally:
            pass

    # ── stat(): PermissionError → file_info корректен ─────────

    @pytest.mark.asyncio
    async def test_stat_permission_error_branch(self, delete_post_ctx, monkeypatch):
        """stat кидает PermissionError → size остаётся 0."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age")

        async def _stat(_k):
            raise PermissionError("no access")

        from app.core import encrypted_storage

        monkeypatch.setattr(encrypted_storage, "stat", _stat)

        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["size"] == 0
        finally:
            pass

    # ── stat(): generic Exception → file_info корректен ──────

    @pytest.mark.asyncio
    async def test_stat_generic_exception_branch(self, delete_post_ctx, monkeypatch):
        """stat кидает RuntimeError → size остаётся 0."""
        app, db = delete_post_ctx
        await _insert_file(db, "file.pdf.age")

        async def _stat(_k):
            raise RuntimeError("unexpected")

        from app.core import encrypted_storage

        monkeypatch.setattr(encrypted_storage, "stat", _stat)

        try:
            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger"):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["size"] == 0
        finally:
            pass

    # ── filename обязателен → 422 если не передан ─────────────

    @pytest.mark.asyncio
    async def test_missing_filename_422(self, delete_post_ctx):
        app, _db = delete_post_ctx
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(URL, data={"confirm": "false"})
            assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        finally:
            pass

    # ── без авторизации → 401/403 ─────────────────────────────

    @pytest.mark.asyncio
    async def test_unauthorized_returns_401_or_403(self):
        """POST без авторизации отклоняется."""
        from app.main import app
        # Не переопределяем зависимость
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    # ── audit_logger: metadata содержит правильные поля ───────

    @pytest.mark.asyncio
    async def test_audit_metadata_content(self, delete_post_ctx, monkeypatch):
        """audit_logger.log_operation получает корректный metadata."""
        app, db = delete_post_ctx
        await _insert_file(db, "data.pdf.age", encrypted_size=3000)

        import time as _time

        async def _stat3000(key: str):
            return ObjectMetadata(key=key, size=3000, last_modified=_time.time())

        from app.core import encrypted_storage as _es

        monkeypatch.setattr(_es, "stat", _stat3000)

        try:
            with patch("app.api.delete.sanitize_filename", return_value="data.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.audit_logger") as mock_audit:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post(URL, data={"filename": "data.pdf.age", "confirm": "true"})

            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["filename"] == "data.pdf.age"
            assert kw["user"] == "admin"
            assert kw["metadata"]["size"] == 3000
            assert kw["metadata"]["hash"] == FAKE_HASH
        finally:
            pass


# ═══════════════════════════════════════════════════════════════
#  GET /api/delete
# ═══════════════════════════════════════════════════════════════

class TestDeleteFileGet:
    """GET /api/delete отключён: удаление разрешено только через admin-only POST."""

    @pytest.mark.asyncio
    async def test_get_delete_is_not_allowed(self):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(
                URL,
                params={
                    "filename": "file.pdf.age",
                    "x-api-key": "any-key",
                    "confirm": "true",
                },
            )

        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED