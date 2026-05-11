# tests/test_core/test_config.py
import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_load_test_mode_defaults_false(monkeypatch):
    """LOAD_TEST_MODE must be opt-in: accidental enablement breaks tenant resolution and timeouts."""
    monkeypatch.delenv("LOAD_TEST_MODE", raising=False)
    from app.core.config import Settings

    assert Settings().load_test_mode is False


def test_get_cors_allow_origins_merges_env(monkeypatch):
    """CORS_ORIGINS из окружения добавляются к базовому списку, без дубликатов."""
    import app.core.config as cfg

    monkeypatch.setattr(cfg.settings, "cors_origins", "https://app.example.com, https://app.example.com ")
    monkeypatch.setattr(cfg.settings, "cors_include_dev_origins", True)
    origins = cfg.get_cors_allow_origins()
    assert "https://app.example.com" in origins
    assert origins.count("https://app.example.com") == 1
    assert "http://localhost:3000" in origins
    assert "https://viewer.ohif.org" in origins


def test_get_cors_allow_origins_can_disable_dev_origins(monkeypatch):
    """Production can disable localhost origins and rely on explicit HTTPS origins."""
    import app.core.config as cfg

    monkeypatch.setattr(cfg.settings, "cors_origins", "https://app.example.com")
    monkeypatch.setattr(cfg.settings, "cors_include_dev_origins", False)
    origins = cfg.get_cors_allow_origins()

    assert "https://app.example.com" in origins
    assert "https://viewer.ohif.org" in origins
    assert "http://localhost:3000" not in origins


def test_require_secure_cookies_rejects_insecure_cookie():
    """Production guard fails fast when secure cookies are required but disabled."""
    from app.core.config import Settings

    with pytest.raises(ValueError, match="COOKIE_SECURE=true"):
        Settings(require_secure_cookies=True, cookie_secure=False)


def test_require_secure_cookies_allows_secure_cookie():
    """Production guard accepts secure cookie configuration."""
    from app.core.config import Settings

    settings = Settings(require_secure_cookies=True, cookie_secure=True)
    assert settings.cookie_secure is True


def test_config_import():
    """Тест импорта конфигурации"""
    from app.core.config import Settings, settings
    
    assert hasattr(settings, 'database_url')
    assert hasattr(settings, 'jwt_secret_key')
    assert hasattr(settings, 'jwt_algorithm')
    assert hasattr(settings, 'MAX_UPLOAD_SIZE_MB')
    assert hasattr(settings, 'ALLOWED_MIME_TYPES')
    
    # Проверяем значения по умолчанию
    assert settings.jwt_algorithm == "HS256"
    assert "application/pdf" in settings.ALLOWED_MIME_TYPES

def test_config_environment():
    """Тест загрузки конфигурации из окружения"""
    import os
    from unittest.mock import patch
    
    with patch.dict(os.environ, {
        'DATABASE_URL': 'sqlite:///test.db',
        'JWT_SECRET_KEY': 'test_secret_key',
        'DEBUG': 'true'
    }):
        # Переимпортируем для применения переменных окружения
        import importlib
        import app.core.config
        importlib.reload(app.core.config)
        
        assert app.core.config.settings.database_url == 'sqlite:///test.db'
        assert app.core.config.settings.debug is True