"""
Demo info endpoint — publicly accessible, no authentication required.

GET /api/demo/info
  Returns demo credentials, feature list, and time until next auto-reset.

Only mounted when settings.demo_mode is True (see app/bootstrap/api_routes.py).
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.feature_flags import get_deployment_info

router = APIRouter(tags=["Demo"])

# Keep a module-level reference so lifespan can update it without a circular import.
# demo_seeder.py manages _LAST_SEED_TIME; we read it lazily.


@router.get("/api/demo/info", summary="Demo credentials and status")
async def demo_info() -> JSONResponse:
    """Return demo login credentials, feature list, and next reset time.

    This endpoint is public (no authentication) so visitors can discover
    credentials directly from the API or from the login page banner.
    """
    from app.core.demo_seeder import get_last_seed_time  # lazy to avoid circular import

    last_seed = get_last_seed_time()
    reset_interval_seconds = settings.demo_reset_interval_hours * 3600

    if last_seed > 0:
        elapsed = time.time() - last_seed
        remaining_seconds = max(0.0, reset_interval_seconds - elapsed)
        next_reset_in_hours = round(remaining_seconds / 3600, 1)
    else:
        next_reset_in_hours = settings.demo_reset_interval_hours

    deployment = get_deployment_info()

    return JSONResponse(
        content={
            "demo": True,
            "credentials": [
                {
                    "role": "Admin",
                    "username": "admin_demo",
                    "password": "Demo1234!",
                    "description": "Full admin access — manage users, audit export, system config",
                },
                {
                    "role": "Doctor",
                    "username": "doctor_demo",
                    "password": "Demo1234!",
                    "description": "Upload / download encrypted medical files, DICOM viewer",
                },
                {
                    "role": "Patient",
                    "username": "user_demo",
                    "password": "Demo1234!",
                    "description": "View shared files and DICOM scans via time-limited links",
                },
            ],
            "reset": {
                "interval_hours": settings.demo_reset_interval_hours,
                "next_reset_in_hours": next_reset_in_hours,
                "note": "All user-generated data is wiped and re-seeded automatically.",
            },
            "features": deployment.get("features_enabled", []),
            "deployment_type": deployment.get("deployment_type", "demo"),
            "note": (
                "This is a live demo of SMDG — Secure Medical Data Gateway. "
                "End-to-end encryption (age), RBAC, DICOM viewer, and audit export "
                "are fully functional. Upload limited to 10 MB per file. "
                "Data resets every 24 hours."
            ),
            "links": {
                "swagger_ui": "/docs",
                "health": "/health/live",
                "features": "/health/features",
            },
        }
    )
