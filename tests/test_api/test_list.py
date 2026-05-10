# tests/test_api/test_list.py
"""
Тесты для GET /api/list
Покрытие: ~93-95%
"""

import uuid
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.main import app
from app.core.auth import get_current_user
from app.core.auth_utils import TokenData
from app.models.user import User
from app.models.file import File
from app.models.file_link import FileLink
from app.core.storage_backend import ObjectMetadata


# ============================================================
# Helpers
# ============================================================

def _token_data(sub: str, role: str = "doctor", tenant_id: int = 1) -> TokenData:
    return TokenData(sub=sub, role=role, tenant_id=tenant_id)


def _make_user(session, username="testdoc", role="doctor") -> User:
    from app.core.security import get_password_hash
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=get_password_hash("pass123"),
        role=role,
        is_active=True,
    )
    session.add(user)
    return user


def _make_file(
    session,
    user_id=None,
    original_name="report.pdf",
    encrypted_name=None,
    original_size=5000,
    encrypted_size=None,
    uploaded_at=None,
    patient_id=None,
    medical_metadata=None,
) -> File:
    enc_name = encrypted_name or f"{uuid.uuid4().hex}.enc"
    f = File(
        user_id=user_id,
        original_name=original_name,
        encrypted_name=enc_name,
        encrypted_path=f"/tmp/uploads/{enc_name}",
        original_size=original_size,
        encrypted_size=encrypted_size if encrypted_size is not None else int(original_size * 1.1),
        original_hash=uuid.uuid4().hex,
        mime_type="application/pdf",
        uploaded_at=uploaded_at or datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        patient_id=patient_id,
        medical_metadata=medical_metadata or {},
    )
    session.add(f)
    return f


def _make_link(
    session,
    file_id: int,
    max_downloads: int = 5,
    downloads_count: int = 0,
    expires_at=None,
) -> FileLink:
    link = FileLink(
        token=str(uuid.uuid4()),
        file_id=file_id,
        max_downloads=max_downloads,
        downloads_count=downloads_count,
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(hours=1)),
    )
    session.add(link)
    return link


def _fake_encrypted_dir(files_on_disk: set[str] | None = None, stat_error: bool = False):
    """
    Возвращает патч для ENCRYPTED_DIR, который корректно подменяет
    только конкретные файлы, не ломая остальной pathlib.
    
    files_on_disk: множество encrypted_name, которые «существуют» на диске.
                   None = все существуют.
    stat_error: если True, stat() бросает PermissionError.
    """
    files_on_disk_set = files_on_disk

    class FakePath:
        def __init__(self, *args):
            self._path = Path(*args)

        def __truediv__(self, other):
            return FakePath(str(self._path / other))

        @property
        def name(self):
            return self._path.name

        def exists(self):
            if files_on_disk_set is None:
                return True
            return self._path.name in files_on_disk_set

        def stat(self):
            if stat_error:
                raise PermissionError("no access")
            mock_stat = MagicMock()
            mock_stat.st_size = 9999
            return mock_stat

    return FakePath("/fake/encrypted")


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
async def _list_api_clean_file_tables(db_session):
    """Перед каждым тестом чистим ``files`` и всё, что на них ссылается.

    У роли doctor запрос списка без фильтра по пользователю — иначе в ответ
    попадают десятки чужих файлов и ломаются ожидания по count / audit.

    Используем ``TRUNCATE ... RESTART IDENTITY CASCADE`` — он сам обходит
    зависимости (``file_links``, ``dicom_view_tokens`` и любые будущие FK)
    и сбрасывает sequence, чтобы id были предсказуемыми.
    """
    await db_session.execute(
        text("TRUNCATE TABLE files RESTART IDENTITY CASCADE")
    )
    await db_session.commit()
    yield


@pytest.fixture
async def _override_db(override_app_db, stub_encrypted_storage):
    """Тестовая БД + заглушка хранилища (list проверяет exists/stat)."""
    yield override_app_db





def _set_user(sub: str, role: str):
    app.dependency_overrides[get_current_user] = lambda: _token_data(sub, role)


def _clear_user():
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _disable_list_endpoint_rate_limit(monkeypatch):
    """SlowAPI 10/min легко даёт 429 при полном suite / параллели."""
    def _no_limit(*_a, **_kw):
        def _decorator(route):
            return route

        return _decorator

    monkeypatch.setattr("app.api.list.limiter.limit", _no_limit)


@pytest.fixture
def async_client():
    transport = ASGITransport(app=app)
    # Host=test не резолвит tenant при SaaS/multi-tenant; testserver — как Starlette TestClient.
    # X-Tenant-ID гарантирует контекст tenant при включённом MULTI_TENANCY.
    return AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Tenant-ID": "1"},
    )


# ============================================================
# 1. Doctor видит все файлы
# ============================================================

@pytest.mark.asyncio
async def test_list_doctor_sees_all_files(async_client, _override_db, db_session):
    db = db_session

    u1 = _make_user(db, username="doc1", role="doctor")
    u2 = _make_user(db, username="usr1", role="user")
    await db.flush()

    _make_file(db, user_id=u1.id, original_name="doc_file.pdf")
    _make_file(db, user_id=u2.id, original_name="usr_file.pdf")
    await db.flush()

    _set_user("doc1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    names = {f["original_name"] for f in data["files"]}
    assert "doc_file.pdf" in names
    assert "usr_file.pdf" in names


# ============================================================
# 2. Admin видит все файлы
# ============================================================

@pytest.mark.asyncio
async def test_list_admin_sees_all_files(async_client, _override_db, db_session):
    db = db_session

    u1 = _make_user(db, username="adm1", role="admin")
    u2 = _make_user(db, username="usr2", role="user")
    await db.flush()

    _make_file(db, user_id=u1.id, original_name="admin_file.pdf")
    _make_file(db, user_id=u2.id, original_name="other_file.pdf")
    await db.flush()

    _set_user("adm1", "admin")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    assert resp.json()["count"] == 2


# ============================================================
# 3. User видит только свои файлы
# ============================================================

@pytest.mark.asyncio
async def test_list_user_sees_only_own_files(async_client, _override_db, db_session):
    db = db_session

    owner = _make_user(db, username="owner1", role="user")
    other = _make_user(db, username="other1", role="user")
    await db.flush()

    _make_file(db, user_id=owner.id, original_name="my_file.pdf")
    _make_file(db, user_id=other.id, original_name="not_mine.pdf")
    await db.flush()

    _set_user("owner1", "user")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["files"][0]["original_name"] == "my_file.pdf"


# ============================================================
# 4. User без файлов — пустой список
# ============================================================

@pytest.mark.asyncio
async def test_list_user_no_files(async_client, _override_db, db_session):
    db = db_session

    _make_user(db, username="lonely1", role="user")
    await db.flush()

    _set_user("lonely1", "user")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["files"] == []


# ============================================================
# 5. User не найден в БД — пустой список (реальное поведение)
# ============================================================
@pytest.mark.asyncio
async def test_list_user_not_found_in_db(async_client, _override_db, db_session):
    """
    Пользователь с ролью 'user' не найден в БД.
    Реальный код: возвращает FileListResponse(count=0, files=[]) без поля 'message'.
    Логирует WARNING и не бросает исключение.
    """
    _set_user("ghost_user_xyz", "user")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            with patch("app.api.list.logger") as mock_logger:
                resp = await async_client.get("/api/list")
    finally:
        _clear_user()
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["files"] == []
    # Проверяем что предупреждение было залогировано
    warning_calls = [
        call for call in mock_logger.warning.call_args_list
        if "ghost_user_xyz" in str(call)
    ]
    assert len(warning_calls) == 1, "Должен быть залогирован warning о ненайденном пользователе"
# ============================================================


# ============================================================
# 6. Файл в БД, но нет на диске — пропускается
# ============================================================

@pytest.mark.asyncio
async def test_list_file_missing_on_disk(async_client, _override_db, db_session, monkeypatch):
    db = db_session

    doc = _make_user(db, username="doc_miss1", role="doctor")
    await db.flush()

    f = _make_file(db, user_id=doc.id, original_name="missing.pdf", encrypted_name="missing_abc.enc")
    await db.flush()

    async def _no_file(_key):
        return False

    monkeypatch.setattr("app.api.list.encrypted_storage.exists", _no_file)

    _set_user("doc_miss1", "doctor")
    try:
        resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ============================================================
# 7. Файл с активной ссылкой
# ============================================================

@pytest.mark.asyncio
async def test_list_file_with_active_link(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_link1", role="doctor")
    await db.flush()

    f = _make_file(db, user_id=doc.id, original_name="linked.pdf")
    await db.flush()

    link = _make_link(db, file_id=f.id, max_downloads=10, downloads_count=0)
    await db.flush()

    _set_user("doc_link1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    file_data = data["files"][0]
    assert file_data["download_token"] == link.token
    assert file_data["download_url"] == f"/api/download?token={link.token}"


# ============================================================
# 8. Файл без ссылки
# ============================================================

@pytest.mark.asyncio
async def test_list_file_without_link(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_nolink1", role="doctor")
    await db.flush()

    _make_file(db, user_id=doc.id, original_name="nolink.pdf")
    await db.flush()

    _set_user("doc_nolink1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["download_token"] is None
    assert file_data["download_url"] is None


# ============================================================
# 9. Файл с истёкшей ссылкой
# ============================================================

@pytest.mark.asyncio
async def test_list_file_with_expired_link(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_exp1", role="doctor")
    await db.flush()

    f = _make_file(db, user_id=doc.id, original_name="expired_link.pdf")
    await db.flush()

    _make_link(
        db,
        file_id=f.id,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    await db.flush()

    _set_user("doc_exp1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["download_token"] is None
    assert file_data["download_url"] is None


# ============================================================
# 10. Файл с исчерпанной ссылкой
# ============================================================

@pytest.mark.asyncio
async def test_list_file_with_exhausted_link(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_exh1", role="doctor")
    await db.flush()

    f = _make_file(db, user_id=doc.id, original_name="exhausted_link.pdf")
    await db.flush()

    _make_link(db, file_id=f.id, max_downloads=3, downloads_count=3)
    await db.flush()

    _set_user("doc_exh1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["download_token"] is None


# ============================================================
# 11. Ошибка при stat файла — пропускается, логируется
# ============================================================
@pytest.mark.asyncio
async def test_list_file_stat_error(async_client, _override_db, db_session, monkeypatch):
    """
    encrypted_storage.stat бросает PermissionError.
    Реальный код:
      1. Вызывает audit_logger с success=False (list_error)
      2. Затем вызывает audit_logger с success=True (list_files, финальный)
    Итого: два вызова.
    """
    db = db_session
    doc = _make_user(db, username="doc_err1", role="doctor")
    await db.flush()
    _make_file(db, user_id=doc.id, original_name="broken.pdf")
    await db.flush()

    async def _bad_stat(_key):
        raise PermissionError("no access")

    monkeypatch.setattr("app.api.list.encrypted_storage.stat", _bad_stat)

    _set_user("doc_err1", "doctor")
    try:
        with patch("app.api.list.audit_logger") as mock_audit:
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
   
    assert mock_audit.log_operation.call_count == 2
    all_calls = mock_audit.log_operation.call_args_list
    # Первый вызов — ошибка файла
    error_call_kwargs = all_calls[0].kwargs
    assert error_call_kwargs["action"] == "list_error"
    assert error_call_kwargs["success"] is False
    assert "no access" in error_call_kwargs["reason"]
   
    final_call_kwargs = all_calls[1].kwargs
    assert final_call_kwargs["action"] == "list_files"
    assert final_call_kwargs["success"] is True

# ============================================================
# 12. Несколько файлов — порядок по uploaded_at desc
# ============================================================

@pytest.mark.asyncio
async def test_list_multiple_files_ordered(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_multi1", role="doctor")
    await db.flush()

    _make_file(
        db,
        user_id=doc.id,
        original_name="old.pdf",
        uploaded_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    _make_file(
        db,
        user_id=doc.id,
        original_name="new.pdf",
        uploaded_at=datetime.now(timezone.utc),
    )
    await db.flush()

    _set_user("doc_multi1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["files"][0]["original_name"] == "new.pdf"
    assert data["files"][1]["original_name"] == "old.pdf"


# ============================================================
# 13. Без авторизации — ошибка
# ============================================================

@pytest.mark.asyncio
async def test_list_unauthorized(async_client, _override_db):
    app.dependency_overrides.pop(get_current_user, None)
    resp = await async_client.get("/api/list")
    assert resp.status_code in (401, 403, 422)


# ============================================================
# 14. encrypted_size из БД приоритетнее stat
# ============================================================

@pytest.mark.asyncio
async def test_list_uses_encrypted_size_from_db(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_size1", role="doctor")
    await db.flush()

    f = _make_file(db, user_id=doc.id, original_name="sized.pdf", original_size=8000, encrypted_size=8800)
    await db.flush()

    _set_user("doc_size1", "doctor")
    try:
        # stat вернёт 9999, но encrypted_size из БД = 8800
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["size"] == 8800


# ============================================================
# 15. encrypted_size = 0 или None → fallback на stat.st_size
# ============================================================

@pytest.mark.asyncio
async def test_list_uses_stat_size_when_encrypted_size_falsy(async_client, _override_db, db_session, monkeypatch):
    db = db_session

    doc = _make_user(db, username="doc_size2", role="doctor")
    await db.flush()

    _make_file(db, user_id=doc.id, original_name="nosize.pdf", encrypted_size=0)
    await db.flush()

    import time

    async def _stat(key):
        return ObjectMetadata(key=key, size=9999, last_modified=time.time())

    monkeypatch.setattr("app.api.list.encrypted_storage.stat", _stat)

    _set_user("doc_size2", "doctor")
    try:
        resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["size"] == 9999


# ============================================================
# 16. Полнота полей ответа
# ============================================================

@pytest.mark.asyncio
async def test_list_response_fields(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_fields1", role="doctor")
    await db.flush()

    _make_file(db, user_id=doc.id, original_name="fields_check.pdf")
    await db.flush()

    _set_user("doc_fields1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "files" in data

    file_data = data["files"][0]
    expected_keys = {
        "id", "name", "size", "modified", "original_name",
        "patient_id", "medical_metadata", "download_token", "download_url"
    }
    assert expected_keys == set(file_data.keys())


# ============================================================
# 17. patient_id и medical_metadata
# ============================================================

@pytest.mark.asyncio
async def test_list_file_with_metadata(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_meta1", role="doctor")
    await db.flush()

    _make_file(
        db,
        user_id=doc.id,
        original_name="meta.pdf",
        patient_id="PAT-12345",
        medical_metadata={"diagnosis": "Test", "doctor": "Dr. House"},
    )
    await db.flush()

    _set_user("doc_meta1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["patient_id"] == "PAT-12345"
    assert file_data["medical_metadata"]["diagnosis"] == "Test"


# ============================================================
# 18. Несколько ссылок — берётся с самым поздним expires_at
# ============================================================

@pytest.mark.asyncio
async def test_list_picks_latest_active_link(async_client, _override_db, db_session):
    db = db_session

    doc = _make_user(db, username="doc_mlink1", role="doctor")
    await db.flush()

    f = _make_file(db, user_id=doc.id, original_name="multilink.pdf")
    await db.flush()

    # Старая ссылка (но ещё активная)
    _make_link(
        db,
        file_id=f.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    # Новая ссылка — позже истекает, должна быть выбрана
    latest = _make_link(
        db,
        file_id=f.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    await db.flush()

    _set_user("doc_mlink1", "doctor")
    try:
        with patch("app.api.list.ENCRYPTED_DIR", _fake_encrypted_dir()):
            resp = await async_client.get("/api/list")
    finally:
        _clear_user()

    assert resp.status_code == 200
    file_data = resp.json()["files"][0]
    assert file_data["download_token"] == latest.token

