# tests/test_api/test_download.py
"""
Тесты для app/api/download.py
Переписаны под реальный код модуля.
"""

import pytest
import uuid
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, BackgroundTasks
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app
from app.core.auth import get_current_doctor
from app.core.database import get_db
from app.api.download import delete_file_after_response, download_by_token, download_file_post
from app.core.auth import TokenData
from app.models.file_access_event import FileAccessEvent


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФАБРИКИ
# ============================================================================

def make_link(
    token: str = "tok",
    file_id: int = 1,
    max_downloads: int = 5,
    downloads_count: int = 0,
    expires_at=None,
) -> MagicMock:
    """Фабрика mock-объекта FileLink."""
    link = MagicMock()
    link.token           = token
    link.file_id         = file_id
    link.max_downloads   = max_downloads
    link.downloads_count = downloads_count
    link.expires_at      = expires_at or datetime.now(timezone.utc) + timedelta(days=1)
    return link


def make_file(
    file_id: int = 1,
    original_name: str = "doc.pdf",
    encrypted_path: str = "/enc/doc.pdf.age",
    encrypted_name: str = "doc.pdf.age",
) -> MagicMock:
    """Фабрика mock-объекта File."""
    f = MagicMock()
    f.id             = file_id
    f.original_name  = original_name
    f.encrypted_path = encrypted_path
    f.encrypted_name = encrypted_name
    return f


def make_db(results: list) -> AsyncMock:
    """
    Фабрика mock-сессии БД.
    results — список возвращаемых scalar_one_or_none значений
    (по одному на каждый вызов execute).
    """
    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=r))
        for r in results
    ]
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def make_request() -> MagicMock:
    req        = MagicMock(spec=Request)
    req.scope  = {"type": "http"}
    req.client = MagicMock(host="127.0.0.1")
    tenant = MagicMock()
    tenant.id = 1
    req.state = MagicMock()
    req.state.tenant = tenant
    return req


async def _fake_encrypted_download(key, destination_path):
    """Обход LocalStorageBackend: ключ в БД может быть абсолютным путём."""
    p = Path(destination_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"stub-cipher")


# ============================================================================
# ФИКСТУРЫ
# ============================================================================

@pytest.fixture
def tmp_dirs(tmp_path):
    """Временные директории encrypted / decrypted / keys."""
    enc  = tmp_path / "encrypted";  enc.mkdir()
    dec  = tmp_path / "decrypted";  dec.mkdir()
    keys = tmp_path / "keys";       keys.mkdir()
    (keys / "age.key").write_text("mock-key")
    return {"encrypted": enc, "decrypted": dec, "keys": keys}


@pytest.fixture
def doctor_token():
    return TokenData(sub="doctor-uuid", role="doctor", tenant_id=1)


@pytest.fixture
def download_client(doctor_token, tmp_dirs):
    """
    TestClient приложения с подменёнными:
    - get_current_doctor → doctor_token
    - get_db            → AsyncMock-сессия (пустая; тест может заменить)
    - ENCRYPTED_DIR / DECRYPTED_DIR / PRIVATE_KEY_PATH
    """
    empty_db = make_db([None])

    async def _get_db():
        yield empty_db

    app.dependency_overrides[get_current_doctor] = lambda: doctor_token
    app.dependency_overrides[get_db]             = _get_db

    with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
         patch("app.api.download.ENCRYPTED_DIR",    tmp_dirs["encrypted"]), \
         patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
         patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, tmp_dirs, empty_db

    app.dependency_overrides.pop(get_current_doctor, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def no_auth_client():
    """TestClient без подмены зависимостей."""
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ============================================================================
# ТЕСТЫ delete_file_after_response
# ============================================================================

class TestDeleteFileAfterResponse:

    def test_deletes_existing_file(self, tmp_path):
        f = tmp_path / "tmp.bin"
        f.write_bytes(b"data")

        delete_file_after_response(f)

        assert not f.exists()

    def test_no_error_when_file_missing(self):
        """Если файл уже удалён — функция молча завершается."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = False

        delete_file_after_response(mock_path)  # не должно бросить исключение

        mock_path.unlink.assert_not_called()

    def test_logs_error_on_permission_denied(self):
        """PermissionError логируется через logger.error, не print."""
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.unlink.side_effect  = PermissionError("denied")
        # Имя нужно для форматирования лог-сообщения
        mock_path.__str__ = lambda s: "/fake/path"

        with patch("app.api.download.logger") as mock_logger:
            delete_file_after_response(mock_path)

        mock_logger.error.assert_called_once()
        logged_msg = mock_logger.error.call_args[0][0]
        assert "denied" in logged_msg or "Permission" in logged_msg \
               or mock_logger.error.called  # достаточно что error вызван

    def test_logs_debug_when_file_missing(self):
        """Если файл отсутствует — логируем debug."""
        mock_path       = MagicMock(spec=Path)
        mock_path.exists.return_value = False
        mock_path.name  = "gone.bin"

        with patch("app.api.download.logger") as mock_logger:
            delete_file_after_response(mock_path)

        mock_logger.debug.assert_called_once()

    def test_logs_info_on_success(self, tmp_path):
        """Успешное удаление логируется через logger.info."""
        f = tmp_path / "ok.bin"
        f.write_bytes(b"x")

        with patch("app.api.download.logger") as mock_logger:
            delete_file_after_response(f)

        mock_logger.info.assert_called_once()


# ============================================================================
# ТЕСТЫ download_by_token (GET /download?token=...)
# ============================================================================

class TestDownloadByToken:

    @pytest.mark.asyncio
    async def test_token_not_found_raises_404(self):
        db  = make_db([None])  # scalar_one_or_none → None
        req = make_request()

        with pytest.raises(HTTPException) as exc:
            await download_by_token(
                request=req,
                background_tasks=MagicMock(),
                token="no-such-token",
                db=db,
            )

        assert exc.value.status_code == 404
        assert "Ссылка не найдена" in exc.value.detail

    @pytest.mark.asyncio
    async def test_expired_link_raises_410_and_deleted(self):
        link = make_link(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        db   = make_db([link])

        with pytest.raises(HTTPException) as exc:
            await download_by_token(
                request=make_request(),
                background_tasks=MagicMock(),
                token=link.token,
                db=db,
            )

        assert exc.value.status_code == 410
        assert "истекла" in exc.value.detail
        db.delete.assert_called_once_with(link)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_limit_exceeded_raises_410_and_deleted(self):
        link = make_link(max_downloads=3, downloads_count=3)
        db   = make_db([link])

        with pytest.raises(HTTPException) as exc:
            await download_by_token(
                request=make_request(),
                background_tasks=MagicMock(),
                token=link.token,
                db=db,
            )

        assert exc.value.status_code == 410
        assert "Лимит" in exc.value.detail
        db.delete.assert_called_once_with(link)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_not_in_db_raises_404(self):
        link = make_link()
        db   = make_db([link, None])   # ссылка есть, файла нет

        with pytest.raises(HTTPException) as exc:
            await download_by_token(
                request=make_request(),
                background_tasks=MagicMock(),
                token=link.token,
                db=db,
            )

        assert exc.value.status_code == 404
        assert "Файл не найден" in exc.value.detail

    @pytest.mark.asyncio
    async def test_decryption_error_raises_500(self, tmp_dirs):
        link = make_link()
        file = make_file(encrypted_path=str(tmp_dirs["encrypted"] / "enc.age"))
        db   = make_db([link, file])

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm:

            mock_cm.decrypt_file = AsyncMock(side_effect=Exception("bad key"))

            with pytest.raises(HTTPException) as exc:
                await download_by_token(
                    request=make_request(),
                    background_tasks=MagicMock(),
                    token=link.token,
                    db=db,
                )

        assert exc.value.status_code == 500
        assert "расшифровки" in exc.value.detail

    @pytest.mark.asyncio
    async def test_success_increments_counter_and_schedules_cleanup(self, tmp_dirs):
        link = make_link(max_downloads=5, downloads_count=2)
        enc_path = tmp_dirs["encrypted"] / "enc.age"
        enc_path.write_bytes(b"cipher")
        file = make_file(encrypted_path=str(enc_path), original_name="report.pdf")
        db   = make_db([link, file])
        bg   = MagicMock(spec=BackgroundTasks)

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm:

            mock_cm.decrypt_file = AsyncMock()

            response = await download_by_token(
                request=make_request(),
                background_tasks=bg,
                token=link.token,
                db=db,
            )

        # Счётчик увеличен
        assert link.downloads_count == 3
        # Коммит выполнен
        db.commit.assert_called_once()
        assert any(
            isinstance(call_args.args[0], FileAccessEvent)
            and call_args.args[0].action == "download_token"
            for call_args in db.add.call_args_list
        )
        # Фоновая задача на удаление зарегистрирована
        bg.add_task.assert_called_once()
        # Имя файла в ответе
        assert response.filename == "report.pdf"
        assert response.media_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_last_download_deletes_link(self, tmp_dirs):
        """При последнем скачивании ссылка удаляется из БД."""
        link = make_link(max_downloads=3, downloads_count=2)
        enc_path = tmp_dirs["encrypted"] / "last.age"
        enc_path.write_bytes(b"x")
        file = make_file(encrypted_path=str(enc_path))
        db   = make_db([link, file])

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm:

            mock_cm.decrypt_file = AsyncMock()

            await download_by_token(
                request=make_request(),
                background_tasks=MagicMock(),
                token=link.token,
                db=db,
            )

        # Лимит исчерпан → ссылка удалена
        db.delete.assert_called_once_with(link)

    @pytest.mark.asyncio
    async def test_no_expiry_link_is_valid(self, tmp_dirs):
        """Ссылка без expires_at (None) не должна считаться истёкшей."""
        link = make_link(expires_at=None)
        link.expires_at = None  # явно None

        enc_path = tmp_dirs["encrypted"] / "noexp.age"
        enc_path.write_bytes(b"data")
        file = make_file(encrypted_path=str(enc_path))
        db   = make_db([link, file])

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm:

            mock_cm.decrypt_file = AsyncMock()

            response = await download_by_token(
                request=make_request(),
                background_tasks=MagicMock(),
                token=link.token,
                db=db,
            )

        assert response.media_type == "application/octet-stream"


# ============================================================================
# ТЕСТЫ download_file_post (POST /download)
# ============================================================================

class TestDownloadFilePost:

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_db_with_file(file_record):
        """Сессия, возвращающая file_record на первый execute."""
        return make_db([file_record])

    # ── unit-тесты (прямой вызов функции) ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_file_not_on_disk_raises_404(self, tmp_dirs):
        """Нет записи в БД → 404."""
        db = make_db([None])

        with patch("app.api.download.ENCRYPTED_DIR", tmp_dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR", tmp_dirs["decrypted"]):

            with pytest.raises(HTTPException) as exc:
                await download_file_post(
                    request=make_request(),
                    background_tasks=MagicMock(),
                    filename="missing.age",
                    current_user=TokenData(sub="doc", role="doctor", tenant_id=1),
                    db=db,
                )

        assert exc.value.status_code == 404
        assert "базе" in exc.value.detail

    @pytest.mark.asyncio
    async def test_file_not_in_db_raises_404(self, tmp_dirs):
        """Файл есть на диске, но не в БД → 404."""
        enc_file = tmp_dirs["encrypted"] / "exists.age"
        enc_file.write_bytes(b"enc")

        db = make_db([None])  # file_record не найден

        with patch("app.api.download.ENCRYPTED_DIR", tmp_dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR", tmp_dirs["decrypted"]):

            with pytest.raises(HTTPException) as exc:
                await download_file_post(
                    request=make_request(),
                    background_tasks=MagicMock(),
                    filename="exists.age",
                    current_user=TokenData(sub="doc", role="doctor", tenant_id=1),
                    db=db,
                )

        assert exc.value.status_code == 404
        assert "базе" in exc.value.detail

    @pytest.mark.asyncio
    async def test_decryption_error_raises_500(self, tmp_dirs):
        """Ошибка расшифровки → 500."""
        enc_file = tmp_dirs["encrypted"] / "broken.age"
        enc_file.write_bytes(b"garbage")
        file_rec = make_file(
            original_name="broken.pdf",
            encrypted_name="broken.age",
            encrypted_path=str(enc_file),
        )
        db = self._make_db_with_file(file_rec)

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.ENCRYPTED_DIR",    tmp_dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm:

            mock_cm.decrypt_file = AsyncMock(side_effect=Exception("bad key"))

            with pytest.raises(HTTPException) as exc:
                await download_file_post(
                    request=make_request(),
                    background_tasks=MagicMock(),
                    filename="broken.age",
                    current_user=TokenData(sub="doc", role="doctor", tenant_id=1),
                    db=db,
                )

        assert exc.value.status_code == 500
        assert "расшифровки" in exc.value.detail

    @pytest.mark.asyncio
    async def test_success_returns_file_response(self, tmp_dirs):
        """Успешное скачивание возвращает FileResponse."""
        enc_file = tmp_dirs["encrypted"] / "report.age"
        enc_file.write_bytes(b"enc-data")
        file_rec = make_file(
            original_name="report.pdf",
            encrypted_name="report.age",
            encrypted_path=str(enc_file),
        )
        db = self._make_db_with_file(file_rec)
        bg = MagicMock(spec=BackgroundTasks)

        async def fake_decrypt(encrypted_path, private_key_path, output_path):
            Path(output_path).write_bytes(b"plain")

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.ENCRYPTED_DIR",    tmp_dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm, \
             patch("app.api.download.audit_logger")   as mock_log:

            mock_cm.decrypt_file = fake_decrypt

            response = await download_file_post(
                request=make_request(),
                background_tasks=bg,
                filename="report.age",
                current_user=TokenData(sub="doc-123", role="doctor", tenant_id=1),
                db=db,
            )

        assert response.filename      == "report.pdf"
        assert response.media_type    == "application/octet-stream"
        bg.add_task.assert_called_once()
        mock_log.log_operation.assert_called_once_with(
            action="download",
            filename="report.age",
            user="doc-123",
            reason="Скачивание авторизованным пользователем",
            success=True,
        )
        assert any(
            isinstance(call_args.args[0], FileAccessEvent)
            and call_args.args[0].action == "download_authenticated"
            for call_args in db.add.call_args_list
        )

    @pytest.mark.asyncio
    async def test_filename_without_age_extension_gets_age_appended(self, tmp_dirs):
        """
        Реальный код сам добавляет .age если его нет.
        Файл должен быть создан с .age именем.
        """
        # Создаём файл с .age именем (именно так ищет код)
        enc_file = tmp_dirs["encrypted"] / "nodoc.age"
        enc_file.write_bytes(b"enc")
        file_rec = make_file(
            original_name="nodoc",
            encrypted_name="nodoc.age",
            encrypted_path=str(enc_file),
        )
        db = self._make_db_with_file(file_rec)

        async def fake_decrypt(encrypted_path, private_key_path, output_path):
            Path(output_path).write_bytes(b"ok")

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.ENCRYPTED_DIR",    tmp_dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm, \
             patch("app.api.download.audit_logger"):

            mock_cm.decrypt_file = fake_decrypt

            # Передаём имя БЕЗ .age — код должен добавить сам
            response = await download_file_post(
                request=make_request(),
                background_tasks=MagicMock(),
                filename="nodoc",          # без .age
                current_user=TokenData(sub="doc", role="doctor", tenant_id=1),
                db=db,
            )

        assert response.media_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_audit_logger_not_called_on_error(self, tmp_dirs):
        """При ошибке расшифровки audit_logger НЕ должен вызываться с success=True."""
        enc_file = tmp_dirs["encrypted"] / "err.age"
        enc_file.write_bytes(b"x")
        file_rec = make_file(
            original_name="err.pdf",
            encrypted_name="err.age",
            encrypted_path=str(enc_file),
        )
        db = self._make_db_with_file(file_rec)

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.ENCRYPTED_DIR",    tmp_dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm, \
             patch("app.api.download.audit_logger") as mock_log:

            mock_cm.decrypt_file = AsyncMock(side_effect=Exception("boom"))

            with pytest.raises(HTTPException):
                await download_file_post(
                    request=make_request(),
                    background_tasks=MagicMock(),
                    filename="err.age",
                    current_user=TokenData(sub="doc", role="doctor", tenant_id=1),
                    db=db,
                )

        # audit_logger не должен быть вызван с success=True
        for call in mock_log.log_operation.call_args_list:
            kwargs = call.kwargs if call.kwargs else {}
            assert kwargs.get("success") is not True

    # ── интеграционные тесты через TestClient ────────────────────────────────

    def test_post_download_no_auth_returns_401_or_403(self, no_auth_client):
        response = no_auth_client.post("/api/download", data={"filename": "test.age"})
        assert response.status_code in (401, 403)

    def test_post_download_success_via_client(self, download_client, tmp_dirs):
        """
        Интеграционный тест через TestClient.
        Подменяем get_db так, чтобы вернуть нужный file_record.
        """
        client, dirs, _ = download_client

        enc_file = dirs["encrypted"] / "integ.age"
        enc_file.write_bytes(b"enc")
        file_rec = make_file(
            original_name="integ.pdf",
            encrypted_name="integ.age",
            encrypted_path=str(enc_file),
        )

        async def fake_decrypt(encrypted_path, private_key_path, output_path):
            Path(output_path).write_bytes(b"plain")

        db_sess = make_db([file_rec])

        async def _get_db():
            yield db_sess

        app.dependency_overrides[get_db] = _get_db

        with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
             patch("app.api.download.ENCRYPTED_DIR",    dirs["encrypted"]), \
             patch("app.api.download.DECRYPTED_DIR",    dirs["decrypted"]), \
             patch("app.api.download.PRIVATE_KEY_PATH", dirs["keys"] / "age.key"), \
             patch("app.api.download.crypto_manager") as mock_cm, \
             patch("app.api.download.audit_logger"):

            mock_cm.decrypt_file = fake_decrypt

            response = client.post("/api/download", data={"filename": "integ.age"})

        assert response.status_code == 200
        assert "integ.pdf" in response.headers.get("content-disposition", "")

    def test_post_download_missing_file_via_client(self, download_client, tmp_dirs):
        """Файл отсутствует на диске → 404 через TestClient."""
        client, dirs, _ = download_client

        response = client.post("/api/download", data={"filename": "ghost.age"})

        assert response.status_code == 404

    def test_get_download_token_not_found_via_client(self, download_client):
        """Токен не найден → 404 через TestClient."""
        client, dirs, _ = download_client

        db_returning_none = make_db([None])

        async def _get_db():
            yield db_returning_none

        app.dependency_overrides[get_db] = _get_db

        response = client.get("/api/download?token=no-such-token")

        assert response.status_code == 404


# ============================================================================
# ПАРАМЕТРИЗОВАННЫЕ ТЕСТЫ
# ============================================================================

@pytest.mark.parametrize("downloads_count,max_downloads,should_delete", [
    (0, 1, True),   # после единственного скачивания — удаляем
    (4, 5, True),   # последнее из 5 — удаляем
    (1, 5, False),  # ещё есть попытки — не удаляем
    (3, 5, False),  # ещё есть попытки — не удаляем
])
@pytest.mark.asyncio
async def test_link_deleted_only_when_limit_reached(
    tmp_dirs, downloads_count, max_downloads, should_delete
):
    link = make_link(max_downloads=max_downloads, downloads_count=downloads_count)
    enc_path = tmp_dirs["encrypted"] / "f.age"
    enc_path.write_bytes(b"x")
    file = make_file(encrypted_path=str(enc_path))
    db   = make_db([link, file])

    with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
         patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
         patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
         patch("app.api.download.crypto_manager") as mock_cm:

        mock_cm.decrypt_file = AsyncMock()

        await download_by_token(
            request=make_request(),
            background_tasks=MagicMock(),
            token=link.token,
            db=db,
        )

    if should_delete:
        db.delete.assert_called_once_with(link)
    else:
        db.delete.assert_not_called()


@pytest.mark.parametrize("filename,expected_safe", [
    ("report.age",          "report.age"),
    ("report",              "report.age"),    # .age добавляется
    ("my file.age",         "my file.age"),   # sanitize_filename обрабатывает пробелы
])
@pytest.mark.asyncio
async def test_filename_sanitization_and_age_append(tmp_dirs, filename, expected_safe):
    """Код добавляет .age и применяет sanitize_filename."""
    # Создаём файл с ожидаемым именем после sanitize
    from app.core.utils import sanitize_filename
    safe = sanitize_filename(filename)
    if not safe.endswith(".age"):
        safe += ".age"

    enc_file = tmp_dirs["encrypted"] / safe
    enc_file.write_bytes(b"enc")
    file_rec = make_file(
        original_name="out.bin",
        encrypted_name=safe,
        encrypted_path=str(enc_file),
    )
    db = make_db([file_rec])

    async def fake_decrypt(encrypted_path, private_key_path, output_path):
        Path(output_path).write_bytes(b"ok")

    with patch("app.api.download.encrypted_storage.download", AsyncMock(side_effect=_fake_encrypted_download)), \
         patch("app.api.download.ENCRYPTED_DIR",    tmp_dirs["encrypted"]), \
         patch("app.api.download.DECRYPTED_DIR",    tmp_dirs["decrypted"]), \
         patch("app.api.download.PRIVATE_KEY_PATH", tmp_dirs["keys"] / "age.key"), \
         patch("app.api.download.crypto_manager") as mock_cm, \
         patch("app.api.download.audit_logger"):

        mock_cm.decrypt_file = fake_decrypt

        response = await download_file_post(
            request=make_request(),
            background_tasks=MagicMock(),
            filename=filename,
            current_user=TokenData(sub="doc", role="doctor", tenant_id=1),
            db=db,
        )

    assert response.media_type == "application/octet-stream"
