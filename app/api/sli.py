# app/api/sli.py
"""Публичные и админ-эндпоинты SLI/SLA (status JSON, агрегированный отчёт)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.sla_tracker import sla_tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sli", tags=["SLA/SLI"])


async def sli_root() -> Dict[str, Any]:
    """Карта эндпоинтов. Регистрируется в ``main`` на ``GET /api/sli`` (и при 404 смотрите, что смонтированы актуальные роуты)."""
    return {
        "service": "SMDG",
        "endpoints": {
            "GET /api/sli": "this",
            "GET /api/sli/status": "публичный JSON для status page",
            "GET /api/sli/report": "детальный отчёт (admin)",
            "GET /api/sli/history": "история инцидентов (admin)",
        },
    }


@router.get("/status", summary="Текущий SLI-статус (публично)")
async def get_sli_status() -> Dict[str, Any]:
    """
    Сводка для status page. Не содержит PII.
    """
    av = sla_tracker.get_api_availability()
    return {
        "current_status": sla_tracker.get_current_status(),
        "uptime_30d": sla_tracker.get_uptime_30d(),
        "api_availability": av,
        "error_budget_remaining": sla_tracker.get_error_budget(),
        "latency_p95": sla_tracker.get_latency_p95(),
        "active_incidents": sla_tracker.get_active_incidents(),
        "incident_history": sla_tracker.get_incident_history(),
        "insufficient_data": av is None,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/report", summary="SLA-отчёт (admin)")
async def get_sla_report(
    _admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    return sla_tracker.generate_report()


@router.get("/history", summary="История инцидентов (admin, опциональный файл)")
async def get_incident_history_sli(
    days: int = 30,
    _admin: TokenData = Depends(get_current_admin),
) -> List[Dict[str, Any]]:
    return sla_tracker.get_incident_history(days=days)
