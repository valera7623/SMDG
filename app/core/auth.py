# app/core/auth.py
from fastapi import Depends, HTTPException, status, Cookie
from typing import Annotated

import jwt
from jwt.exceptions import PyJWTError as JWTError
from jwt import decode as jwt_decode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .auth_utils import TokenData, create_access_token
from app.core.database import get_db
from app.models.user import User


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
        payload = jwt_decode(access_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        role: str = payload.get("role", "user")
        tenant_id: int | None = payload.get("tenant_id")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Некорректный токен: отсутствует subject"
            )
        return TokenData(sub=username, role=role, tenant_id=tenant_id)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Недействительный токен: {str(e)}"
        )


async def get_current_doctor(
    current_user: Annotated[TokenData, Depends(get_current_user)]
) -> TokenData:
    if current_user.role not in {"doctor", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только врачам и администраторам"
        )
    return current_user


async def get_current_admin(
    current_user: Annotated[TokenData, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenData:
    if current_user.role not in {"admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администраторам"
        )

    stmt = select(User).where(User.username == current_user.sub)
    if current_user.role != "super_admin" and current_user.tenant_id is not None:
        stmt = stmt.where(User.tenant_id == current_user.tenant_id)
    db_user = (await db.execute(stmt)).scalar_one_or_none()
    if not db_user or not db_user.is_active or db_user.role not in {"admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Администраторская сессия больше не действительна"
        )
    if db_user.role != current_user.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Роль пользователя изменилась; выполните вход повторно"
        )
    return TokenData(sub=db_user.username, role=db_user.role, tenant_id=db_user.tenant_id)