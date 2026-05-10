"""Тесты ``app/api/admin_audit_export.py``."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.audit_export import AuditExportStats


@pytest.fixture
def admin_td() -> TokenData:
    return TokenData(sub="admin-audit-exp", role="admin", tenant_id=1)


@pytest.fixture(autouse=True)
def _noop_audit_export_decorators(monkeypatch):
    """Не гоняем реальный bulkhead/timeout в HTTP-тестах."""

    def _bulkhead(*_a, **_kw):
        def _wrap(fn):
            return fn

        return _wrap

    def _timeout(*_a, **_kw):
        def _wrap(fn):
            return fn

        return _wrap

    monkeypatch.setattr("app.api.admin_audit_export.bulkhead", _bulkhead)
    monkeypatch.setattr("app.api.admin_audit_export.timeout", _timeout)


@pytest_asyncio.fixture
async def admin_audit_client(admin_td):
    async def _admin():
        return admin_td

    app.dependency_overrides[get_current_admin] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Tenant-ID": "1"},
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_admin, None)


def _sample_rows():
    return [
        {
            "timestamp": "2025-01-01T12:00:00Z",
            "user": "alice",
            "action": "GET /api/health",
            "ip": "127.0.0.1",
            "success": True,
        }
    ]


def _stats_for(rows):
    s = AuditExportStats()
    for r in rows:
        s.add_entry(r)
    return s


@pytest.mark.asyncio
async def test_export_invalid_date_range_returns_400(admin_audit_client):
    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "csv",
            "start_date": "2025-06-10",
            "end_date": "2025-01-01",
        },
    )
    assert r.status_code == 400
    assert "start_date" in r.json()["detail"].lower() or "позже" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_no_audit_rows_returns_404(admin_audit_client, monkeypatch):
    async def _empty(_s, _a, _b, _c, _d):
        return [], AuditExportStats()

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _empty,
    )

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "csv",
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
        },
    )
    assert r.status_code == 404
    assert "не найдено" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_export_csv_ok(admin_audit_client, monkeypatch):
    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "csv",
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "user_id": "alice",
            "event_type": "GET /api/health",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/csv")
    disp = r.headers.get("content-disposition", "")
    assert "attachment" in disp.lower() and ".csv" in disp
    assert r.content.startswith(b"\xef\xbb\xbf") or b"alice" in r.content


@pytest.mark.asyncio
async def test_export_excel_ok(admin_audit_client, monkeypatch):
    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "excel",
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
        },
    )
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers.get("content-type", "")
    assert r.content.startswith(b"PK")
    assert ".xlsx" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_pdf_ok(admin_audit_client, monkeypatch):
    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    def _fake_pdf(_settings, *_args, **_kw):
        return b"%PDF-1.4 test"

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )
    monkeypatch.setattr(
        "app.api.admin_audit_export.build_pdf_bytes",
        _fake_pdf,
    )

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "pdf",
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
        },
    )
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert ".pdf" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_load_error_dlq_and_500(admin_audit_client, monkeypatch):
    async def _boom(*_a, **_kw):
        raise OSError("disk melted")

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _boom,
    )
    mock_dlq = AsyncMock()
    monkeypatch.setattr("app.api.admin_audit_export.dlq.send_to_dlq", mock_dlq)

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "csv",
            "start_date": "2025-02-01",
            "end_date": "2025-02-02",
        },
    )
    assert r.status_code == 500
    assert "прочитать" in r.json()["detail"].lower()
    mock_dlq.assert_awaited_once()
    call_kw = mock_dlq.await_args
    assert call_kw.kwargs["queue_name"] == "audit"
    assert call_kw.kwargs["payload"]["operation"] == "load_filtered_audit_entries"


@pytest.mark.asyncio
async def test_export_http_exception_from_builder_reraised(admin_audit_client, monkeypatch):
    """``except HTTPException: raise`` — не уходит в DLQ / обёртку 500."""
    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    def _teapot(*_a, **_kw):
        raise HTTPException(status_code=418, detail="teapot")

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )
    monkeypatch.setattr(
        "app.api.admin_audit_export.build_excel_bytes",
        _teapot,
    )
    mock_dlq = AsyncMock()
    monkeypatch.setattr("app.api.admin_audit_export.dlq.send_to_dlq", mock_dlq)

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "excel",
            "start_date": "2025-06-01",
            "end_date": "2025-06-02",
        },
    )
    assert r.status_code == 418
    mock_dlq.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_generate_error_dlq_and_500(admin_audit_client, monkeypatch):
    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    def _bad_excel(*_a, **_kw):
        raise RuntimeError("openpyxl exploded")

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )
    monkeypatch.setattr(
        "app.api.admin_audit_export.build_excel_bytes",
        _bad_excel,
    )
    mock_dlq = AsyncMock()
    monkeypatch.setattr("app.api.admin_audit_export.dlq.send_to_dlq", mock_dlq)

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "excel",
            "start_date": "2025-03-01",
            "end_date": "2025-03-02",
        },
    )
    assert r.status_code == 500
    assert "генерации" in r.json()["detail"].lower()
    mock_dlq.assert_awaited_once()
    assert mock_dlq.await_args.kwargs["payload"]["operation"] == "generate_export"
    assert mock_dlq.await_args.kwargs["payload"]["format"] == "excel"


# --- DLQ replay handler (_audit_dlq_handler) ---


@pytest.mark.asyncio
async def test_audit_dlq_handler_missing_fields_returns_false():
    from app.api.admin_audit_export import _audit_dlq_handler

    assert await _audit_dlq_handler({}) is False
    assert await _audit_dlq_handler({"operation": "x"}) is False


@pytest.mark.asyncio
async def test_audit_dlq_handler_empty_rows_returns_false(monkeypatch):
    from app.api.admin_audit_export import _audit_dlq_handler

    async def _empty(*_a, **_kw):
        return [], AuditExportStats()

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _empty,
    )

    payload = {
        "operation": "load_filtered_audit_entries",
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
    }
    assert await _audit_dlq_handler(payload) is False


@pytest.mark.asyncio
async def test_audit_dlq_handler_load_operation_success(monkeypatch):
    from app.api.admin_audit_export import _audit_dlq_handler

    rows = _sample_rows()

    async def _load(*_a, **_kw):
        return rows, _stats_for(rows)

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )

    payload = {
        "operation": "load_filtered_audit_entries",
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
    }
    assert await _audit_dlq_handler(payload) is True


@pytest.mark.asyncio
async def test_audit_dlq_handler_csv_excel_pdf(monkeypatch):
    from app.api.admin_audit_export import AuditExportFormat, _audit_dlq_handler

    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )
    monkeypatch.setattr(
        "app.api.admin_audit_export.build_pdf_bytes",
        lambda *_a, **_kw: b"%PDF",
    )

    base = {
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "operation": "generate_export",
    }
    assert (
        await _audit_dlq_handler({**base, "format": AuditExportFormat.csv.value})
        is True
    )
    assert (
        await _audit_dlq_handler({**base, "format": AuditExportFormat.excel.value})
        is True
    )
    assert (
        await _audit_dlq_handler({**base, "format": AuditExportFormat.pdf.value})
        is True
    )


@pytest.mark.asyncio
async def test_audit_dlq_handler_unknown_format_returns_false(monkeypatch):
    from app.api.admin_audit_export import _audit_dlq_handler

    rows = _sample_rows()

    async def _load(*_a, **_kw):
        return rows, _stats_for(rows)

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )

    payload = {
        "operation": "generate_export",
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "format": "xml",
    }
    assert await _audit_dlq_handler(payload) is False


@pytest.mark.asyncio
async def test_period_filename_from_content_disposition(admin_audit_client, monkeypatch):
    """Префикс имени файла из ``audit_export_download_prefix``."""
    from app.core.config import settings

    rows = _sample_rows()
    stats = _stats_for(rows)

    async def _load(*_a, **_kw):
        return rows, stats

    monkeypatch.setattr(
        "app.api.admin_audit_export.load_filtered_audit_entries",
        _load,
    )
    monkeypatch.setattr(settings, "audit_export_download_prefix", "custom_pref")

    start = date(2025, 4, 1)
    end = date(2025, 4, 15)
    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "csv",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    assert r.status_code == 200
    disp = r.headers.get("content-disposition", "")
    assert "custom_pref_2025-04-01_2025-04-15.csv" in disp


@pytest.mark.asyncio
async def test_export_integration_reads_tmp_audit_dir(tmp_path, admin_audit_client, monkeypatch):
    """Без мока ``load_filtered_audit_entries``: реальное чтение лога."""
    from app.core.config import settings

    day = date(2025, 5, 10)
    log = tmp_path / f"audit_{day:%Y-%m-%d}.log"
    log.write_text(
        json.dumps(
            {
                "timestamp": "x",
                "user": "u1",
                "action": "POST /api/x",
                "ip": "1.1.1.1",
                "success": True,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "audit_logs_dir", tmp_path)

    r = await admin_audit_client.get(
        "/api/admin/audit/export",
        params={
            "format": "csv",
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
        },
    )
    assert r.status_code == 200
    assert b"POST /api/x" in r.content or b"u1" in r.content
