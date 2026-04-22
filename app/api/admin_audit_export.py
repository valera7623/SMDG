# app/api/admin_audit_export.py
from __future__ import annotations

import logging
from datetime import date
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.core.audit_export import (
    build_excel_bytes,
    build_pdf_bytes,
    iter_csv_chunks,
    load_filtered_audit_entries,
)
from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.config import settings
from app.core.timeout import timeout
from app.core.bulkhead import bulkhead
from app.services.dead_letter_service import dlq

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/audit", tags=["Admin Audit"])


class AuditExportFormat(str, Enum):
    excel = "excel"
    pdf = "pdf"
    csv = "csv"


async def _audit_dlq_handler(payload: dict) -> bool:
    """Replay handler for audit export failures."""
    operation = payload.get("operation")
    start_raw = payload.get("start_date")
    end_raw = payload.get("end_date")
    if not operation or not start_raw or not end_raw:
        return False

    start_date = date.fromisoformat(start_raw)
    end_date = date.fromisoformat(end_raw)
    user_id = payload.get("user_id")
    event_type = payload.get("event_type")
    rows, stats = await load_filtered_audit_entries(settings, start_date, end_date, user_id, event_type)
    if not rows:
        return False

    if operation == "load_filtered_audit_entries":
        return True

    export_format = payload.get("format")
    if export_format == AuditExportFormat.csv.value:
        # Проверяем генерацию CSV чанков.
        next(iter(iter_csv_chunks(rows)))
        return True
    if export_format == AuditExportFormat.excel.value:
        build_excel_bytes(rows, stats, start_date, end_date, user_id, event_type)
        return True
    if export_format == AuditExportFormat.pdf.value:
        build_pdf_bytes(settings, rows, stats, start_date, end_date, user_id, event_type)
        return True
    return False


def _period_filename(start: date, end: date, ext: str) -> str:
    prefix = getattr(settings, "audit_export_download_prefix", "smdg_audit")
    return f"{prefix}_{start:%Y-%m-%d}_{end:%Y-%m-%d}.{ext}"


def _validate_dates_or_400(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date не может быть позже end_date",
        )


@router.get("/export")
@timeout(120.0, "Audit export timed out", service="api", operation="export_audit_logs")
@bulkhead(
    "audit_export",
    max_concurrent=settings.AUDIT_EXPORT_BULKHEAD_MAX_CONCURRENT,
    queue_size=settings.AUDIT_EXPORT_BULKHEAD_QUEUE_SIZE,
    timeout_seconds=settings.AUDIT_EXPORT_BULKHEAD_TIMEOUT,
)
async def export_audit_logs(
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    export_format: AuditExportFormat = Query(..., alias="format", description="Формат: excel, pdf, csv"),
    start_date: date = Query(..., description="Начало периода (включительно)"),
    end_date: date = Query(..., description="Конец периода (включительно)"),
    user_id: str | None = Query(
        None,
        description=(
            "Фильтр по строковому полю **user** в JSON-записи журнала (имя пользователя из аудита; "
            "это не числовой id из БД). Совпадение только полное, строка к строке."
        ),
    ),
    event_type: str | None = Query(
        None,
        description=(
            "Фильтр по полю **action** в JSON (HTTP-метод и путь, как записаны в аудите): "
            "полное совпадение строки, например `GET /health`. Подстрочный поиск не выполняется."
        ),
        openapi_examples={
            "health_probe": {"summary": "Пример", "value": "GET /health"},
        },
    ),
) -> StreamingResponse:
    """
    Экспорт записей аудита из JSON-файлов `audit_YYYY-MM-DD.log` за период.
    Доступ только администратору.

    **Фильтры:** параметр ``user_id`` сопоставляется с полем ``user``, ``event_type`` — с полем ``action``
    (оба — точное совпадение строк из журнала).

    **PDF:** для кириллицы нужен шрифт DejaVuSans. В образе без системных шрифтов задайте переменную окружения
    ``AUDIT_EXPORT_PDF_FONT_PATH`` — абсолютный путь к файлу ``DejaVuSans.ttf``.
    """
    _ = current_admin
    _validate_dates_or_400(start_date, end_date)

    try:
        rows, stats = await load_filtered_audit_entries(
            settings, start_date, end_date, user_id, event_type
        )
    except Exception as exc:
        await dlq.send_to_dlq(
            queue_name="audit",
            payload={
                "operation": "load_filtered_audit_entries",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "user_id": user_id,
                "event_type": event_type,
            },
            error=exc,
            max_retries=2,
            metadata={"source": "admin_audit_export"},
        )
        logger.exception("Ошибка чтения журналов аудита")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось прочитать журналы аудита",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="За указанный период и фильтры записей аудита не найдено",
        )

    try:
        if export_format == AuditExportFormat.csv:
            filename = _period_filename(start_date, end_date, "csv")
            return StreamingResponse(
                iter_csv_chunks(rows),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )

        if export_format == AuditExportFormat.excel:
            payload = build_excel_bytes(
                rows, stats, start_date, end_date, user_id, event_type
            )
            filename = _period_filename(start_date, end_date, "xlsx")
            return StreamingResponse(
                iter([payload]),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )

        payload = build_pdf_bytes(
            settings, rows, stats, start_date, end_date, user_id, event_type
        )
        filename = _period_filename(start_date, end_date, "pdf")
        return StreamingResponse(
            iter([payload]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        await dlq.send_to_dlq(
            queue_name="audit",
            payload={
                "operation": "generate_export",
                "format": export_format.value,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "user_id": user_id,
                "event_type": event_type,
            },
            error=exc,
            max_retries=2,
            metadata={"source": "admin_audit_export"},
        )
        logger.exception("Ошибка генерации отчёта аудита (%s)", export_format.value)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка генерации отчёта",
        )


dlq.register_handler("audit", _audit_dlq_handler)
