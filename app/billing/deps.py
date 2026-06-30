"""Shared helpers for billing API routes."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_utils import TokenData
from app.models.user import User


async def require_billing_user(
    db: AsyncSession,
    current_user: TokenData,
    tenant_id: int | None = None,
) -> User:
    stmt = select(User).where(User.username == current_user.sub, User.is_active.is_(True))
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    elif current_user.tenant_id is not None:
        stmt = stmt.where(User.tenant_id == current_user.tenant_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if not user.email:
        raise HTTPException(status_code=400, detail="Для оплаты требуется email в профиле")
    return user
