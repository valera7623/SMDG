from fastapi import APIRouter, Depends, HTTPException, status, Body, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel, Field
from typing import Annotated
from app.core.auth import create_access_token, get_current_user, TokenData
from app.core.database import get_db
from app.models.user import User
from app.core.security import verify_password, get_password_hash
from app.core import audit_logger
from app.core.rate_limiter import limiter, get_remote_address
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Упрощённый key_func для логина (только IP, чтобы избежать async проблем с form)
def login_rate_limit_key(request: Request):
    ip = get_remote_address(request)
    return f"login:{ip}"


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, description="Текущий пароль")
    new_password: str = Field(..., min_length=8, description="Новый пароль (мин. 8 символов)")


@router.post("/change-password", response_model=dict)
@limiter.limit(
    "5/minute",
    key_func=get_remote_address,
    error_message="Слишком много попыток смены пароля. Подождите минуту."
)
async def change_password(
    request: Request,  # ← обязательно для slowapi!
    request_body: ChangePasswordRequest = Body(...),
    current_user: Annotated[TokenData, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db)
):
    
    result = await db.execute(
        select(User).where(User.username == current_user.sub)
    )
    user = result.scalar_one_or_none()

    if not user:
        audit_logger.log_operation(
            action="change_password_failed",
            filename="",
            user=current_user.sub,
            reason="Пользователь не найден",
            success=False
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 2. Проверяем старый пароль
    if not verify_password(request_body.old_password, user.hashed_password):
        audit_logger.log_operation(
            action="change_password_failed",
            filename="",
            user=current_user.sub,
            reason="Неверный старый пароль",
            success=False
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный текущий пароль",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 3. Проверяем, что новый пароль ≠ старому
    if verify_password(request_body.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль не должен совпадать со старым"
        )

    # 4. Обновляем пароль
    new_hash = get_password_hash(request_body.new_password)

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(hashed_password=new_hash)
    )
    await db.commit()

    # 5. Логируем успех
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
@limiter.limit(
    "10/minute;5/10seconds",
    key_func=login_rate_limit_key,
    methods=["POST"],
    error_message="Слишком много попыток входа. Попробуйте через минуту.",
    exempt_when=lambda: False
)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    # Находим пользователя
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        audit_logger.log_operation(
            action="login_failed",
            filename="",
            user=username,
            reason="Пользователь не найден или отключён",
            success=False
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not verify_password(password, user.hashed_password):
        audit_logger.log_operation(
            action="login_failed",
            filename="",
            user=username,
            reason="Неверный пароль",
            success=False
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"}
        )

    access_token = create_access_token(
        subject=user.username,
        role=user.role,
        expires_delta=timedelta(minutes=60)
    )

    audit_logger.log_operation(
        action="login_success",
        filename="",
        user=username,
        reason="Успешный вход",
        success=True
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "expires_in": 3600
    }