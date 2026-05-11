# app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status, Body, Form, Request, Response, Cookie
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Annotated, Optional
import re

from app.core.auth import get_current_user, get_current_admin
from app.core.auth_utils import create_access_token, TokenData
from app.core.config import settings
from app.core.database import get_db, execute_with_db_circuit_breaker
from app.models.user import User
from app.models.tenant import Tenant
from app.core.security import verify_password, get_password_hash
from app.core import audit_logger
from app.core.rate_limiter import limiter, get_remote_address
from app.core.tenant import require_tenant, assert_tenant_access
from app.core.feature_flags import Feature, is_enabled, is_2fa_required_for_user
from datetime import timedelta
import pyotp

router = APIRouter(prefix="/auth", tags=["Authentication"])
LOGIN_RATE_LIMIT = settings.rate_limit_login
if settings.load_test_mode and LOGIN_RATE_LIMIT == "10/minute;5/10seconds":
    # Safe pre-prod default override for auth capacity tests.
    LOGIN_RATE_LIMIT = "2000/minute;500/10seconds"


# ==================== Pydantic V2 Models ====================

class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    otp_code: Optional[str] = Field(None, min_length=6, max_length=6)

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Пароль должен быть не менее 8 символов')
        return v


class Verify2FARequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    otp_code: Optional[str] = Field(None, min_length=6, max_length=6)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError('Неверный формат email')
        return v


# ==================== Утилиты ====================

def generate_otp_secret() -> str:
    return pyotp.random_base32()


def get_otp_url(username: str, secret: str, issuer_name: str = "SMDG System") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=issuer_name
    )


def verify_otp_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


async def _load_current_db_user(
    db: AsyncSession,
    current_user: TokenData,
    tenant,
) -> User:
    """Загрузить запись пользователя из БД по данным токена и текущего тенанта.

    Бросает HTTPException(404), если пользователь не найден.
    """
    result = await db.execute(
        select(User).where(User.username == current_user.sub, User.tenant_id == tenant.id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


# ==================== Эндпоинты ====================

@router.post("/change-password")
@limiter.limit("5/minute", key_func=get_remote_address)
async def change_password(
    request: Request,
    request_body: ChangePasswordRequest = Body(...),
    current_user: Annotated[TokenData, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db)
):
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    user = await _load_current_db_user(db, current_user, tenant)

    if not verify_password(request_body.old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный текущий пароль")

    if user.otp_secret:
        if not request_body.otp_code or not verify_otp_code(user.otp_secret, request_body.otp_code):
            if not request_body.otp_code:
                raise HTTPException(status_code=400, detail="Требуется код 2FA")
            raise HTTPException(status_code=401, detail="Неверный код 2FA")

    if verify_password(request_body.new_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Новый пароль не должен совпадать со старым")

    new_otp_secret = generate_otp_secret()
    new_hash = get_password_hash(request_body.new_password)

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(hashed_password=new_hash, otp_secret=new_otp_secret)
    )
    await db.commit()

    audit_logger.log_operation(
        action="change_password",
        filename="",
        user=current_user.sub,
        reason="Пароль успешно изменён",
        success=True
    )

    return {
        "message": "Пароль успешно изменён",
        "otp_secret": new_otp_secret,
        "otp_url": get_otp_url(current_user.sub, new_otp_secret)
    }


@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT, key_func=get_remote_address)
async def login(
    response: Response,
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    otp_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    tenant = require_tenant(request)
    print(f"[LOGIN] Попытка входа: username={username}, otp_provided={bool(otp_code)}")

    # Поиск пользователя
    result = await execute_with_db_circuit_breaker(
        db.execute,
        select(User).where(User.username == username, User.tenant_id == tenant.id),
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        print(f"[LOGIN] ❌ Пользователь не найден или неактивен")
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

    # Проверка пароля
    if not verify_password(password, user.hashed_password):
        print("[LOGIN] ❌ Неверный пароль")
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

    if is_enabled(Feature.MANDATORY_2FA) and not user.otp_secret:
        raise HTTPException(
            status_code=403,
            detail="Для данного развёртывания требуется 2FA. Настройте секрет через администратора или CLI",
        )

    # === ОБРАБОТКА 2FA ===
    if user.otp_secret:
        if not otp_code:
            # Это ключевой момент — фронтенд ждёт именно 400
            print("[LOGIN] ⚠️  2FA включена, но код не передан → показываем форму")
            raise HTTPException(
                status_code=400,
                detail="Требуется код 2FA"
            )
        if not verify_otp_code(user.otp_secret, otp_code):
            print("[LOGIN] ❌ Неверный код 2FA")
            raise HTTPException(status_code=401, detail="Неверный код 2FA")
        print("[LOGIN] ✅ Код 2FA верный")
    else:
        print("[LOGIN] 2FA отключена — вход без кода")


    # === ПРОВЕРКА: ДОЛЖНА ЛИ БЫТЬ 2FA ВКЛЮЧЕНА ===
    if is_2fa_required_for_user(user.role) and not user.otp_secret:
        # Требуется 2FA, но она не настроена
        raise HTTPException(
            status_code=400,
            detail="2FA обязательна. Пожалуйста, настройте двухфакторную аутентификацию"
        )
        

    # Создание токена
    access_token = create_access_token(subject=user.username, role=user.role, tenant_id=user.tenant_id)

    # Установка cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=3600,
        path="/"
    )

    print(f"[LOGIN] ✅ Успешный вход пользователя {username}")

    if not settings.load_test_mode:
        audit_logger.log_operation(
            action="login_success",
            filename="",
            user=username,
            reason="Успешный вход",
            success=True
        )

    return {
        "message": "Успешный вход",
        "username": user.username,
        "role": user.role,
        "2fa_enabled": bool(user.otp_secret)
    }


@router.post("/logout")
@limiter.limit("60/minute", key_func=get_remote_address)
async def logout(request: Request, response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return {"message": "Вы успешно вышли из системы"}


@router.post("/setup-2fa")
@limiter.limit("3/minute", key_func=get_remote_address)
async def setup_2fa(
    request: Request,
    current_user: Annotated[TokenData, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    user = await _load_current_db_user(db, current_user, tenant)

    new_secret = generate_otp_secret()

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(otp_secret=new_secret)
    )
    await db.commit()

    return {
        "message": "Отсканируйте QR-код в приложении аутентификатора",
        "otp_url": get_otp_url(current_user.sub, new_secret),
        "instructions": [
            "1. Откройте приложение-аутентификатор",
            "2. Добавьте новую учётную запись",
            "3. Отсканируйте QR-код или введите строку вручную",
            "4. Введите сгенерированный код для подтверждения"
        ]
    }


@router.post("/verify-2fa-setup")
@limiter.limit("5/minute", key_func=get_remote_address)
async def verify_2fa_setup(
    request: Request,
    current_user: Annotated[TokenData, Depends(get_current_user)],
    req: Verify2FARequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    user = await _load_current_db_user(db, current_user, tenant)

    if not user.otp_secret:
        raise HTTPException(status_code=400, detail="2FA ещё не настроена")

    if verify_otp_code(user.otp_secret, req.code):
        audit_logger.log_operation("verify_2fa_success", "", current_user.sub, success=True)
        return {"message": "2FA успешно настроена и проверена!"}
    else:
        raise HTTPException(status_code=400, detail="Неверный код")


@router.post("/disable-2fa")
@limiter.limit("3/minute", key_func=get_remote_address)
async def disable_2fa(
    request: Request,
    current_user: Annotated[TokenData, Depends(get_current_user)],
    otp_code: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    user = await _load_current_db_user(db, current_user, tenant)

    if not user.otp_secret:
        raise HTTPException(status_code=400, detail="2FA не включена")

    if not verify_otp_code(user.otp_secret, otp_code):
        raise HTTPException(status_code=401, detail="Неверный код 2FA")

    if is_enabled(Feature.MANDATORY_2FA):
        raise HTTPException(
            status_code=403,
            detail="Отключение 2FA запрещено политикой развёртывания",
        )

    await db.execute(update(User).where(User.id == user.id).values(otp_secret=None))
    await db.commit()

    audit_logger.log_operation("disable_2fa", "", current_user.sub, success=True)

    return {"message": "2FA успешно отключен", "warning": "Ваша учётная запись теперь защищена только паролем"}


@router.post("/register")
@limiter.limit("10/minute", key_func=get_remote_address)
async def register(
    request: Request,
    user_data: RegisterRequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    tenant = require_tenant(request)
    result = await db.execute(
        select(User).where(User.username == user_data.username, User.tenant_id == tenant.id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")

    result = await db.execute(
        select(User).where(User.email == user_data.email, User.tenant_id == tenant.id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        role="user",
        is_active=True,
        tenant_id=tenant.id,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    audit_logger.log_operation(
        action="user_registered",
        filename="",
        user=new_user.username,
        reason="Новый пользователь зарегистрирован",
        success=True
    )

    new_otp_secret = generate_otp_secret()

    return {
        "message": "Пользователь успешно зарегистрирован",
        "username": new_user.username,
        "email": new_user.email,
        "role": new_user.role,
        "otp_secret": new_otp_secret,
        "otp_url": get_otp_url(new_user.username, new_otp_secret),
        "2fa_enabled": False
    }