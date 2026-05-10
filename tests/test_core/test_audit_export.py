"""Тесты ``app/core/audit_export.py``."""

from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import audit_export as ae
from app.core.audit_export import (
    AUDIT_ROW_HEADERS,
    AuditExportStats,
    audit_row,
    build_excel_bytes,
    build_pdf_bytes,
    format_extra_column,
    format_status,
    iter_audit_log_entries,
    iter_csv_chunks,
    load_filtered_audit_entries,
    resolve_pdf_font_path,
    shorten_cell,
)


def test_audit_export_stats_add_entry():
    s = AuditExportStats()
    s.add_entry({"success": True})
    s.add_entry({"success": False})
    s.add_entry({"success": None})
    assert s.total == 3
    assert s.success == 1
    assert s.failed == 2


def test_format_status():
    assert format_status(True) == "Успех"
    assert format_status(False) == "Неудача"
    assert format_status(None) == "None"
    assert format_status("x") == "x"


def test_format_extra_column_metadata_and_helpers():
    assert '"k"' in format_extra_column({"metadata": {"k": 1}, "filename": "f.txt", "reason": "r"})


def test_format_extra_column_json_fallback():
    class Bad:
        pass

    out = format_extra_column({"metadata": {"x": Bad()}})
    assert isinstance(out, str)
    assert "Bad" in out or "x" in out


def test_shorten_cell():
    assert shorten_cell("a\nb", 100) == "a b"
    long = "x" * 3000
    out = shorten_cell(long, max_len=10)
    assert len(out) == 10
    assert out.endswith("…")


def test_audit_row_order():
    row = audit_row(
        {
            "timestamp": "t",
            "user": "u",
            "action": "a",
            "ip": "1.1.1.1",
            "success": True,
            "metadata": {"z": 1},
        }
    )
    assert len(row) == len(AUDIT_ROW_HEADERS)


@pytest.mark.asyncio
async def test_iter_audit_log_entries_not_a_directory(tmp_path):
    not_dir = tmp_path / "file.txt"
    not_dir.write_text("x", encoding="utf-8")
    out = []
    async for e in iter_audit_log_entries(not_dir, date(2024, 1, 1), date(2024, 1, 1), None, None):
        out.append(e)
    assert out == []


@pytest.mark.asyncio
async def test_iter_audit_log_entries_reads_and_filters(tmp_path):
    d = date(2024, 6, 15)
    log_path = tmp_path / f"audit_{d:%Y-%m-%d}.log"
    lines = [
        json.dumps(
            {
                "timestamp": "1",
                "user": "10",
                "action": "login",
                "ip": "0",
                "success": True,
            },
            ensure_ascii=False,
        ),
        "not-json {{{",
        json.dumps(
            {
                "timestamp": "2",
                "user": "20",
                "action": "logout",
                "ip": "0",
                "success": False,
            },
            ensure_ascii=False,
        ),
    ]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    all_rows = []
    async for e in iter_audit_log_entries(tmp_path, d, d, None, None):
        all_rows.append(e)
    assert len(all_rows) == 2

    u10 = []
    async for e in iter_audit_log_entries(tmp_path, d, d, "10", None):
        u10.append(e)
    assert len(u10) == 1 and u10[0]["action"] == "login"

    logout_only = []
    async for e in iter_audit_log_entries(tmp_path, d, d, None, "logout"):
        logout_only.append(e)
    assert len(logout_only) == 1


@pytest.mark.asyncio
async def test_iter_audit_log_entries_oserror_logged(tmp_path, caplog):
    d = date(2024, 6, 15)
    log_path = tmp_path / f"audit_{d:%Y-%m-%d}.log"
    log_path.write_text("{}", encoding="utf-8")

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=OSError("boom"))
    cm.__aexit__ = AsyncMock(return_value=None)

    def fake_open(*_a, **_kw):
        return cm

    caplog.set_level("ERROR")
    with patch("app.core.audit_export.aiofiles.open", fake_open):
        got = []
        async for e in iter_audit_log_entries(tmp_path, d, d, None, None):
            got.append(e)
    assert got == []
    assert "Ошибка чтения" in caplog.text or "boom" in caplog.text


@pytest.mark.asyncio
async def test_iter_audit_skips_missing_log_for_day(tmp_path):
    """Строка ``continue``: файл за дату отсутствует."""
    d0 = date(2024, 1, 10)
    d1 = date(2024, 1, 11)
    only = tmp_path / f"audit_{d0:%Y-%m-%d}.log"
    only.write_text(
        json.dumps({"user": "1", "action": "a", "success": True}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    out = []
    async for e in iter_audit_log_entries(tmp_path, d0, d1, None, None):
        out.append(e)
    assert len(out) == 1


@pytest.mark.asyncio
async def test_iter_audit_skips_blank_lines(tmp_path):
    """Пустые строки в логе пропускаются."""
    d = date(2024, 2, 2)
    p = tmp_path / f"audit_{d:%Y-%m-%d}.log"
    p.write_text(
        "\n\n"
        + json.dumps({"user": "x", "action": "y", "success": True}, ensure_ascii=False)
        + "\n\n",
        encoding="utf-8",
    )
    out = []
    async for e in iter_audit_log_entries(tmp_path, d, d, None, None):
        out.append(e)
    assert len(out) == 1


@pytest.mark.asyncio
async def test_load_filtered_audit_entries(tmp_path):
    d = date(2025, 3, 1)
    (tmp_path / f"audit_{d:%Y-%m-%d}.log").write_text(
        json.dumps({"user": "1", "action": "x", "success": True}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    settings = SimpleNamespace(audit_logs_dir=tmp_path)
    rows, stats = await load_filtered_audit_entries(settings, d, d, None, None)
    assert len(rows) == 1
    assert stats.total == 1 and stats.success == 1


def test_build_excel_bytes():
    rows = [
        {"timestamp": "t", "user": "u", "action": "a", "ip": "i", "success": True, "metadata": {}}
    ]
    stats = AuditExportStats()
    stats.add_entry(rows[0])
    buf = build_excel_bytes(
        rows,
        stats,
        date(2024, 1, 1),
        date(2024, 1, 2),
        user_id=None,
        event_type=None,
    )
    assert buf.startswith(b"PK")
    assert len(buf) > 100


def _first_existing_dejavu() -> Path | None:
    for p in ae.DEJAVU_FONT_CANDIDATES:
        if p.is_file():
            return p
    return None


def test_resolve_pdf_font_path_custom_ok(tmp_path):
    font = tmp_path / "x.ttf"
    font.write_bytes(b"dummy")
    # Path.exists as file — TTFont may fail at runtime; resolve_pdf_font_path only checks is_file
    settings = SimpleNamespace(audit_export_pdf_font_path=str(font))
    assert resolve_pdf_font_path(settings) == font


def test_resolve_pdf_font_path_custom_missing_warns(tmp_path, caplog):
    missing = tmp_path / "nope.ttf"
    real = _first_existing_dejavu()
    if real is None:
        pytest.skip("Нет системного DejaVu — нужен для ветки fallback")
    settings = SimpleNamespace(audit_export_pdf_font_path=str(missing))
    caplog.set_level("WARNING")
    p = resolve_pdf_font_path(settings)
    assert p == real
    assert "не найден" in caplog.text or str(missing) in caplog.text


def test_resolve_pdf_font_path_candidates_only(tmp_path):
    fake = tmp_path / "DejaVuSans.ttf"
    fake.write_bytes(b"x")
    with patch.object(ae, "DEJAVU_FONT_CANDIDATES", (fake,)):
        settings = SimpleNamespace(audit_export_pdf_font_path=None)
        assert resolve_pdf_font_path(settings) == fake


def test_resolve_pdf_font_path_not_found():
    with patch.object(ae, "DEJAVU_FONT_CANDIDATES", ()):
        settings = SimpleNamespace(audit_export_pdf_font_path=None)
        with pytest.raises(FileNotFoundError, match="DejaVuSans"):
            resolve_pdf_font_path(settings)


def test_build_pdf_bytes_end_to_end():
    font = _first_existing_dejavu()
    if font is None:
        pytest.skip("Нет шрифта DejaVu в системе")
    settings = SimpleNamespace(audit_export_pdf_font_path=None)
    rows = [
        {
            "timestamp": "2025-01-01",
            "user": "u",
            "action": "act",
            "ip": "10.0.0.1",
            "success": True,
            "metadata": {"k": "v"},
        }
    ]
    stats = AuditExportStats()
    for r in rows:
        stats.add_entry(r)
    pdf = build_pdf_bytes(
        settings,
        rows,
        stats,
        date(2025, 1, 1),
        date(2025, 1, 31),
        "u",
        "act",
    )
    assert pdf.startswith(b"%PDF")


def test_build_pdf_bytes_font_already_registered():
    font = _first_existing_dejavu()
    if font is None:
        pytest.skip("Нет шрифта DejaVu в системе")
    settings = SimpleNamespace(audit_export_pdf_font_path=str(font))
    rows: list[dict] = []
    stats = AuditExportStats()
    build_pdf_bytes(
        settings,
        rows,
        stats,
        date(2024, 1, 1),
        date(2024, 1, 1),
        None,
        None,
    )
    # повторный вызов — ветка «DejaVuSans уже зарегистрирован»
    build_pdf_bytes(
        settings,
        rows,
        stats,
        date(2024, 1, 1),
        date(2024, 1, 1),
        None,
        None,
    )


def test_iter_csv_chunks_encoding():
    rows = [
        {"timestamp": "t", "user": "u", "action": "a", "ip": "", "success": False},
    ]
    chunks = list(iter_csv_chunks(rows))
    assert len(chunks) >= 2
    assert chunks[0].startswith(b"\xef\xbb\xbf")
    joined = b"".join(chunks).decode("utf-8-sig", errors="replace")
    assert "Дата" in joined


def test_build_excel_empty_rows():
    buf = build_excel_bytes(
        [],
        AuditExportStats(),
        date(2022, 1, 1),
        date(2022, 1, 1),
        "uid",
        "etype",
    )
    assert buf.startswith(b"PK")


def test_build_excel_column_width_skips_none_cells():
    """Ветка ``cell.value is None`` при расчёте ширины колонок."""
    fake_row = ["t", "u", "a", "ip", "ok", None]
    with patch("app.core.audit_export.audit_row", return_value=fake_row):
        buf = build_excel_bytes(
            [{"ignored": True}],
            AuditExportStats(),
            date(2023, 5, 1),
            date(2023, 5, 1),
            None,
            None,
        )
    assert buf.startswith(b"PK")
