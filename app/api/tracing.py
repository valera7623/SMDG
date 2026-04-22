"""
Tracing API — тонкая admin-only обёртка над Jaeger Query API.

Позволяет операторам искать трассы и запрашивать отдельную трассу по
``trace_id`` без прямого доступа к Jaeger UI. Полезно в headless-средах
(скриптах, алертах, CI), а также когда Jaeger UI закрыт за VPN.

Безопасность
------------
* Все эндпоинты требуют роли ``admin`` / ``super_admin``.
* Адрес Jaeger берётся из переменной окружения ``JAEGER_QUERY_URL``
  (по умолчанию ``http://jaeger:16686``) — это **внутренний** адрес,
  наружу не публикуется.
* Входные параметры провалидированы через Pydantic, чтобы избежать
  server-side URL-инъекций в query string.

Если Jaeger недоступен, эндпоинты возвращают ``503`` — приложение
продолжает работать (в соответствии с требованием fail-open).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracing", tags=["Tracing"])


# ──────────────────────────────────────────────────────────────────────
# Конфигурация / helpers
# ──────────────────────────────────────────────────────────────────────


def _jaeger_base_url() -> str:
    """Возвращает базовый URL Jaeger Query API без завершающего слэша."""
    url = os.getenv("JAEGER_QUERY_URL", "http://jaeger:16686")
    return url.rstrip("/")


# Таймаут для всех обращений к Jaeger — короткий, чтобы фронтенд не ждал
# бесконечно при недоступном Jaeger.
_JAEGER_TIMEOUT: float = 5.0

# Максимальный лимит результатов на один запрос /search. Больше 1000 Jaeger
# всё равно вернёт 400, а нам не нужен DoS за счёт heavy-запросов от админов.
_MAX_SEARCH_LIMIT: int = 200


async def _jaeger_get(path: str, params: Optional[dict] = None) -> dict:
    """Выполнить GET к Jaeger Query API с единой обработкой ошибок."""
    url = f"{_jaeger_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_JAEGER_TIMEOUT) as client:
            response = await client.get(url, params=params)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        logger.warning("Jaeger недоступен: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jaeger query API is unavailable",
        )
    except httpx.TimeoutException as exc:
        logger.warning("Jaeger query timeout: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Jaeger query timeout",
        )
    except httpx.HTTPError as exc:  # pragma: no cover - network edge cases
        logger.warning("Jaeger HTTP error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Jaeger query failed: {exc}",
        )

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Trace not found")
    if response.status_code >= 400:
        logger.warning(
            "Jaeger вернул %d для %s: %s", response.status_code, url, response.text[:200]
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Jaeger returned {response.status_code}",
        )

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Jaeger returned invalid JSON: {exc}",
        )


# ──────────────────────────────────────────────────────────────────────
# Эндпоинты
# ──────────────────────────────────────────────────────────────────────


@router.get("/trace/{trace_id}")
async def get_trace(
    trace_id: str,
    _admin: TokenData = Depends(get_current_admin),
) -> dict[str, Any]:
    """Вернуть структуру трассы Jaeger по её ``trace_id``.

    Возвращаемый формат — "как есть" из Jaeger Query API
    (ключи ``data``/``errors``/``limit``/``offset``/``total``).
    """
    if not trace_id or len(trace_id) > 64 or not trace_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid trace_id format")

    return await _jaeger_get(f"/api/traces/{trace_id}")


@router.get("/search")
async def search_traces(
    service: str = Query("smdg", min_length=1, max_length=128),
    operation: Optional[str] = Query(None, max_length=256),
    start_time: Optional[int] = Query(
        None,
        description="Начало диапазона в микросекундах Unix-эпохи",
    ),
    end_time: Optional[int] = Query(
        None,
        description="Конец диапазона в микросекундах Unix-эпохи",
    ),
    limit: int = Query(20, ge=1, le=_MAX_SEARCH_LIMIT),
    tags: Optional[str] = Query(
        None,
        description='Теги в формате JSON, например {"error":"true"}',
    ),
    _admin: TokenData = Depends(get_current_admin),
) -> dict[str, Any]:
    """Поиск трасс в Jaeger по сервису, операции и временному окну.

    Прокидывает параметры в Jaeger Query API и возвращает сырой ответ —
    UI/скрипты могут сами разбирать поле ``data``.
    """
    params: dict[str, Any] = {"service": service, "limit": limit}
    if operation:
        params["operation"] = operation
    if start_time is not None:
        params["start"] = start_time
    if end_time is not None:
        params["end"] = end_time
    if tags:
        params["tags"] = tags

    return await _jaeger_get("/api/traces", params=params)


@router.get("/services")
async def list_services(
    _admin: TokenData = Depends(get_current_admin),
) -> dict[str, Any]:
    """Список сервисов, о которых Jaeger уже получил хотя бы один spans."""
    return await _jaeger_get("/api/services")


@router.get("/services/{service}/operations")
async def list_operations(
    service: str,
    _admin: TokenData = Depends(get_current_admin),
) -> dict[str, Any]:
    """Список операций (spans) для конкретного сервиса."""
    if not service or len(service) > 128:
        raise HTTPException(status_code=400, detail="Invalid service name")
    return await _jaeger_get(f"/api/services/{service}/operations")


__all__ = ["router"]
