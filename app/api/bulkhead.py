from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_admin
from app.core.bulkhead import _bulkheads, get_bulkhead, initialize_bulkheads

router = APIRouter(prefix="/api/bulkhead", tags=["Bulkhead"])


@router.get("/status")
async def get_bulkheads_status(current_admin=Depends(get_current_admin)):
    _ = current_admin
    return {name: bulkhead.get_state() for name, bulkhead in _bulkheads.items()}


@router.post("/reset/{name}")
async def reset_bulkhead(name: str, current_admin=Depends(get_current_admin)):
    _ = current_admin
    # Lazy-create known bulkheads so reset works before first traffic.
    if name not in _bulkheads:
        try:
            get_bulkhead(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Bulkhead '{name}' not found") from exc

    if name not in _bulkheads:
        raise HTTPException(status_code=404, detail=f"Bulkhead '{name}' not found")

    await _bulkheads[name].open()
    return {"status": "reset", "bulkhead": name}


@router.post("/warmup")
async def warmup_bulkheads(current_admin=Depends(get_current_admin)):
    _ = current_admin
    initialize_bulkheads()
    return {
        "status": "ok",
        "initialized": sorted(_bulkheads.keys()),
        "bulkheads": {name: bulkhead.get_state() for name, bulkhead in sorted(_bulkheads.items())},
    }


@router.get("/metrics")
async def get_bulkheads_metrics(current_admin=Depends(get_current_admin)):
    _ = current_admin
    initialize_bulkheads()

    metrics: dict[str, dict[str, float | int]] = {}
    for name, bulkhead in sorted(_bulkheads.items()):
        state = bulkhead.get_state()
        state_metrics = state.get("metrics", {})
        metrics[name] = {
            "utilization": state.get("utilization", 0),
            "active": state_metrics.get("active_requests", 0),
            "queued": state_metrics.get("queued_requests", 0),
            "rejected": state_metrics.get("total_rejected", 0),
            "timeout": state_metrics.get("total_timeout", 0),
        }

    return {"bulkheads": metrics}
