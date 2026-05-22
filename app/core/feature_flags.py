"""
Feature flags и матрица возможностей по типу развёртывания (DeploymentType).

Чтение текущего профиля выполняется через app.core.config.settings (ленивый импорт,
чтобы избежать циклических зависимостей при загрузке модулей).
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class DeploymentType(str, Enum):
    RUSSIA = "russia"
    INTERNATIONAL = "intl"
    SINGLE_TENANT = "single"
    SAAS = "saas"
    DEMO = "demo"


class Feature(str, Enum):
    # === Базовые фичи (есть везде) ===
    DICOM_VIEWER = "dicom_viewer"      # DICOM Viewer — ВЕЗДЕ
    TOTP_2FA = "totp_2fa"              # 2FA — ВЕЗДЕ
    
    # === Хранилище ===
    S3_STORAGE = "s3_storage"
    LOCAL_STORAGE = "local_storage"

    # === Безопасность ===
    MANDATORY_2FA = "mandatory_2fa"    # Обязательная 2FA (Россия для всех, SaaS для admin)
    GOST_CRYPTO = "gost_crypto"
    AUDIT_3_YEARS = "audit_3_years"
    GOSSOPKA = "gossopka"

    # === Интеграции ===
    PACS_INTEGRATION = "pacs_integration"

    # === Multi-tenancy (только SaaS) ===
    MULTI_TENANCY = "multi_tenancy"
    BILLING = "billing"
    WHITE_LABEL = "white_label"

    # === GDPR права ===
    RIGHT_TO_BE_FORGOTTEN = "right_to_be_forgotten"
    DATA_PORTABILITY = "data_portability"

    # === Self-hosted удобства ===
    AUTO_SSL = "auto_ssl"
    AUTO_BACKUP = "auto_backup"
    SIMPLE_ADMIN = "simple_admin"


# Значение: bool или dict с ключом "enabled" и дополнительными параметрами
FEATURE_MATRIX: dict[DeploymentType, dict[Feature, Any]] = {
    DeploymentType.RUSSIA: {
        # Базовые (везде)
        Feature.DICOM_VIEWER: True,
        Feature.TOTP_2FA: True,
        
        # Хранилище
        Feature.LOCAL_STORAGE: True,
        Feature.S3_STORAGE: False,
        
        # Безопасность
        Feature.MANDATORY_2FA: True,      # Обязательная 2FA для всех
        Feature.GOST_CRYPTO: True,
        Feature.AUDIT_3_YEARS: True,
        Feature.GOSSOPKA: True,
        
        # Интеграции
        Feature.PACS_INTEGRATION: False,
        
        # Multi-tenancy
        Feature.MULTI_TENANCY: False,
        Feature.BILLING: False,
        Feature.WHITE_LABEL: False,
        
        # GDPR
        Feature.RIGHT_TO_BE_FORGOTTEN: False,
        Feature.DATA_PORTABILITY: True,
        
        # Self-hosted
        Feature.AUTO_SSL: False,
        Feature.AUTO_BACKUP: True,
        Feature.SIMPLE_ADMIN: False,
    },
    
    DeploymentType.INTERNATIONAL: {
        # Базовые (везде)
        Feature.DICOM_VIEWER: True,
        Feature.TOTP_2FA: True,
        
        # Хранилище
        Feature.LOCAL_STORAGE: False,
        Feature.S3_STORAGE: True,
        
        # Безопасность
        Feature.MANDATORY_2FA: False,     # Опциональная 2FA
        Feature.GOST_CRYPTO: False,
        Feature.AUDIT_3_YEARS: False,
        Feature.GOSSOPKA: False,
        
        # Интеграции
        Feature.PACS_INTEGRATION: True,
        
        # Multi-tenancy
        Feature.MULTI_TENANCY: False,
        Feature.BILLING: False,
        Feature.WHITE_LABEL: False,
        
        # GDPR
        Feature.RIGHT_TO_BE_FORGOTTEN: True,
        Feature.DATA_PORTABILITY: True,
        
        # Self-hosted
        Feature.AUTO_SSL: False,
        Feature.AUTO_BACKUP: False,
        Feature.SIMPLE_ADMIN: False,
    },
    
    DeploymentType.SINGLE_TENANT: {
        # Базовые (везде)
        Feature.DICOM_VIEWER: True,
        Feature.TOTP_2FA: True,
        
        # Хранилище (опционально S3 через конфиг)
        Feature.LOCAL_STORAGE: True,
        Feature.S3_STORAGE: False,        # По умолчанию локальное, но может быть включено через .env
        
        # Безопасность
        Feature.MANDATORY_2FA: False,     # Опциональная
        Feature.GOST_CRYPTO: False,
        Feature.AUDIT_3_YEARS: False,
        Feature.GOSSOPKA: False,
        
        # Интеграции
        Feature.PACS_INTEGRATION: False,
        
        # Multi-tenancy
        Feature.MULTI_TENANCY: False,
        Feature.BILLING: False,
        Feature.WHITE_LABEL: False,
        
        # GDPR
        Feature.RIGHT_TO_BE_FORGOTTEN: False,
        Feature.DATA_PORTABILITY: False,
        
        # Self-hosted (удобства)
        Feature.AUTO_SSL: True,
        Feature.AUTO_BACKUP: True,
        Feature.SIMPLE_ADMIN: True,
    },
    
    DeploymentType.SAAS: {
        # Базовые (везде)
        Feature.DICOM_VIEWER: True,
        Feature.TOTP_2FA: True,
        
        # Хранилище
        Feature.LOCAL_STORAGE: False,
        Feature.S3_STORAGE: True,
        
        # Безопасность
        Feature.MANDATORY_2FA: True,      # Обязательная для admin (проверка по роли в коде)
        Feature.GOST_CRYPTO: False,
        Feature.AUDIT_3_YEARS: False,
        Feature.GOSSOPKA: False,
        
        # Интеграции
        Feature.PACS_INTEGRATION: True,
        
        # Multi-tenancy
        Feature.MULTI_TENANCY: True,
        Feature.BILLING: True,
        Feature.WHITE_LABEL: True,
        
        # GDPR
        Feature.RIGHT_TO_BE_FORGOTTEN: True,
        Feature.DATA_PORTABILITY: True,
        
        # Self-hosted
        Feature.AUTO_SSL: True,
        Feature.AUTO_BACKUP: False,
        Feature.SIMPLE_ADMIN: False,
    },

    DeploymentType.DEMO: {
        # Core (enabled everywhere)
        Feature.DICOM_VIEWER: True,        # key showcase feature for portfolio
        Feature.TOTP_2FA: True,            # visible but not mandatory

        # Storage — local only, no MinIO to fit 2GB RAM
        Feature.LOCAL_STORAGE: True,
        Feature.S3_STORAGE: False,

        # Security
        Feature.MANDATORY_2FA: False,      # don't block quick evaluation
        Feature.GOST_CRYPTO: False,
        Feature.AUDIT_3_YEARS: False,
        Feature.GOSSOPKA: False,

        # Integrations
        Feature.PACS_INTEGRATION: False,

        # Multi-tenancy
        Feature.MULTI_TENANCY: False,
        Feature.BILLING: False,
        Feature.WHITE_LABEL: False,

        # GDPR/HIPAA — show compliance capabilities to US audience
        Feature.RIGHT_TO_BE_FORGOTTEN: True,
        Feature.DATA_PORTABILITY: True,

        # Self-hosted conveniences
        Feature.AUTO_SSL: True,
        Feature.AUTO_BACKUP: False,
        Feature.SIMPLE_ADMIN: True,        # simplified admin for easy evaluation
    },
}


def _matrix_row() -> dict[Feature, Any]:
    from app.core.config import settings

    return FEATURE_MATRIX.get(settings.deployment_type, FEATURE_MATRIX[DeploymentType.SINGLE_TENANT])


def _coerce_enabled(raw: Any) -> bool:
    if isinstance(raw, dict):
        return bool(raw.get("enabled", True))
    return bool(raw)


def is_enabled(feature: Feature) -> bool:
    """Проверка: включена ли фича для текущего DEPLOYMENT_TYPE."""
    row = _matrix_row()
    if feature not in row:
        return False
    return _coerce_enabled(row[feature])


def get_feature_value(feature: Feature, default: Any = None) -> Any:
    """Значение фичи из матрицы (для параметризованных флагов) либо default."""
    row = _matrix_row()
    if feature not in row:
        return default
    return row[feature]


def is_2fa_mandatory() -> bool:
    """
    2FA обязательна для всех пользователей (Россия) или только для admin (SaaS).
    Для международной и single-tenant версии 2FA опциональна.
    """
    from app.core.config import settings
    
    if settings.deployment_type == DeploymentType.RUSSIA:
        return True  # Для всех пользователей
    if settings.deployment_type == DeploymentType.SAAS:
        return True  # Для admin, проверка по роли в коде
    return False  # Опционально


def is_2fa_required_for_user(role: str) -> bool:
    """
    Проверка, требуется ли 2FA для конкретного пользователя.
    
    Args:
        role: Роль пользователя ('admin', 'doctor', 'user', 'super_admin')
    
    Returns:
        True если 2FA обязательна для этого пользователя, False если опциональна
    """
    from app.core.config import settings
    
    if settings.deployment_type == DeploymentType.RUSSIA:
        return True  # Для всех пользователей
    
    if settings.deployment_type == DeploymentType.SAAS and role in ("admin", "super_admin"):
        return True  # Только для admin и super_admin в SaaS
    
    return False  # Опционально для остальных


def get_deployment_info() -> dict[str, Any]:
    """Сводка по текущему развёртыванию и включённым фичам."""
    from app.core.config import settings

    dt = settings.deployment_type
    enabled_features = sorted(
        [f.value for f in Feature if is_enabled(f)],
        key=lambda x: x,
    )
    return {
        "deployment_type": dt.value,
        "deployment_label": {
            DeploymentType.RUSSIA: "Russia (FZ-152)",
            DeploymentType.INTERNATIONAL: "International (GDPR/HIPAA-oriented)",
            DeploymentType.SINGLE_TENANT: "Self-hosted single tenant",
            DeploymentType.SAAS: "SaaS multi-tenant",
        }.get(dt, dt.value),
        "audit_retention_days": settings.audit_retention_days,
        "simple_admin": is_enabled(Feature.SIMPLE_ADMIN),
        "features_enabled": enabled_features,
        "features": {f.value: is_enabled(f) for f in Feature},
        "mandatory_2fa_for_all": is_2fa_mandatory(),
    }


def deployment_supports_feature(deployment: DeploymentType, feature: Feature) -> bool:
    """Проверка фичи для явно заданного типа развёртывания (тесты, CLI)."""
    row = FEATURE_MATRIX.get(deployment, {})
    if feature not in row:
        return False
    return _coerce_enabled(row[feature])