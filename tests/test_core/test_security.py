# tests/test_core/test_security.py
import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_get_password_hash():
    """Тест хеширования пароля"""
    from app.core.security import get_password_hash
    
    password = "test_password_123"
    hashed = get_password_hash(password)
    
    # Проверяем что хеш не равен оригиналу
    assert hashed != password
    # Проверяем что хеш не пустой
    assert len(hashed) > 0
    # Проверяем формат (argon2 обычно начинается с $argon2)
    assert hashed.startswith("$argon2")
    
    print("✅ get_password_hash работает")

def test_verify_password():
    """Тест проверки пароля"""
    from app.core.security import verify_password, get_password_hash
    
    password = "secure_password_456"
    wrong_password = "wrong_password_789"
    
    # Генерируем хеш
    hashed = get_password_hash(password)
    
    # Проверяем правильный пароль
    assert verify_password(password, hashed) is True
    
    # Проверяем неправильный пароль
    assert verify_password(wrong_password, hashed) is False
    
    # Проверяем пустой пароль
    empty_hash = get_password_hash("")
    assert verify_password("", empty_hash) is True
    assert verify_password("not_empty", empty_hash) is False
    
    print("✅ verify_password работает")

def test_password_hash_consistency():
    """Тест консистентности хеширования"""
    from app.core.security import get_password_hash, verify_password
    
    password = "same_password"
    
    # Два хеша одного пароля должны быть разными (из-за соли)
    hash1 = get_password_hash(password)
    hash2 = get_password_hash(password)
    
    assert hash1 != hash2
    
    # Но оба должны верифицироваться
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True
    
    print("✅ Хеширование консистентно")