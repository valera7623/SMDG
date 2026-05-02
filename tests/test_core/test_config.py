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