"""Тесты для ``app/api/archive.py`` (админские эндпоинты архива)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.models.archive import ArchiveRecord, ArchiveRestoreRequest
from app.services.archive_service import archive_service


def _make_archive_record(
    *,
    source_type: str = "file",
    source_id: int = 1,
    archive_id: str | None = None,
    archive_size_bytes: int = 1024,
    status: str = "archived",
) -> ArchiveRecord:
    now = datetime.now(timezone.utc)
    aid = archive_id or str(uuid.uuid4())
    return ArchiveRecord(
        archive_id=aid,
        source_type=source_type,
        source_id=source_id,
        source_table="files",
        archive_path=f"/tmp/archive/{aid}.bin",
        archive_size_bytes=archive_size_bytes,
        archive_checksum="a" * 64,
        storage_tier="glacier",
        retention_until=now + timedelta(days=365),
        original_metadata={"k": "v"},
        status=status,
        archived_at=now,
    )


@pytest.fixture
def admin_token_data() -> TokenData:
    return TokenData(sub="admin-archive-test", role="admin", tenant_id=1)


@pytest_asyncio.fixture
async def patch_archive_sessions(monkeypatch, db_session):
    """Подмена ``AsyncSessionLocal`` на тестовую сессию (импорты в api и service)."""

    class _FakeMaker:
        def __call__(self, *args, **kwargs):
            class _CM:
                async def __aenter__(self_inner):
                    return db_session

                async def __aexit__(self_inner, *args_inner):
                    return None

            return _CM()

    fake = _FakeMaker()
    monkeypatch.setattr("app.api.archive.AsyncSessionLocal", fake)
    monkeypatch.setattr("app.services.archive_service.AsyncSessionLocal", fake)


@pytest_asyncio.fixture
async def archive_async_client(
    admin_token_data,
    patch_archive_sessions,
    monkeypatch,
):
    """AsyncClient на том же event loop, что и ``db_session`` (избегаем teardown loop mismatch)."""

    async def _admin_dep():
        return admin_token_data

    app.dependency_overrides[get_current_admin] = _admin_dep
    monkeypatch.setattr(
        archive_service,
        "_execute_restore",
        AsyncMock(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_current_admin, None)


@pytest_asyncio.fixture
async def archive_async_client_real_sessions(admin_token_data, monkeypatch):
    """Тот же URL БД, что и у тестов, без подмены ``AsyncSessionLocal`` — для полного покрытия тела роутов."""
    async def _admin_dep():
        return admin_token_data

    app.dependency_overrides[get_current_admin] = _admin_dep
    monkeypatch.setattr(
        archive_service,
        "_execute_restore",
        AsyncMock(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_current_admin, None)


async def _clear_archive_tables(db_session):
    await db_session.execute(delete(ArchiveRestoreRequest))
    await db_session.execute(delete(ArchiveRecord))
    await db_session.commit()


@pytest.mark.asyncio
class TestArchiveStats:
    async def test_get_stats_empty(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        r = await archive_async_client.get("/api/archive/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total_archived"] == 0
        assert data["by_type"] == {}
        assert data["total_size_bytes"] == 0
        assert data["total_size_gb"] == 0.0
        assert data["restore_requests"] == {}

    async def test_get_stats_aggregates(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        db_session.add(_make_archive_record(source_type="file", source_id=10, archive_size_bytes=1000))
        db_session.add(_make_archive_record(source_type="audit", source_id=0, archive_size_bytes=500))
        await db_session.commit()

        r = await archive_async_client.get("/api/archive/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total_archived"] == 2
        assert data["by_type"]["file"] == 1
        assert data["by_type"]["audit"] == 1
        assert data["total_size_bytes"] == 1500
        assert data["restore_requests"] == {}


@pytest.mark.asyncio
class TestListArchiveRecords:
    async def test_list_empty(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        r = await archive_async_client.get("/api/archive/records")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["records"] == []
        assert body["limit"] == 50
        assert body["offset"] == 0

    async def test_list_serializes_rows(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        aid = str(uuid.uuid4())
        rec = _make_archive_record(archive_id=aid, source_type="file", source_id=42)
        db_session.add(rec)
        await db_session.commit()

        r = await archive_async_client.get("/api/archive/records")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["records"]) == 1
        row = body["records"][0]
        assert row["archive_id"] == aid
        assert row["source_type"] == "file"
        assert row["source_id"] == 42
        assert row["archive_size_bytes"] == 1024
        assert row["storage_tier"] == "glacier"
        assert "retention_until" in row
        assert row["status"] == "archived"
        assert "archived_at" in row

    async def test_list_filter_by_source_type(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        db_session.add(_make_archive_record(source_type="file", source_id=1))
        db_session.add(_make_archive_record(source_type="user", source_id=2))
        await db_session.commit()

        r = await archive_async_client.get(
            "/api/archive/records",
            params={"source_type": "user"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["records"][0]["source_type"] == "user"

    async def test_list_pagination(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        for _ in range(3):
            db_session.add(_make_archive_record(source_id=0, archive_id=str(uuid.uuid4())))
        await db_session.commit()

        r = await archive_async_client.get(
            "/api/archive/records",
            params={"limit": 2, "offset": 1},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert body["limit"] == 2
        assert body["offset"] == 1
        assert len(body["records"]) == 2


@pytest.mark.asyncio
class TestRestoreFromArchive:
    async def test_restore_success_returns_pending(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        aid = str(uuid.uuid4())
        db_session.add(_make_archive_record(archive_id=aid))
        await db_session.commit()

        r = await archive_async_client.post(
            f"/api/archive/restore/{aid}",
            params={"reason": "compliance review requested"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert "request_id" in data
        uuid.UUID(data["request_id"])

    async def test_restore_missing_record_404(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        r = await archive_async_client.post(
            "/api/archive/restore/00000000-0000-0000-0000-000000000001",
            params={"reason": "need data back"},
        )
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
class TestListRestoreRequests:
    async def test_list_empty(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        r = await archive_async_client.get("/api/archive/restore-requests")
        assert r.status_code == 200
        assert r.json()["requests"] == []

    async def test_list_serializes_requests(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        aid = str(uuid.uuid4())
        db_session.add(_make_archive_record(archive_id=aid))
        await db_session.flush()

        now = datetime.now(timezone.utc)
        req = ArchiveRestoreRequest(
            archive_id=aid,
            requested_by="admin-1",
            request_reason="audit",
            status="completed",
            created_at=now,
            completed_at=now + timedelta(minutes=1),
            error_message=None,
        )
        db_session.add(req)
        await db_session.commit()

        r = await archive_async_client.get("/api/archive/restore-requests")
        assert r.status_code == 200
        items = r.json()["requests"]
        assert len(items) == 1
        row = items[0]
        assert row["archive_id"] == aid
        assert row["requested_by"] == "admin-1"
        assert row["status"] == "completed"
        assert row["completed_at"] is not None
        assert row["error_message"] is None

    async def test_list_pending_without_completed_at(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        aid = str(uuid.uuid4())
        db_session.add(_make_archive_record(archive_id=aid))
        await db_session.flush()

        req = ArchiveRestoreRequest(
            archive_id=aid,
            requested_by="x",
            request_reason="reason here",
            status="pending",
            created_at=datetime.now(timezone.utc),
            completed_at=None,
            error_message=None,
        )
        db_session.add(req)
        await db_session.commit()

        r = await archive_async_client.get(
            "/api/archive/restore-requests",
            params={"status": "pending"},
        )
        assert r.status_code == 200
        row = r.json()["requests"][0]
        assert row["completed_at"] is None

    async def test_filter_by_status(self, db_session, archive_async_client):
        await _clear_archive_tables(db_session)
        aid = str(uuid.uuid4())
        db_session.add(_make_archive_record(archive_id=aid))
        await db_session.flush()

        db_session.add(
            ArchiveRestoreRequest(
                archive_id=aid,
                requested_by="a",
                request_reason="r1",
                status="failed",
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                error_message="boom",
            )
        )
        await db_session.commit()

        r = await archive_async_client.get(
            "/api/archive/restore-requests",
            params={"status": "failed"},
        )
        assert r.status_code == 200
        assert len(r.json()["requests"]) == 1
        assert r.json()["requests"][0]["error_message"] == "boom"


@pytest.mark.asyncio
class TestArchiveRealSessionCoverage:
    """Доп. кейсы через реальный ``AsyncSessionLocal`` (после ``commit`` виден второму пулу)."""

    async def test_list_records_and_restore_requests_hit_execute_branch(
        self,
        db_session,
        archive_async_client_real_sessions,
    ):
        await _clear_archive_tables(db_session)
        aid = str(uuid.uuid4())
        db_session.add(_make_archive_record(archive_id=aid, source_type="audit"))
        await db_session.commit()

        r1 = await archive_async_client_real_sessions.get("/api/archive/records")
        assert r1.status_code == 200
        assert r1.json()["total"] >= 1

        now = datetime.now(timezone.utc)
        db_session.add(
            ArchiveRestoreRequest(
                archive_id=aid,
                requested_by="real-pool",
                request_reason="coverage",
                status="processing",
                created_at=now,
                completed_at=None,
                error_message=None,
            )
        )
        await db_session.commit()

        r2 = await archive_async_client_real_sessions.get(
            "/api/archive/restore-requests",
            params={"status": "processing", "limit": 10},
        )
        assert r2.status_code == 200
        assert any(x["archive_id"] == aid for x in r2.json()["requests"])


@pytest.mark.asyncio
class TestRestoreHttpExceptionMapping:
    async def test_restore_valueerror_becomes_404(
        self,
        archive_async_client,
        monkeypatch,
    ):
        async def _boom(*_a, **_kw):
            raise ValueError("Archive record missing")

        monkeypatch.setattr(archive_service, "restore_from_archive", _boom)

        r = await archive_async_client.post(
            "/api/archive/restore/any-id",
            params={"reason": "valid reason string"},
        )
        assert r.status_code == 404
        assert "missing" in r.json()["detail"].lower()
