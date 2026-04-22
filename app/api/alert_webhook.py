"""FastAPI endpoint для приёма алертов от Alertmanager.

Alertmanager при срабатывании правила делает HTTP POST с JSON-пэйлоадом
в формате v2 (см. https://prometheus.io/docs/alerting/latest/configuration/#webhook_config).
Мы:

1. Пишем событие в audit log (чтобы все алерты остались в регуляторном
   аудит-треке).
2. Пересылаем в Telegram (см. ``app.services.telegram_alerter``).

Защита:
    * Endpoint доступен **только из backend-сети** (в compose
      alertmanager → smdg через network alias, наружу не открывается
      nginx'ом).
    * Опционально: shared secret ``SMDG_ALERT_WEBHOOK_SECRET`` в
      заголовке ``X-Alert-Secret``. Если переменная установлена, но
      заголовок не совпадает — 401. Если переменная не задана —
      проверка отключена (dev-friendly).
    * В audit log пишем только alertname/severity/instance, т.е. НЕ
      попадает PII (имена пациентов, пути к файлам и т.п.).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core import audit_logger
from app.services.telegram_alerter import get_telegram_alerter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


def _check_shared_secret(header_value: str | None) -> None:
    """Если задан SMDG_ALERT_WEBHOOK_SECRET — сравнить с заголовком."""
    expected = os.getenv("SMDG_ALERT_WEBHOOK_SECRET", "").strip()
    if not expected:
        return  # защита отключена
    if not header_value or header_value.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid alert webhook secret",
        )


def _audit_alerts(alerts: List[Dict[str, Any]]) -> None:
    """Записать пачку алертов в audit log (без PII)."""
    for alert in alerts:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        try:
            audit_logger.log_operation(
                action="ALERT_RECEIVED",
                filename="",
                user="alertmanager",
                ip="internal",
                reason=str(annotations.get("summary", ""))[:200],
                success=str(alert.get("status", "")).lower() != "firing",
                metadata={
                    "alertname": labels.get("alertname"),
                    "severity": labels.get("severity"),
                    "service": labels.get("service"),
                    "component": labels.get("component"),
                    "instance": labels.get("instance"),
                    "status": alert.get("status"),
                    "starts_at": alert.get("startsAt"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audit write for alert failed: %s", exc)


@router.post(
    "/webhook",
    summary="Alertmanager webhook receiver",
    status_code=status.HTTP_200_OK,
)
async def handle_alertmanager_webhook(
    request: Request,
    x_alert_secret: str | None = Header(default=None, alias="X-Alert-Secret"),
) -> Dict[str, Any]:
    """Принять webhook от Alertmanager и распределить его по каналам.

    Возвращает:
        ``{"status": "received", "count": N, "delivered": M}`` —
        N принятых алертов, M доставленных в Telegram. Даже при ошибках
        пересылки возвращаем 200, чтобы Alertmanager не ретраил в цикле.
    """
    _check_shared_secret(x_alert_secret)

    try:
        data = await request.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alert webhook: invalid JSON: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    alerts = data.get("alerts") or []
    if not isinstance(alerts, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected 'alerts' to be a list",
        )

    logger.info(
        "Alert webhook received: receiver=%s group=%s count=%d",
        data.get("receiver"),
        data.get("groupKey"),
        len(alerts),
    )

    # 1. В audit log (синхронно, это быстро и никогда не должно тормозить Alertmanager).
    _audit_alerts(alerts)

    # 2. В Telegram — асинхронно, но в пределах обработки запроса. Использовать
    #    fire-and-forget (BackgroundTasks) НЕ нужно, потому что:
    #      a) Telegram API сам по себе < 1 сек;
    #      b) у нас отдельный таймаут httpx, и ошибки мы проглатываем;
    #      c) синхронное поведение упрощает трактовку логов/тестов.
    alerter = get_telegram_alerter()
    delivered = 0
    if alerts:
        try:
            delivered = await alerter.send_batch_alerts(alerts)
        except Exception as exc:  # noqa: BLE001
            # Никогда не пробрасываем — Alertmanager иначе заретраит и засыпет нас.
            logger.warning("Telegram delivery failed: %s", exc)

    return {"status": "received", "count": len(alerts), "delivered": delivered}


@router.get(
    "/webhook/health",
    summary="Alert webhook health probe",
)
async def alert_webhook_health() -> Dict[str, Any]:
    """Диагностический эндпоинт: проверяет, сконфигурирован ли Telegram."""
    alerter = get_telegram_alerter()
    return {
        "ok": True,
        "telegram_enabled": alerter.enabled,
        "shared_secret_required": bool(os.getenv("SMDG_ALERT_WEBHOOK_SECRET")),
    }


__all__ = ["router"]
