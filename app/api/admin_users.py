# app/api/admin_users.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Annotated
import re

from app.core.database import get_db
from app.core.auth import get_current_admin, TokenData
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.core import audit_logger

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])


# ==================== Pydantic схемы (Pydantic V2) ====================

class UserResponse(BaseModel):
    """Модель пользователя для ответа API"""
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    otp_secret: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserCreateRequest(BaseModel):
    """Создание нового пользователя администратором"""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)
    role: str = Field("user", pattern="^(user|doctor|admin)$")
    is_active: bool = True

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError('Неверный формат email')
        return v


class UserUpdateRequest(BaseModel):
    """Обновление пользователя"""
    email: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = Field(None, pattern="^(user|doctor|admin)$")
    is_active: Optional[bool] = None
    reset_password: Optional[bool] = False
    new_password: Optional[str] = Field(None, min_length=8)
    reset_2fa: Optional[bool] = False

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError('Неверный формат email')
        return v


class UserPasswordResetRequest(BaseModel):
    """Сброс пароля администратором"""
    new_password: str = Field(..., min_length=8)


class BulkUserActionRequest(BaseModel):
    """Массовые операции с пользователями"""
    user_ids: List[int]
    action: str  # 'activate', 'deactivate', 'delete', 'change_role'
    role: Optional[str] = Field(None, pattern="^(user|doctor|admin)$")


class UserStatsResponse(BaseModel):
    """Статистика по пользователям"""
    total_users: int
    active_users: int
    inactive_users: int
    admins: int
    doctors: int
    regular_users: int
    users_with_2fa: int


# ==================== Эндпоинты ====================

@router.get("/", response_model=List[UserResponse])
async def get_all_users(
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None, pattern="^(user|doctor|admin)$"),
    active_only: bool = Query(False)
):
    query = select(User)

    if search:
        query = query.where(
            (User.username.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )

    if role:
        query = query.where(User.role == role)

    if active_only:
        query = query.where(User.is_active == True)

    query = query.offset(skip).limit(limit).order_by(User.id)

    result = await db.execute(query)
    users = result.scalars().all()

    audit_logger.log_operation(
        action="admin_view_users",
        filename="",
        user=current_admin.sub,
        reason=f"Админ просмотрел список пользователей (найдено: {len(users)})",
        success=True,
        metadata={"filters": {"search": search, "role": role, "active_only": active_only}}
    )

    return users


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    audit_logger.log_operation(
        action="admin_view_user",
        filename="",
        user=current_admin.sub,
        reason=f"Просмотр пользователя {user.username}",
        success=True
    )

    return user


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreateRequest,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db)
):
    print(f"=== СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ ===")
    print(f"Получены данные: {user_data.model_dump()}")

    # Проверка уникальности username
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")

    # Проверка уникальности email
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        role=user_data.role,
        is_active=user_data.is_active
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    audit_logger.log_operation(
        action="admin_create_user",
        filename="",
        user=current_admin.sub,
        reason=f"Создан пользователь {new_user.username}",
        success=True,
        metadata={"created_user_id": new_user.id, "created_user_role": new_user.role}
    )

    return new_user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    update_data: UserUpdateRequest,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.username == current_admin.sub:
        raise HTTPException(status_code=400, detail="Нельзя изменять свою учётную запись через этот эндпоинт")

    changes = {}

    if update_data.email and update_data.email != user.email:
        result = await db.execute(select(User).where(User.email == update_data.email, User.id != user_id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        user.email = update_data.email
        changes["email"] = True

    if update_data.role and update_data.role != user.role:
        user.role = update_data.role
        changes["role"] = update_data.role

    if update_data.is_active is not None and update_data.is_active != user.is_active:
        user.is_active = update_data.is_active
        changes["is_active"] = update_data.is_active

    if update_data.reset_password and update_data.new_password:
        user.hashed_password = get_password_hash(update_data.new_password)
        changes["password_reset"] = True

    if update_data.reset_2fa and user.otp_secret:
        user.otp_secret = None
        changes["2fa_reset"] = True

    if changes:
        await db.commit()
        await db.refresh(user)

        audit_logger.log_operation(
            action="admin_update_user",
            filename="",
            user=current_admin.sub,
            reason=f"Обновлен пользователь {user.username}",
            success=True,
            metadata=changes
        )

    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db),
    confirm: bool = Query(False)
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Требуется подтверждение удаления (confirm=true)")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.username == current_admin.sub:
        raise HTTPException(status_code=400, detail="Нельзя удалить свою учётную запись")

    if user.role == "admin":
        result = await db.execute(select(User).where(User.role == "admin"))
        admins = result.scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status_code=400, detail="Нельзя удалить последнего администратора")

    username = user.username
    await db.delete(user)
    await db.commit()

    audit_logger.log_operation(
        action="admin_delete_user",
        filename="",
        user=current_admin.sub,
        reason=f"Удален пользователь {username}",
        success=True
    )

    return {"message": f"Пользователь {username} успешно удален"}


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    reset_data: UserPasswordResetRequest,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.username == current_admin.sub:
        raise HTTPException(status_code=400, detail="Используйте /auth/change-password для смены своего пароля")

    user.hashed_password = get_password_hash(reset_data.new_password)
    await db.commit()

    audit_logger.log_operation(
        action="admin_reset_password",
        filename="",
        user=current_admin.sub,
        reason=f"Сброшен пароль пользователя {user.username}",
        success=True
    )

    return {"message": f"Пароль пользователя {user.username} успешно сброшен"}


@router.post("/bulk")
async def bulk_user_actions(
    action_data: BulkUserActionRequest,
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db)
):
    if not action_data.user_ids:
        raise HTTPException(status_code=400, detail="Не указаны пользователи")

    # Запрещаем массовые операции над самим собой
    result = await db.execute(
        select(User).where(User.id.in_(action_data.user_ids), User.username == current_admin.sub)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Нельзя применять массовые операции к своей учётной записи")

    affected_count = 0

    if action_data.action == "activate":
        result = await db.execute(update(User).where(User.id.in_(action_data.user_ids)).values(is_active=True))
        affected_count = result.rowcount

    elif action_data.action == "deactivate":
        result = await db.execute(select(User).where(User.id.in_(action_data.user_ids), User.role == "admin"))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Нельзя деактивировать администраторов")
        result = await db.execute(update(User).where(User.id.in_(action_data.user_ids)).values(is_active=False))
        affected_count = result.rowcount

    elif action_data.action == "change_role":
        if not action_data.role:
            raise HTTPException(status_code=400, detail="Не указана новая роль")
        result = await db.execute(select(User).where(User.id.in_(action_data.user_ids), User.role == "admin"))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Нельзя изменить роль администраторов")
        result = await db.execute(update(User).where(User.id.in_(action_data.user_ids)).values(role=action_data.role))
        affected_count = result.rowcount

    elif action_data.action == "delete":
        result = await db.execute(select(User).where(User.id.in_(action_data.user_ids), User.role == "admin"))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Нельзя удалять администраторов")
        result = await db.execute(delete(User).where(User.id.in_(action_data.user_ids)))
        affected_count = result.rowcount

    else:
        raise HTTPException(status_code=400, detail=f"Неизвестное действие: {action_data.action}")

    await db.commit()

    audit_logger.log_operation(
        action=f"admin_bulk_{action_data.action}",
        filename="",
        user=current_admin.sub,
        reason=f"Массовая операция {action_data.action} над {affected_count} пользователями",
        success=True,
        metadata={"action": action_data.action, "user_ids": action_data.user_ids, "affected_count": affected_count}
    )

    return {
        "message": f"Операция '{action_data.action}' выполнена над {affected_count} пользователями",
        "affected_count": affected_count
    }


@router.get("/stats/overview", response_model=UserStatsResponse)
async def get_user_stats(
    current_admin: Annotated[TokenData, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User))
    all_users = result.scalars().all()

    total = len(all_users)
    active = sum(1 for u in all_users if u.is_active)
    inactive = total - active
    admins = sum(1 for u in all_users if u.role == "admin")
    doctors = sum(1 for u in all_users if u.role == "doctor")
    regular = sum(1 for u in all_users if u.role == "user")
    with_2fa = sum(1 for u in all_users if u.otp_secret)

    return UserStatsResponse(
        total_users=total,
        active_users=active,
        inactive_users=inactive,
        admins=admins,
        doctors=doctors,
        regular_users=regular,
        users_with_2fa=with_2fa
    )