# tests/test_api/test_delete.py
"""
Тесты для /api/delete эндпоинтов.
Целевое покрытие: 90-95% (app/api/delete.py)

Маршруты:
  POST /api/delete  — удалить зашифрованный файл (admin-only)
  GET  /api/delete  — то же, GET-версия (вызывает POST-функцию напрямую)

Особенности кода:
  - ENCRYPTED_DIR патчится как MagicMock с __truediv__
  - GET-эндпоинт передаёт api_key как current_user (строку вместо TokenData)
    — это баг в коде, тест документирует поведение as-is
  - stat() запускается через loop.run_in_executor, патчим Path.stat
  - calculate_hash_async патчится глобально в модуле
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import status
from httpx import AsyncClient, ASGITransport

from app.core.auth import TokenData


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
    return TokenData(sub="admin", role="admin")


# ─────────────────────────────────────────────────────────────
#  Вспомогательные функции
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
    async def test_auto_age_extension_found(self, admin_token):
        """Файл без .age → .age-версия существует → продолжает выполнение."""
        from app.main import app
        _override(app, admin_token)
        try:
            no_age = _make_path(exists=False, name="report.pdf")
            with_age = _make_path(exists=True, name="report.pdf.age", size=1024)

            with patch("app.api.delete.sanitize_filename", return_value="report.pdf"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(no_age, with_age):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "report.pdf", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            # Имя файла должно содержать .age
            assert body["file_info"]["name"] == "report.pdf.age"
        finally:
            _clear(app)

    # ── confirmation_required без confirm ─────────────────────

    @pytest.mark.asyncio
    async def test_requires_confirmation_default(self, admin_token):
        """confirm не передан (default 'false') → запрос на подтверждение."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, name="file.pdf.age", size=4096)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["requires_confirmation"] is True
            assert body["file_info"]["name"] == "file.pdf.age"
            assert body["file_info"]["size"] == 4096
            # hash обрезается до 20 символов + "..."
            assert body["file_info"]["hash"].endswith("...")
        finally:
            _clear(app)

    # ── параметризованный: все falsy-значения confirm ─────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirm_val", ["false", "no", "0", "off", "False", "FALSE"])
    async def test_confirm_falsy_values(self, confirm_val, admin_token):
        """Все falsy-значения confirm → возвращает confirmation_required."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=512)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": confirm_val})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["confirmation_required"] is True
        finally:
            _clear(app)

    # ── параметризованный: все truthy-значения confirm ────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirm_val", ["true", "yes", "1", "on", "confirmed"])
    async def test_confirm_truthy_values(self, confirm_val, admin_token):
        """Все truthy-значения confirm → файл удаляется."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=100)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove"), \
                 patch("app.api.delete.os.path.exists", return_value=False), \
                 patch("app.api.delete.audit_logger"), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": confirm_val})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["message"] == "✅ Файл успешно удален"
        finally:
            _clear(app)

    # ── успешное удаление с reason ────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_success_with_reason(self, admin_token):
        """Успешное удаление с явным reason → audit_logger получает reason."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=2048)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove") as mock_remove, \
                 patch("app.api.delete.os.path.exists", return_value=False), \
                 patch("app.api.delete.audit_logger") as mock_audit, \
                 _patch_enc_dir(existing):
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
            assert body["timestamp"] is None   # os.path.exists → False

            mock_remove.assert_called_once()
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["action"] == "delete"
            assert kw["success"] is True
            assert kw["reason"] == "Тестовая причина"
        finally:
            _clear(app)

    # ── успешное удаление без reason → дефолтный reason ──────

    @pytest.mark.asyncio
    async def test_delete_success_default_reason(self, admin_token):
        """Пустой reason → audit_logger получает дефолтную строку."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=512)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove"), \
                 patch("app.api.delete.os.path.exists", return_value=False), \
                 patch("app.api.delete.audit_logger") as mock_audit, \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_200_OK
            kw = mock_audit.log_operation.call_args.kwargs
            assert "администратором" in kw["reason"]
        finally:
            _clear(app)

    # ── timestamp присутствует если файл ещё существует ──────

    @pytest.mark.asyncio
    async def test_delete_timestamp_if_file_still_exists(self, admin_token):
        """os.path.exists → True после удаления → timestamp заполнен."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=100)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove"), \
                 patch("app.api.delete.os.path.exists", return_value=True), \
                 patch("app.api.delete.os.path.getmtime", return_value=1700000000.0), \
                 patch("app.api.delete.audit_logger"), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["timestamp"] == 1700000000.0
        finally:
            _clear(app)

    # ── 500: os.remove падает ────────────────────────────────

    @pytest.mark.asyncio
    async def test_os_remove_raises_500(self, admin_token):
        """Ошибка os.remove → 500 и audit_logger с success=False."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=1024)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove", side_effect=PermissionError("Permission denied")), \
                 patch("app.api.delete.audit_logger") as mock_audit, \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "Delete failed" in resp.json()["detail"]
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["success"] is False
            assert kw["action"] == "delete"
        finally:
            _clear(app)

    # ── 500: audit_logger получает дефолтный reason при ошибке

    @pytest.mark.asyncio
    async def test_error_audit_default_reason(self, admin_token):
        """При ошибке с пустым reason → audit_logger получает дефолт."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=256)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove", side_effect=OSError("disk error")), \
                 patch("app.api.delete.audit_logger") as mock_audit, \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "true"})

            assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            kw = mock_audit.log_operation.call_args.kwargs
            # reason="" → fallback "Ручное удаление"
            assert "удаление" in kw["reason"].lower()
        finally:
            _clear(app)

    # ── stat(): FileNotFoundError → file_info заполняется корректно

    @pytest.mark.asyncio
    async def test_stat_file_not_found_branch(self, admin_token):
        """stat() кидает FileNotFoundError → size=0, hash=file_not_found_before_delete."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=0)
            # stat() бросает FileNotFoundError
            existing.stat.side_effect = FileNotFoundError("gone")

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            # size = 0 из-за FileNotFoundError
            assert body["file_info"]["size"] == 0
        finally:
            _clear(app)

    # ── stat(): PermissionError → file_info корректен ─────────

    @pytest.mark.asyncio
    async def test_stat_permission_error_branch(self, admin_token):
        """stat() кидает PermissionError → size='permission_denied'."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True)
            existing.stat.side_effect = PermissionError("no access")

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert body["file_info"]["size"] == "permission_denied"
        finally:
            _clear(app)

    # ── stat(): generic Exception → file_info корректен ──────

    @pytest.mark.asyncio
    async def test_stat_generic_exception_branch(self, admin_token):
        """stat() кидает Exception → size='error: ...'."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True)
            existing.stat.side_effect = RuntimeError("unexpected")

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.post(URL, data={"filename": "file.pdf.age", "confirm": "false"})

            body = resp.json()
            assert resp.status_code == status.HTTP_200_OK
            assert body["confirmation_required"] is True
            assert "error:" in str(body["file_info"]["size"])
        finally:
            _clear(app)

    # ── filename обязателен → 422 если не передан ─────────────

    @pytest.mark.asyncio
    async def test_missing_filename_422(self, admin_token):
        from app.main import app
        _override(app, admin_token)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post(URL, data={"confirm": "false"})
            assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        finally:
            _clear(app)

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
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # ── audit_logger: metadata содержит правильные поля ───────

    @pytest.mark.asyncio
    async def test_audit_metadata_content(self, admin_token):
        """audit_logger.log_operation получает корректный metadata."""
        from app.main import app
        _override(app, admin_token)
        try:
            existing = _make_path(exists=True, size=3000)

            with patch("app.api.delete.sanitize_filename", return_value="data.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove"), \
                 patch("app.api.delete.os.path.exists", return_value=False), \
                 patch("app.api.delete.audit_logger") as mock_audit, \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post(URL, data={"filename": "data.pdf.age", "confirm": "true"})

            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["filename"] == "data.pdf.age"
            assert kw["user"] == "admin"
            assert kw["metadata"]["size"] == 3000
            assert kw["metadata"]["hash"] == FAKE_HASH
        finally:
            _clear(app)


# ═══════════════════════════════════════════════════════════════
#  GET /api/delete
# ═══════════════════════════════════════════════════════════════

class TestDeleteFileGet:
    """
    GET /api/delete не имеет Depends(get_current_admin).
    Вместо этого принимает api_key как query-параметр и передаёт его
    позиционно в delete_file() как current_user.
    Это баг в коде — тесты документируют реальное поведение.
    """

    # ── GET без api_key → 422 (поле обязательно) ─────────────

    @pytest.mark.asyncio
    async def test_get_missing_api_key_422(self):
        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(URL, params={"filename": "file.pdf.age"})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # ── GET без filename → 422 ────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_missing_filename_422(self):
        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(URL, params={"x-api-key": "somekey"})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # ── GET: вызывает delete_file (файл не найден → 404) ──────

    @pytest.mark.asyncio
    async def test_get_delegates_to_post_logic_404(self):
        """GET передаёт управление в delete_file. Файл не найден → 404."""
        from app.main import app
        try:
            missing = _make_path(exists=False, name="gone.pdf.age")

            with patch("app.api.delete.sanitize_filename", return_value="gone.pdf.age"), \
                 _patch_enc_dir(missing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(URL, params={
                        "filename": "gone.pdf.age",
                        "x-api-key": "any-key",
                        "confirm": "false",
                    })

            assert resp.status_code == status.HTTP_404_NOT_FOUND
        finally:
            pass

    # ── GET: confirm=false → confirmation_required ────────────

    @pytest.mark.asyncio
    async def test_get_requires_confirmation(self):
        """GET с существующим файлом, confirm=false → confirmation_required."""
        from app.main import app
        try:
            existing = _make_path(exists=True, size=512)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(URL, params={
                        "filename": "file.pdf.age",
                        "x-api-key": "any-key",
                        "confirm": "false",
                    })

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["confirmation_required"] is True
        finally:
            pass

    # ── GET: confirm=true → файл удаляется ───────────────────

    @pytest.mark.asyncio
    async def test_get_delete_confirmed(self):
        """GET с confirm=true → файл удаляется успешно."""
        from app.main import app
        try:
            existing = _make_path(exists=True, size=1024)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove") as mock_remove, \
                 patch("app.api.delete.os.path.exists", return_value=False), \
                 patch("app.api.delete.audit_logger"), \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(URL, params={
                        "filename": "file.pdf.age",
                        "x-api-key": "any-key",
                        "confirm": "true",
                    })

            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["message"] == "✅ Файл успешно удален"
            mock_remove.assert_called_once()
        finally:
            pass

    # ── GET: reason передаётся в audit_logger ─────────────────

    @pytest.mark.asyncio
    async def test_get_reason_forwarded(self):
        """reason из query params попадает в audit_logger."""
        from app.main import app
        try:
            existing = _make_path(exists=True, size=100)

            with patch("app.api.delete.sanitize_filename", return_value="file.pdf.age"), \
                 patch("app.api.delete.calculate_hash_async", new_callable=AsyncMock, return_value=FAKE_HASH), \
                 patch("app.api.delete.os.remove"), \
                 patch("app.api.delete.os.path.exists", return_value=False), \
                 patch("app.api.delete.audit_logger") as mock_audit, \
                 _patch_enc_dir(existing):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    resp = await ac.get(URL, params={
                        "filename": "file.pdf.age",
                        "x-api-key": "any-key",
                        "confirm": "true",
                        "reason": "плановая очистка",
                    })

            assert resp.status_code == status.HTTP_200_OK
            kw = mock_audit.log_operation.call_args.kwargs
            assert kw["reason"] == "плановая очистка"
        finally:
            pass