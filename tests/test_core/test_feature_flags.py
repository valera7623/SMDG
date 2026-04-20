# tests/test_core/test_feature_flags.py
import pytest

from app.core.feature_flags import (
    DeploymentType,
    Feature,
    deployment_supports_feature,
    get_deployment_info,
    is_enabled,
)


@pytest.mark.parametrize(
    "deployment,feature,expected",
    [
        (DeploymentType.RUSSIA, Feature.MANDATORY_2FA, True),
        (DeploymentType.RUSSIA, Feature.S3_STORAGE, False),
        (DeploymentType.INTERNATIONAL, Feature.S3_STORAGE, True),
        (DeploymentType.SINGLE_TENANT, Feature.SIMPLE_ADMIN, True),
        (DeploymentType.SAAS, Feature.MULTI_TENANCY, True),
    ],
)
def test_matrix_each_deployment(deployment, feature, expected):
    assert deployment_supports_feature(deployment, feature) is expected


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 48)


def test_is_enabled_and_deployment_info(jwt_secret, monkeypatch):
    import app.core.config as cfg

    monkeypatch.setenv("DEPLOYMENT_TYPE", "russia")
    monkeypatch.setenv("S3_ENABLED", "false")
    monkeypatch.setattr(cfg, "settings", cfg.Settings())

    assert is_enabled(Feature.MANDATORY_2FA) is True
    assert is_enabled(Feature.S3_STORAGE) is False

    info = get_deployment_info()
    assert info["deployment_type"] == "russia"
    assert info["audit_retention_days"] == 1095
    assert isinstance(info["features_enabled"], list)


def test_audit_retention_days_property(jwt_secret, monkeypatch):
    import app.core.config as cfg

    monkeypatch.setenv("DEPLOYMENT_TYPE", "intl")
    monkeypatch.setenv("S3_ENABLED", "false")
    monkeypatch.setattr(cfg, "settings", cfg.Settings())

    assert cfg.settings.audit_retention_days == 365


def test_storage_backend_factory_respects_russia(tmp_path, jwt_secret, monkeypatch):
    import app.core.config as cfg

    monkeypatch.setenv("DEPLOYMENT_TYPE", "russia")
    monkeypatch.setenv("S3_ENABLED", "false")
    monkeypatch.setattr(cfg, "settings", cfg.Settings())

    from app.core.storage_backend import LocalStorageBackend, get_storage_backend

    backend = get_storage_backend(local_base_dir=tmp_path)
    assert isinstance(backend, LocalStorageBackend)


def test_crypto_proxy_age_by_default(jwt_secret, monkeypatch):
    import app.core.config as cfg

    monkeypatch.setenv("DEPLOYMENT_TYPE", "intl")
    monkeypatch.setenv("S3_ENABLED", "false")
    monkeypatch.setattr(cfg, "settings", cfg.Settings())

    from app.crypto.crypto import crypto_manager, get_crypto_backend

    cm = get_crypto_backend()
    assert hasattr(cm, "encrypt") and callable(cm.encrypt)
    assert callable(crypto_manager.check_age_installed)
