# app/api/health.py
"""Дополнительные health-эндпоинты: фичи и профиль развёртывания."""

from fastapi import APIRouter

from app.core.feature_flags import get_deployment_info

router = APIRouter(tags=["Health"])


@router.get("/health/features")
async def health_features():
    """Список фич и их состояние для текущего ``DEPLOYMENT_TYPE``."""
    info = get_deployment_info()
    return {
        "deployment_type": info["deployment_type"],
        "features": info["features"],
        "features_enabled": info["features_enabled"],
    }


@router.get("/health/deployment")
async def health_deployment():
    """Информация о типе развёртывания и связанных параметрах."""
    return get_deployment_info()
