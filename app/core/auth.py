# app/core/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import PyJWTError as JWTError
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional
from .config import settings

# Схема Bearer токена
security = HTTPBearer()

class TokenData(BaseModel):
    sub: str  # username или ID
    role: str = "user"  # user, doctor, admin

# Константы из настроек
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_access_expires_minutes

def create_access_token(subject: str, role: str = "user", expires_delta: Optional[timedelta] = None) -> str:
    """
    Создаёт JWT access-токен
    """
    to_encode = {"sub": subject, "role": role}
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Зависимость: проверяет Bearer токен и возвращает данные пользователя
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "user")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token: missing subject")
        return TokenData(sub=username, role=role)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

async def get_current_doctor(current_user: TokenData = Depends(get_current_user)):
    """Только врачи и админы"""
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Doctor or admin access required")
    return current_user

async def get_current_admin(current_user: TokenData = Depends(get_current_user)):
    """Только админ"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user