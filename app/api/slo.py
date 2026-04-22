"""HTTP API для SLO-отчётов и сырых метрик.

Два эндпоинта:

- ``GET /api/slo/report`` — человекочитаемый JSON-отчёт: compliance
  по каждому SLO, статусы, остаток error budget, общий вердикт.
  Доступен только администратору (consistent с остальным admin API).
- ``GET /api/slo/metrics`` — raw Prometheus-текст (дублирует
  ``/metrics``, но требует auth). Удобен для интеграций, где общий
  ``/metrics`` публично недоступен.

Оба эндпоинта read-only: SLO-метрики обновляет отдельный фоновый
коллектор (см. :mod:`app.core.slo_collector`), так что серверу
достаточно прочитать текущее состояние реестра.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.slo_collector import SLO_CONFIG
from app.core.slo_metrics import (
    error_budget_remaining,
    slo_compliance,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/slo", tags=["SLO"])


def _status_from_compliance(compliance: float, target: float) -> str:
    """Текстовый статус SLO для UI.

    - ``good`` — compliance >= 99%
    - ``warning`` — 95..99%
    - ``critical`` — < 95%
    - ``breach`` — compliance < target (SLO нарушен)

    Порог 95% выбран ниже любой целевой компоненты в ``SLO_CONFIG``:
    это уровень, когда уже чётко нужно вмешиваться.
    """
    if compliance < 95.0:
        return "critical"
    if compliance < target:
        return "breach"
    if compliance < 99.0:
        return "warning"
    return "good"


def _safe_labeled_gauge_value(gauge: Any, **labels: str) -> float:
    """Прочитать текущее значение Gauge с заданными labels, не бросая.

    Если labels никогда не устанавливались — возвращаем 0.0.
    ``_value.get()`` — приватный API prometheus_client; fallback к 0
    защищает на случай смены внутренней реализации.
    """
    try:
        return float(gauge.labels(**labels)._value.get())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0.0


@router.get("/report", summary="SLO compliance report (admin)")
async def get_slo_report(
    current_admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Агрегированный SLO-отчёт.

    Структура ответа::

        {
            "timestamp": "2025-01-01T12:00:00+00:00",
            "overall_status": "good" | "warning" | "critical",
            "slo_compliance": {
                "api_availability": {
                    "current": 99.95,
                    "target": 99.9,
                    "status": "good"
                },
                ...
            },
            "error_budget": {
                "api_availability": 1234.5,
                ...
            }
        }
    """
    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_status": "good",
        "slo_compliance": {},
        "error_budget": {},
    }

    worst_status = "good"
    status_order = {"good": 0, "warning": 1, "breach": 2, "critical": 3}

    for slo_name, config in SLO_CONFIG.items():
        target = float(config["target"])
        try:
            current = _safe_labeled_gauge_value(
                slo_compliance, slo_name=slo_name, target=f"{target}%"
            )
            status = _status_from_compliance(current, target)
            report["slo_compliance"][slo_name] = {
                "current": round(current, 3),
                "target": target,
                "status": status,
            }
            if status_order[status] > status_order[worst_status]:
                worst_status = status

            budget = _safe_labeled_gauge_value(
                error_budget_remaining, slo_name=slo_name
            )
            report["error_budget"][slo_name] = round(budget, 3)
        except Exception as exc:  # noqa: BLE001
            # Никогда не роняем отчёт целиком — показываем ошибку только
            # по проблемному SLO, чтобы остальные были видны.
            logger.warning("SLO report: failed to render %s: %s", slo_name, exc)
            report["slo_compliance"][slo_name] = {"error": str(exc)}

    # Маппим breach → critical для внешнего статуса.
    report["overall_status"] = {
        "good": "good",
        "warning": "warning",
        "breach": "critical",
        "critical": "critical",
    }[worst_status]

    return report


@router.get("/metrics", summary="Raw Prometheus SLO metrics (admin)")
async def get_slo_metrics(
    current_admin: TokenData = Depends(get_current_admin),
) -> Response:
    """Экспорт SLO-метрик в формате Prometheus text.

    Удобно для read-only scrape'а из приватной сети, когда общий
    ``/metrics`` доступен только с loopback.
    """
    body = generate_latest()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


__all__ = ["router"]
