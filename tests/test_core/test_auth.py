# tests/test_core/test_auth.py
import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_create_access_token():
    """Тест создания JWT токена"""
    from app.core.auth import create_access_token
    
    token = create_access_token("testuser", "admin")
    
    assert isinstance(token, str)
    assert len(token) > 0
    
    # Можно декодировать и проверить
    import jwt
    from app.core.config import settings
    
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "testuser"
    assert payload["role"] == "admin"
    assert "exp" in payload

@pytest.mark.asyncio
async def test_get_current_user_valid():
    """Тест получения пользователя из валидного токена"""
    from app.core.auth import get_current_user, create_access_token, TokenData

    # Создаём валидный токен
    token = create_access_token("testuser", "admin")

    # get_current_user принимает строку из Cookie, не HTTPAuthorizationCredentials
    user = await get_current_user(access_token=token)

    assert isinstance(user, TokenData)
    assert user.sub == "testuser"
    assert user.role == "admin"


@pytest.mark.asyncio
async def test_get_current_user_invalid():
    """Тест получения пользователя из невалидного токена"""
    from app.core.auth import get_current_user
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(access_token="invalid_token")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_no_token():
    """Тест без токена — должен вернуть 401"""
    from app.core.auth import get_current_user
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(access_token=None)

    assert exc_info.value.status_code == 401


def test_token_data_model():
    """Тест модели TokenData"""
    from app.core.auth import TokenData
    
    token_data = TokenData(sub="testuser", role="admin")
    assert token_data.sub == "testuser"
    assert token_data.role == "admin"
    
    # Проверяем значения по умолчанию
    token_data_default = TokenData(sub="testuser")
    assert token_data_default.role == "user"