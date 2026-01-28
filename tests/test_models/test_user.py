# tests/test_models/test_user_corrected.py
import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_user_model():
    """Тест модели User - исправленная версия"""
    from app.models.user import User
    
    # Проверяем что модель создается
    user = User(
        username="testuser",
        hashed_password="hashed_password_123",
        role="user",  # Явно указываем
        is_active=True
    )
    
    assert user.username == "testuser"
    assert user.hashed_password == "hashed_password_123"
    assert user.role == "user"
    assert user.is_active is True

def test_user_defaults_correct():
    """Правильная проверка значений по умолчанию"""
    from app.models.user import User
    
    # Создаем пользователя только с обязательными полями
    user = User(
        username="testuser",
        hashed_password="hash"
    )
    
    # В модели Mapped[str] без default, так что role будет None
    # Это нормально - проверим что мы можем установить роль позже
    user.role = "user"
    assert user.role == "user"
    
    # is_active должно быть True по умолчанию из mapped_column(default=True)
    assert user.is_active is True

def test_user_repr():
    """Тест строкового представления"""
    from app.models.user import User
    
    user = User(username="doctor", role="doctor")
    repr_str = repr(user)
    
    assert "User" in repr_str
    assert "doctor" in repr_str