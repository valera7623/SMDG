"""Админский API для наблюдения за Circuit Breaker'ами.

Доступно только роли ``admin`` / ``super_admin`` (см. ``get_current_admin``).

Эндпоинты:
    GET  /api/circuit-breaker/status              — список всех брейкеров
    GET  /api/circuit-breaker/status/{name}       — конкретный брейкер
    POST /api/circuit-breaker/reset/{name}        — ручной сброс в CLOSED
    POST /api/circuit-breaker/reset-all           — сбросить все брейкеры

Ручной сброс нужен в первую очередь в инцидентах: если зависимость
восстановлена раньше ``recovery_timeout``, админ может не ждать таймер.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.circuit_breaker import (
    CircuitState,
    get_all_circuit_breakers,
    get_circuit_breaker,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/circuit-breaker", tags=["Circuit Breaker"])


@router.get("/status")
async def get_circuit_breakers_status(
    current_admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Вернуть снимок состояния всех зарегистрированных брейкеров."""
    breakers = get_all_circuit_breakers()
    states: Dict[str, Any] = {name: cb.get_state() for name, cb in breakers.items()}

    # Итоговая сводка — полезна для быстрой оценки: «сколько деградаций прямо сейчас?».
    summary = {
        "total": len(breakers),
        "closed": sum(1 for cb in breakers.values() if cb.state is CircuitState.CLOSED),
        "open": sum(1 for cb in breakers.values() if cb.state is CircuitState.OPEN),
        "half_open": sum(
            1 for cb in breakers.values() if cb.state is CircuitState.HALF_OPEN
        ),
    }
    return {"summary": summary, "breakers": states}


@router.get("/status/{name}")
async def get_single_circuit_breaker_status(
    name: str,
    current_admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Снимок конкретного брейкера по имени.

    В отличие от ``/status``, не создаёт брейкер, если он не был ни разу
    использован — возвращает 404.
    """
    breakers = get_all_circuit_breakers()
    cb = breakers.get(name)
    if cb is None:
        raise HTTPException(
            status_code=404,
            detail=f"Circuit breaker '{name}' is not registered",
        )
    return cb.get_state()


@router.post("/reset/{name}")
async def reset_circuit_breaker(
    name: str,
    current_admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Принудительно сбросить брейкер в CLOSED (требует роль admin)."""
    breakers = get_all_circuit_breakers()
    cb = breakers.get(name)
    if cb is None:
        raise HTTPException(
            status_code=404,
            detail=f"Circuit breaker '{name}' is not registered",
        )

    prev_state = cb.state.value
    await cb.reset()
    logger.warning(
        "Circuit breaker '%s' was manually reset by admin '%s' (was %s)",
        name,
        current_admin.sub,
        prev_state,
    )
    return {
        "status": "reset",
        "name": name,
        "previous_state": prev_state,
        "current_state": cb.state.value,
    }


@router.post("/reset-all")
async def reset_all_circuit_breakers(
    current_admin: TokenData = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Сбросить ВСЕ брейкеры в CLOSED (аварийная операция)."""
    breakers = get_all_circuit_breakers()
    reset_list: List[str] = []
    for name, cb in breakers.items():
        if cb.state is not CircuitState.CLOSED:
            await cb.reset()
            reset_list.append(name)
    logger.warning(
        "All circuit breakers reset by admin '%s' (reset=%s)",
        current_admin.sub,
        reset_list,
    )
    return {"status": "reset-all", "reset": reset_list, "total": len(breakers)}


__all__ = ["router"]
