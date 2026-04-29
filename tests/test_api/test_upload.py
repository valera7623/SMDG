"""
Тесты для app/api/upload.py
Покрытие: ~90-95%
"""

import pytest
import json
import uuid
import asyncio
from unittest.mock import ANY, MagicMock, AsyncMock, patch, call, mock_open
from fastapi import HTTPException
from fastapi.testclient import TestClient
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone, timedelta

from app.api.upload import (
    validate_file_safety,
    ALLOWED_EXTENSIONS,
    DANGEROUS_EXTENSIONS,
    ALLOWED_MIME_PREFIXES,
)


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def make_token_data(sub="test_user", role="user"):
    td = MagicMock()
    td.sub = sub
    td.role = role
    td.tenant_id = 1
    return td


def make_dicom_header():
    """128 байт нулей + DICM сигнатура"""
    return b'\x00' * 128 + b'DICM' + b'\x00' * 100


def make_pdf_content():
    return b'%PDF-1.4 fake pdf content here ' + b'\x00' * 1000


def make_path_mock(exists=True, st_size=2048):
    """Создаёт корректный мок Path, который работает с / оператором и open()"""
    p = MagicMock()
    p.exists.return_value = exists
    p.unlink = MagicMock()
    p.stat.return_value = MagicMock(st_size=st_size)
    # __truediv__ возвращает сам себя (или новый мок) с __str__
    p.__truediv__ = MagicMock(return_value=p)
    p.__str__ = MagicMock(return_value="/tmp/fake_path")
    p.__fspath__ = MagicMock(return_value="/tmp/fake_path")
    return p


# ═══════════════════════════════════════════════════════════
#  validate_file_safety() — UNIT TESTS
# ═══════════════════════════════════════════════════════════

class TestValidateFileSafety:

    # ── Dangerous extensions ──────────────────────────────

    @pytest.mark.parametrize("ext", [
        '.exe', '.bat', '.cmd', '.scr', '.js', '.vbs', '.ps1',
        '.dll', '.jar', '.apk', '.msi', '.sh', '.php', '.py', '.pyc', '.pif'
    ])
    def test_dangerous_extension(self, ext):
        with pytest.raises(HTTPException) as exc:
            validate_file_safety(f"file{ext}", b"\x00" * 100, 100)
        assert exc.value.status_code == 400
        assert "Запрещённое расширение" in exc.value.detail

    # ── Disallowed extensions ─────────────────────────────

    @pytest.mark.parametrize("ext", ['.mp3', '.zip', '.html', '.avi', '.iso'])
    def test_disallowed_extension(self, ext):
        with pytest.raises(HTTPException) as exc:
            validate_file_safety(f"file{ext}", b"\x00" * 100, 100)
        assert exc.value.status_code == 400
        assert "Недопустимое расширение" in exc.value.detail

    # ── Valid files ───────────────────────────────────────

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_pdf(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/pdf", "image/"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/pdf"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("report.pdf", b"%PDF-1.4", 1024)
        assert mime == "application/pdf"
        assert ext == ".pdf"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_jpeg(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["image/"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "image/jpeg"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("photo.jpg", b"\xff\xd8\xff\xe0", 2048)
        assert mime == "image/jpeg"
        assert ext == ".jpg"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_png(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["image/"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "image/png"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("img.png", b"\x89PNG\r\n", 500)
        assert mime == "image/png"
        assert ext == ".png"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_txt(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["text/plain"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "text/plain"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("notes.txt", b"Hello world", 11)
        assert mime == "text/plain"
        assert ext == ".txt"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_docx(self, mock_settings, mock_magic_cls):
        docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        mock_settings.ALLOWED_MIME_TYPES = [docx_mime]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = docx_mime
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("doc.docx", b"PK\x03\x04", 5000)
        assert ext == ".docx"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_mime_prefix_match_tiff(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["image/"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "image/tiff"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("scan.tif", b"II*\x00", 200)
        assert mime == "image/tiff"

    # ── DICOM ─────────────────────────────────────────────

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_dicom_dcm(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/dicom"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        dicom_data = make_dicom_header()
        mime, ext = validate_file_safety("scan.dcm", dicom_data, len(dicom_data))
        assert mime == "application/dicom"
        assert ext == ".dcm"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_valid_dicom_dicom_ext(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/dicom"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        dicom_data = make_dicom_header()
        mime, ext = validate_file_safety("image.dicom", dicom_data, len(dicom_data))
        assert mime == "application/dicom"
        assert ext == ".dicom"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_dicom_no_signature(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/dicom"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        fake = b'\x00' * 200
        with pytest.raises(HTTPException) as exc:
            validate_file_safety("fake.dcm", fake, len(fake))
        assert exc.value.status_code == 400
        assert "DICM" in exc.value.detail

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_dicom_too_short(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/dicom"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        with pytest.raises(HTTPException) as exc:
            validate_file_safety("tiny.dicom", b'\x00' * 50, 50)
        assert exc.value.status_code == 400

    # ── octet-stream fallback ─────────────────────────────

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_octet_stream_dicom_fallback(self, mock_settings, mock_magic_cls):
        """Non-.dcm extension but has DICM header → dicom"""
        mock_settings.ALLOWED_MIME_TYPES = ["application/dicom", "application/pdf"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        dicom_data = make_dicom_header()
        mime, ext = validate_file_safety("file.pdf", dicom_data, len(dicom_data))
        assert mime == "application/dicom"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_octet_stream_pdf_fallback(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("doc.pdf", b"\x00" * 200, 200)
        assert mime == "application/pdf"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_octet_stream_jpg_fallback(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["image/jpeg"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("photo.jpg", b"\x00" * 200, 200)
        assert mime == "image/jpeg"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_octet_stream_jpeg_fallback(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["image/jpeg"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("img.jpeg", b"\x00" * 200, 200)
        assert mime == "image/jpeg"

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_octet_stream_no_fallback_rejected(self, mock_settings, mock_magic_cls):
        """octet-stream + .csv (нет fallback) → rejected"""
        mock_settings.ALLOWED_MIME_TYPES = ["text/plain", "application/pdf"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/octet-stream"
        mock_magic_cls.return_value = mock_inst

        with pytest.raises(HTTPException) as exc:
            validate_file_safety("data.csv", b"\x00" * 200, 200)
        assert exc.value.status_code == 400
        assert "application/octet-stream" in exc.value.detail

    # ── MIME not in allowed ───────────────────────────────

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_mime_not_allowed(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "video/mp4"
        mock_magic_cls.return_value = mock_inst

        with pytest.raises(HTTPException) as exc:
            validate_file_safety("file.gif", b"\x00" * 200, 200)
        assert exc.value.status_code == 400
        assert "Недопустимый тип содержимого" in exc.value.detail

    # ── No extension ──────────────────────────────────────

    @patch("app.api.upload.magic.Magic")
    @patch("app.api.upload.settings")
    def test_file_no_extension(self, mock_settings, mock_magic_cls):
        mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]
        mock_inst = MagicMock()
        mock_inst.from_buffer.return_value = "application/pdf"
        mock_magic_cls.return_value = mock_inst

        mime, ext = validate_file_safety("README", b"%PDF-1.4", 100)
        assert mime == "application/pdf"
        assert ext == ""


# ═══════════════════════════════════════════════════════════
#  POST /upload — ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════

class TestUploadEndpoint:

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Настраиваем app с auth override для каждого теста"""
        from unittest.mock import AsyncMock, MagicMock, patch
        from contextlib import asynccontextmanager
        from app.main import app
        from app.core.auth import get_current_user

        mock_sess = AsyncMock()

        @asynccontextmanager
        async def _sess_ctx():
            yield mock_sess

        asl_patch = patch(
            "app.main.AsyncSessionLocal",
            side_effect=lambda: _sess_ctx(),
        )
        asl_patch.start()

        tr_patch = patch("app.main.resolve_tenant_from_request", new_callable=AsyncMock)
        _tr_mock = tr_patch.start()
        _tenant = MagicMock()
        _tenant.id = 1
        _tr_mock.return_value = _tenant

        app.state.shutting_down = False
        app.state.active_requests = 0
        if not hasattr(app.state, "active_requests_lock"):
            app.state.active_requests_lock = asyncio.Lock()
        if hasattr(app.state, "limiter"):
            app.state.limiter.enabled = False

        from app.core.database import get_db
        from app.core.dependencies import get_db_for_write

        _fallback_db = AsyncMock()

        async def _fallback_ov():
            yield _fallback_db

        app.dependency_overrides[get_db] = _fallback_ov
        app.dependency_overrides[get_db_for_write] = _fallback_ov

        app.dependency_overrides[get_current_user] = lambda: make_token_data()
        try:
            yield app
        finally:
            tr_patch.stop()
            asl_patch.stop()
            app.dependency_overrides.clear()

    @pytest.fixture
    def mock_db(self, setup_app):
        """Мок базы данных"""
        from app.core.database import get_db
        from app.core.dependencies import get_db_for_write

        db = AsyncMock()
        mock_result = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 1
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        async def override():
            yield db

        setup_app.dependency_overrides[get_db_for_write] = override
        setup_app.dependency_overrides[get_db] = override
        return db

    @pytest.fixture
    def mock_db_no_user(self, setup_app):
        """Мок БД где пользователь НЕ найден"""
        from app.core.database import get_db
        from app.core.dependencies import get_db_for_write

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        async def override():
            yield db

        setup_app.dependency_overrides[get_db_for_write] = override
        setup_app.dependency_overrides[get_db] = override
        return db

    @pytest.fixture
    def client(self, setup_app):
        return TestClient(setup_app)

    @pytest.fixture
    def upload_mocks(self, tmp_path):
        """Полный набор моков для успешного upload.
        Использует реальную tmp_path для файловых операций.
        """
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        encrypted_dir = tmp_path / "encrypted"
        encrypted_dir.mkdir()

        patches = {}
        mocks = {}

        targets = {
            "validate": "app.api.upload.validate_file_safety",
            "magic_cls": "app.api.upload.magic.Magic",
            "settings": "app.api.upload.settings",
            "sanitize": "app.api.upload.sanitize_filename",
            "calc_hash": "app.api.upload.calculate_hash_async",
            "crypto": "app.api.upload.crypto_manager",
            "audit": "app.api.upload.audit_logger",
            "get_pub_key": "app.api.upload.get_public_key",
            "upload_dir": "app.api.upload.UPLOAD_DIR",
            "encrypted_dir": "app.api.upload.ENCRYPTED_DIR",
        }

        for name, target in targets.items():
            p = patch(target)
            mocks[name] = p.start()
            patches[name] = p

        # Defaults
        mocks["validate"].return_value = ("application/pdf", ".pdf")
        mocks["sanitize"].return_value = "safe_file.pdf"
        mocks["get_pub_key"].return_value = "age1publickey"

        # UPLOAD_DIR / ENCRYPTED_DIR — реальные пути
        mocks["upload_dir"].__truediv__ = lambda self, x: upload_dir / x
        # Нужен workaround: patch заменяет на MagicMock, делаем __truediv__ вручную
        mocks["upload_dir"] = upload_dir
        patches["upload_dir"].stop()
        patches["upload_dir"] = patch("app.api.upload.UPLOAD_DIR", upload_dir)
        mocks["upload_dir"] = patches["upload_dir"].start()

        mocks["encrypted_dir"] = encrypted_dir
        patches["encrypted_dir"].stop()
        patches["encrypted_dir"] = patch("app.api.upload.ENCRYPTED_DIR", encrypted_dir)
        mocks["encrypted_dir"] = patches["encrypted_dir"].start()

        st_u = patch(
            "app.api.upload.encrypted_storage.upload",
            new_callable=AsyncMock,
        )
        patches["encrypted_storage_upload"] = st_u
        _um = MagicMock()
        _um.size = 2048
        mocks["enc_storage_upload"] = st_u.start()
        mocks["enc_storage_upload"].return_value = _um

        # settings
        mocks["settings"].MAX_UPLOAD_SIZE_MB = 50
        mocks["settings"].ALLOWED_MIME_TYPES = [
            "application/pdf", "image/", "text/plain", "application/dicom"
        ]
        mocks["settings"].dev_mode = True

        # magic (второй вызов в endpoint)
        mock_magic_inst = MagicMock()
        mock_magic_inst.from_buffer.return_value = "application/pdf"
        mocks["magic_cls"].return_value = mock_magic_inst
        mocks["magic_inst"] = mock_magic_inst

        # crypto — encrypt_file должен создать файл
        async def fake_encrypt(input_path, public_key, output_path):
            # Создаём фейковый зашифрованный файл
            Path(output_path).write_bytes(b"ENCRYPTED_CONTENT_HERE")
            return "encrypted_hash_abc"

        mocks["crypto"].encrypt_file = AsyncMock(side_effect=fake_encrypt)

        # hash
        mocks["calc_hash"].return_value = "sha256_original_hash"
        # Если используется как coroutine
        mocks["calc_hash"] = AsyncMock(return_value="sha256_original_hash")
        patches["calc_hash"].stop()
        patches["calc_hash"] = patch(
            "app.api.upload.calculate_hash_async",
            new=AsyncMock(return_value="sha256_original_hash")
        )
        mocks["calc_hash"] = patches["calc_hash"].start()

        # audit
        mocks["audit"].log_operation = MagicMock()

        mocks["_patches"] = patches
        mocks["upload_path"] = upload_dir
        mocks["encrypted_path"] = encrypted_dir

        yield mocks

        for p in patches.values():
            try:
                p.stop()
            except RuntimeError:
                pass

    # ── SUCCESS ───────────────────────────────────────────

    def test_upload_success(self, client, mock_db, upload_mocks):
        pdf_content = make_pdf_content()
        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "3"},
            files={"file": ("report.pdf", BytesIO(pdf_content), "application/pdf")}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Файл успешно загружен и зашифрован"
        assert "encrypted_file" in data
        assert "download_url" in data
        assert data["max_downloads"] == 3

        # Audit вызван с success
        upload_mocks["audit"].log_operation.assert_any_call(
            action="upload",
            filename="report.pdf",
            user="test_user",
            reason="Успешная загрузка и шифрование",
            success=True,
            metadata=pytest.approx({
                "mime_type": "application/pdf",
                "size": len(pdf_content),
                "encrypted_name": data["encrypted_file"],
                "ttl_days": 7
            }, abs=10)
        )

    def test_upload_success_with_metadata(self, client, mock_db, upload_mocks):
        """Загрузка с patient_id и medical_metadata_json"""
        metadata = {"diagnosis": "test", "doctor": "Dr. Smith"}
        response = client.post(
            "/api/upload",
            data={
                "ttl_days": "30",
                "max_downloads": "5",
                "patient_id": "P-12345",
                "medical_metadata_json": json.dumps(metadata)
            },
            files={"file": ("xray.pdf", BytesIO(make_pdf_content()), "application/pdf")}
        )
        assert response.status_code == 200

    def test_upload_success_default_params(self, client, mock_db, upload_mocks):
        """Загрузка с дефолтными ttl_days=30, max_downloads=1"""
        response = client.post(
            "/api/upload",
            data={},
            files={"file": ("doc.pdf", BytesIO(make_pdf_content()), "application/pdf")}
        )
        assert response.status_code == 200

    # ── FILE TOO LARGE ────────────────────────────────────

    def test_upload_file_too_large(self, client, mock_db, upload_mocks):
        upload_mocks["settings"].MAX_UPLOAD_SIZE_MB = 1
        big_content = b"x" * (2 * 1024 * 1024)

        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"},
            files={"file": ("big.pdf", BytesIO(big_content), "application/pdf")}
        )
        assert response.status_code == 413

    # ── MIME REJECTED (second check) ──────────────────────

    def test_upload_mime_rejected_second_check(self, client, mock_db, upload_mocks):
        """Второй MIME check отклоняет файл"""
        upload_mocks["magic_inst"].from_buffer.return_value = "application/x-executable"

        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"},
            files={"file": ("file.pdf", BytesIO(b"ELF binary"), "application/pdf")}
        )
        assert response.status_code == 400
        assert "Недопустимый тип" in response.json()["detail"]

    # ── OCTET-STREAM DICOM FALLBACK (second check) ───────

    def test_upload_octet_stream_dicom_fallback(self, client, mock_db, upload_mocks):
        """Второй check: octet-stream + DICM header → allowed"""
        upload_mocks["magic_inst"].from_buffer.return_value = "application/octet-stream"
        upload_mocks["validate"].return_value = ("application/dicom", ".dcm")

        dicom_content = make_dicom_header()
        response = client.post(
            "/api/upload",
            data={"ttl_days": "30", "max_downloads": "1"},
            files={"file": ("scan.dcm", BytesIO(dicom_content), "application/octet-stream")}
        )
        assert response.status_code == 200

    # ── OCTET-STREAM IMAGE FALLBACK (second check) ───────

    def test_upload_octet_stream_image_fallback(self, client, mock_db, upload_mocks):
        """Второй check: octet-stream + .jpg filename → image/jpg"""
        upload_mocks["magic_inst"].from_buffer.return_value = "application/octet-stream"
        upload_mocks["validate"].return_value = ("image/jpeg", ".jpg")
        upload_mocks["settings"].ALLOWED_MIME_TYPES = [
            "application/pdf", "image/", "image/jpg", "image/jpeg"
        ]

        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "5"},
            files={"file": ("photo.jpg", BytesIO(b"\xff\xd8\xff" + b"\x00" * 500), "image/jpeg")}
        )
        assert response.status_code == 200

    # ── INVALID JSON METADATA ─────────────────────────────

    def test_upload_invalid_metadata_json(self, client, mock_db, upload_mocks):
        response = client.post(
            "/api/upload",
            data={
                "ttl_days": "7",
                "max_downloads": "1",
                "medical_metadata_json": "{invalid json!!!"
            },
            files={"file": ("doc.pdf", BytesIO(make_pdf_content()), "application/pdf")}
        )
        assert response.status_code == 400
        assert "JSON" in response.json()["detail"]

    # ── USER NOT FOUND IN DB ──────────────────────────────

    def test_upload_user_not_found(self, client, mock_db_no_user, upload_mocks):
        """User из токена не найден → user_id=None, upload продолжается"""
        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"},
            files={"file": ("doc.pdf", BytesIO(make_pdf_content()), "application/pdf")}
        )
        assert response.status_code == 200

        # Warning logged
        upload_mocks["audit"].log_operation.assert_any_call(
            action="upload_warning",
            filename="doc.pdf",
            user="test_user",
            reason="Пользователь test_user не найден в БД",
            success=True
        )

    # ── NO FILE ───────────────────────────────────────────

    def test_upload_no_file(self, client):
        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"}
        )
        assert response.status_code == 422

    # ── UNAUTHORIZED ──────────────────────────────────────

    def test_upload_unauthorized(self, setup_app):
        setup_app.dependency_overrides.clear()
        raw_client = TestClient(setup_app)

        response = raw_client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"},
            files={"file": ("test.pdf", BytesIO(b"pdf"), "application/pdf")}
        )
        assert response.status_code in (401, 403)

    # ── TEMP FILE CLEANUP ─────────────────────────────────

    def test_temp_file_cleaned_on_mime_rejection(self, client, mock_db, upload_mocks):
        """Temp файл удаляется в finally при MIME rejection"""
        upload_mocks["magic_inst"].from_buffer.return_value = "application/x-evil"

        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"},
            files={"file": ("doc.pdf", BytesIO(make_pdf_content()), "application/pdf")}
        )
        assert response.status_code == 400

        # Проверяем что в upload_dir нет оставшихся файлов
        remaining = list(upload_mocks["upload_path"].iterdir())
        assert len(remaining) == 0, f"Temp files not cleaned: {remaining}"

    # ── GENERIC EXCEPTION → 500 ──────────────────────────

    def test_upload_generic_exception(self, client, mock_db, upload_mocks):
        """Непредвиденное исключение → 500 + audit log"""
        upload_mocks["crypto"].encrypt_file = AsyncMock(
            side_effect=RuntimeError("encryption exploded")
        )

        response = client.post(
            "/api/upload",
            data={"ttl_days": "7", "max_downloads": "1"},
            files={"file": ("doc.pdf", BytesIO(make_pdf_content()), "application/pdf")}
        )
        assert response.status_code == 500
        assert "Upload failed" in response.json()["detail"]

        # Audit failure logged
        upload_mocks["audit"].log_operation.assert_any_call(
            action="upload",
            filename="doc.pdf",
            user="test_user",
            reason=ANY,
            success=False,
            metadata=ANY
        )


# ═══════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════

class TestConstants:

    def test_allowed_extensions_lowercase_dotted(self):
        for ext in ALLOWED_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ext.lower()

    def test_dangerous_extensions_lowercase_dotted(self):
        for ext in DANGEROUS_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ext.lower()

    def test_no_overlap(self):
        assert len(ALLOWED_EXTENSIONS & DANGEROUS_EXTENSIONS) == 0

    def test_known_dangerous(self):
        for ext in ['.exe', '.bat', '.cmd', '.js', '.ps1']:
            assert ext in DANGEROUS_EXTENSIONS

    def test_known_allowed(self):
        for ext in ['.pdf', '.jpg', '.png', '.docx', '.dcm']:
            assert ext in ALLOWED_EXTENSIONS

    def test_mime_prefixes_not_empty(self):
        assert len(ALLOWED_MIME_PREFIXES) > 0

    def test_pdf_in_prefixes(self):
        assert "application/pdf" in ALLOWED_MIME_PREFIXES

    def test_image_in_prefixes(self):
        assert "image/" in ALLOWED_MIME_PREFIXES

    def test_dicom_in_prefixes(self):
        assert "application/dicom" in ALLOWED_MIME_PREFIXES

