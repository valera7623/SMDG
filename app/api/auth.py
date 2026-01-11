from fastapi import APIRouter, Depends, HTTPException, status, Body, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel, Field
from typing import Annotated
from app.core.auth import create_access_token, get_current_user, TokenData
from app.core.database import get_db
from app.models.user import User
from app.core.security import pwd_context, verify_password, get_password_hash
from app.core import audit_logger
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])






class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, description="Текущий пароль")
    new_password: str = Field(..., min_length=8, description="Новый пароль (мин. 8 символов)")


@router.post("/change-password", response_model=dict)
async def change_password(
    request: ChangePasswordRequest = Body(...),
    current_user: Annotated[TokenData, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Смена пароля текущего пользователя.
    Требуется указать старый пароль для верификации.
    """
    # 1. Находим пользователя по sub (username)
    result = await db.execute(
        select(User).where(User.username == current_user.sub)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    # 2. Проверяем старый пароль
    if not verify_password(request.old_password, user.hashed_password):
        audit_logger.log_operation(
            action="change_password_failed",
            filename="",
            user=current_user.sub,
            reason="Неверный старый пароль",
            success=False
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный текущий пароль"
        )

    # 3. Проверяем, что новый пароль ≠ старому (опционально, но хорошая практика)
    if verify_password(request.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль не должен совпадать со старым"
        )

    # 4. Обновляем пароль
    new_hash = get_password_hash(request.new_password)

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(hashed_password=new_hash)
    )
    await db.commit()

    # 5. Логируем успешную смену
    audit_logger.log_operation(
        action="change_password",
        filename="",
        user=current_user.sub,
        reason="Пароль успешно изменён",
        success=True,
        metadata={"username": current_user.sub}
    )

    return {"message": "Пароль успешно изменён"}


@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    # Находим пользователя
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not pwd_context.verify(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        subject=user.username,
        role=user.role,
        expires_delta=timedelta(minutes=60)
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "expires_in": 3600
    }