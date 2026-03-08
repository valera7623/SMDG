# app/core/auth.py

from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials  # пока оставляем, если где-то ещё используется
from typing import Annotated
import jwt
from jwt.exceptions import PyJWTError as JWTError
from jwt import decode as jwt_decode
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional
from .config import settings
from .auth_utils import TokenData, create_access_token

# ──── Определяем модели и константы прямо здесь ────
class TokenData(BaseModel):
    sub: str
    role: str = "user"


SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_access_expires_minutes  # если есть в settings


# ──── Базовая зависимость (теперь работает без цикла) ────
async def get_current_user(
    access_token: Annotated[str | None, Cookie(alias="access_token")] = None
) -> TokenData:
    """
    Проверяет JWT-токен из HttpOnly cookie и возвращает данные пользователя
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не авторизован (токен в cookie отсутствует)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt_decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "user")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Некорректный токен: отсутствует subject"
            )
        return TokenData(sub=username, role=role)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Недействительный токен: {str(e)}"
        )


# ──── Композиционные зависимости (без изменений) ────
async def get_current_doctor(
    current_user: Annotated[TokenData, Depends(get_current_user)]
) -> TokenData:
    """Только врачи и админы"""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только врачам и администраторам"
        )
    return current_user


async def get_current_admin(
    current_user: Annotated[TokenData, Depends(get_current_user)]
) -> TokenData:
    """Только админ"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администраторам"
        )
    return current_user