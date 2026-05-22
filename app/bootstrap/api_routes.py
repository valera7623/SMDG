"""Подключение API-роутеров к приложению."""

from __future__ import annotations

from fastapi import FastAPI

from app.api import (
    archive,
    bulkhead,
    cleanup,
    delete,
    dicom,
    download,
    stats,
    test,
    upload,
    webhooks,
)
from app.api import (
    list as list_api,
)
from app.api.admin_audit_export import router as admin_audit_export_router
from app.api.admin_file_audit import router as admin_file_audit_router
from app.api.admin_users import router as admin_users_router
from app.api.alert_webhook import router as alert_webhook_router
from app.api.auth import router as auth_router
from app.api.circuit_breaker import router as circuit_breaker_router
from app.api.dead_letter import router as dead_letter_router
from app.api.delete_user import router as delete_user_router
from app.api.health import router as health_router
from app.api.sli import router as sli_router
from app.api.sli import sli_root
from app.api.slo import router as slo_router
from app.api.tracing import router as tracing_router
from app.core.config import settings


def register_api_routers(app: FastAPI) -> None:
    """Монтирует все REST API роутеры."""
    app.include_router(upload.router, prefix="/api")
    app.include_router(download.router, prefix="/api")
    app.include_router(list_api.router, prefix="/api")
    app.include_router(delete.router, prefix="/api")
    app.include_router(cleanup.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_users_router, prefix="/api")
    app.include_router(admin_audit_export_router, prefix="/api")
    app.include_router(admin_file_audit_router, prefix="/api")
    app.include_router(delete_user_router, prefix="/api")
    app.include_router(dicom.router, prefix="/api")
    if settings.dev_mode or settings.load_test_mode:
        app.include_router(test.router, prefix="/api")
    if settings.demo_mode:
        from app.api.demo import router as demo_router
        app.include_router(demo_router)
    app.include_router(tracing_router)
    app.include_router(health_router)
    app.include_router(alert_webhook_router)
    app.include_router(slo_router)
    app.include_router(sli_router)
    app.include_router(circuit_breaker_router)
    app.include_router(dead_letter_router)
    app.include_router(bulkhead.router)
    app.include_router(archive.router)

    app.add_api_route(
        "/api/sli",
        sli_root,
        methods=["GET"],
        tags=["SLA/SLI"],
        summary="SLI: карта эндпоинтов (проверка, что маршруты смонтированы)",
        include_in_schema=True,
    )
