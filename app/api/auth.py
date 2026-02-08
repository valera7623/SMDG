# auth.py - обновлённая версия (добавлены изменения)
from fastapi import APIRouter, Depends, HTTPException, status, Body, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from app.core.auth import create_access_token, get_current_user, TokenData
from app.core.database import get_db
from app.models.user import User
from app.core.security import verify_password, get_password_hash
from app.core import audit_logger
from app.core.rate_limiter import limiter, get_remote_address
from datetime import timedelta
import pyotp  # Новая зависимость
import base64

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Упрощённый key_func для логина (только IP, чтобы избежать async проблем с form)
def login_rate_limit_key(request: Request):
    ip = get_remote_address(request)
    return f"login:{ip}"


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, description="Текущий пароль")
    new_password: str = Field(..., min_length=8, description="Новый пароль (мин. 8 символов)")
    otp_code: Optional[str] = Field(None, min_length=6, max_length=6, description="Код 2FA (опционально, если включён)")


class LoginRequest(BaseModel):
    username: str = Field(..., description="Имя пользователя")
    password: str = Field(..., description="Пароль")
    otp_code: Optional[str] = Field(None, min_length=6, max_length=6, description="Код 2FA (опционально, если включён)")


def generate_otp_secret():
    """Генерация нового OTP секрета"""
    return pyotp.random_base32()


def get_otp_url(username: str, secret: str, issuer_name: str = "SMDG System"):
    """Генерация URL для QR-кода"""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=issuer_name
    )


def verify_otp_code(secret: str, code: str) -> bool:
    """Верификация OTP кода"""
    if not secret or not code:
        return False
    
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)  # valid_window=1 для небольшого запаса


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

    # 3. Проверяем 2FA если включён
    if user.otp_secret:
        if not request_body.otp_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Требуется код 2FA"
            )
        
        if not verify_otp_code(user.otp_secret, request_body.otp_code):
            audit_logger.log_operation(
                action="change_password_failed",
                filename="",
                user=current_user.sub,
                reason="Неверный код 2FA",
                success=False
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный код 2FA"
            )

    # 4. Проверяем, что новый пароль ≠ старому
    if verify_password(request_body.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль не должен совпадать со старым"
        )

    # 5. Генерируем новый OTP секрет при смене пароля
    new_otp_secret = generate_otp_secret()

    # 6. Обновляем пароль и OTP секрет
    new_hash = get_password_hash(request_body.new_password)

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            hashed_password=new_hash,
            otp_secret=new_otp_secret  # Генерируем новый секрет
        )
    )
    await db.commit()

    # 7. Логируем успех
    audit_logger.log_operation(
        action="change_password",
        filename="",
        user=current_user.sub,
        reason="Пароль успешно изменён, OTP секрет обновлён",
        success=True,
        metadata={
            "username": current_user.sub,
            "otp_secret_regenerated": True
        }
    )

    return {
        "message": "Пароль успешно изменён",
        "otp_secret": new_otp_secret,
        "otp_url": get_otp_url(current_user.sub, new_otp_secret),
        "warning": "Сохраните этот секрет для настройки 2FA!"
    }


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
    otp_code: Optional[str] = Form(None),  # Новый параметр для 2FA
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

    # Проверка 2FA если секрет установлен
    if user.otp_secret:
        if not otp_code:
            # Если 2FA включён, но код не предоставлен
            audit_logger.log_operation(
                action="login_failed",
                filename="",
                user=username,
                reason="Требуется код 2FA",
                success=False
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Требуется код 2FA",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        if not verify_otp_code(user.otp_secret, otp_code):
            audit_logger.log_operation(
                action="login_failed",
                filename="",
                user=username,
                reason="Неверный код 2FA",
                success=False
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный код 2FA",
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
        reason="Успешный вход" + (" (с 2FA)" if user.otp_secret else ""),
        success=True,
        metadata={
            "2fa_enabled": user.otp_secret is not None
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "expires_in": 3600,
        "2fa_enabled": user.otp_secret is not None
    }


@router.post("/setup-2fa", response_model=dict)
@limiter.limit(
    "3/minute",
    key_func=get_remote_address,
    error_message="Слишком много запросов на настройку 2FA"
)
async def setup_2fa(
    request: Request,
    current_user: Annotated[TokenData, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Эндпоинт для первоначальной настройки 2FA"""
    result = await db.execute(
        select(User).where(User.username == current_user.sub)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    # Генерируем новый OTP секрет
    new_secret = generate_otp_secret()
    
    # Обновляем пользователя
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(otp_secret=new_secret)
    )
    await db.commit()

    audit_logger.log_operation(
        action="setup_2fa",
        filename="",
        user=current_user.sub,
        reason="Настройка 2FA",
        success=True,
        metadata={"username": current_user.sub}
    )

    return {
        "otp_secret": new_secret,
        "otp_url": get_otp_url(current_user.sub, new_secret),
        "message": "Отсканируйте QR-код в приложении аутентификатора",
        "instructions": "Сохраните секрет в безопасном месте!"
    }


@router.post("/disable-2fa", response_model=dict)
@limiter.limit(
    "3/minute",
    key_func=get_remote_address,
    error_message="Слишком много запросов на отключение 2FA"
)
async def disable_2fa(
    request: Request,
    otp_code: str = Form(...),  # Требуется код для отключения
    current_user: Annotated[TokenData, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Эндпоинт для отключения 2FA"""
    result = await db.execute(
        select(User).where(User.username == current_user.sub)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    if not user.otp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA не включен"
        )

    # Проверяем код перед отключением
    if not verify_otp_code(user.otp_secret, otp_code):
        audit_logger.log_operation(
            action="disable_2fa_failed",
            filename="",
            user=current_user.sub,
            reason="Неверный код 2FA",
            success=False
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный код 2FA"
        )

    # Отключаем 2FA
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(otp_secret=None)
    )
    await db.commit()

    audit_logger.log_operation(
        action="disable_2fa",
        filename="",
        user=current_user.sub,
        reason="Отключение 2FA",
        success=True,
        metadata={"username": current_user.sub}
    )

    return {
        "message": "2FA успешно отключен",
        "warning": "Рекомендуется немедленно настроить 2FA заново для безопасности"
    }