# tests/test_api/test_auth.py
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_auth_module_import():
    """Тест импорта auth модуля"""
    from app.api import auth
    
    assert hasattr(auth, 'router')
    
    # Проверяем модели
    from app.api.auth import ChangePasswordRequest
    
    # Создаем экземпляр модели
    change_req = ChangePasswordRequest(
        old_password="old_pass",
        new_password="new_pass_123"
    )
    
    assert change_req.old_password == "old_pass"
    assert change_req.new_password == "new_pass_123"
    
    print("✅ Auth модуль импортирован")

def test_auth_router_routes():
    """Тест маршрутов auth"""
    from app.api.auth import router
    
    routes = []
    for route in router.routes:
        if hasattr(route, 'path'):
            routes.append(str(route.path))
    
    # Проверяем основные маршруты
    assert any("/auth/login" in r for r in routes)
    assert any("/auth/change-password" in r for r in routes)
    
    print(f"✅ Auth router имеет {len(routes)} маршрутов")

def test_change_password_model():
    """Тест модели ChangePasswordRequest"""
    from app.api.auth import ChangePasswordRequest
    from pydantic import ValidationError
    
    # Валидные данные
    valid_data = ChangePasswordRequest(
        old_password="current_pass",
        new_password="new_password_123"  # мин 8 символов
    )
    assert valid_data.old_password == "current_pass"
    
    # Невалидные данные (слишком короткий новый пароль)
    try:
        ChangePasswordRequest(
            old_password="current",
            new_password="short"  # меньше 8 символов
        )
        assert False, "Должно быть исключение ValidationError"
    except ValidationError:
        pass  # Ожидаемое поведение
    
    print("✅ ChangePasswordRequest модель работает")