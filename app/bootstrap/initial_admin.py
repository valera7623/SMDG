"""Создание первого администратора и вспомогательные проверки в dev."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models import Tenant, User


async def ensure_admin_exists(session: AsyncSession) -> None:
    result = await session.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one_or_none()

    if not admin:
        print("⚡ Создаём первого администратора...")
        admin = User(
            username="admin",
            hashed_password=get_password_hash("ChangeMe123!"),
            role="admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        print("✅ Админ создан. Логин: admin | Пароль: ChangeMe123! (измените немедленно!)")
    else:
        if not admin.hashed_password.startswith("$argon2"):
            print("⚠️  Обнаружен НЕВАЛИДНЫЙ хэш пароля у admin!")
            print("   Текущее значение:", repr(admin.hashed_password[:50]))
            print("   Автоматически перехэшируем...")
            admin.hashed_password = get_password_hash("ChangeMe123!")
            await session.commit()
            print("✅ Хэш пароля исправлен (argon2)")


async def create_first_admin() -> None:
    """Создаёт первого администратора, если его ещё нет (только в dev-режиме)."""
    if not settings.dev_mode:
        print("👀 Production-режим: пропускаем создание тестового админа")
        return

    async with AsyncSessionLocal() as db:
        tenant_result = await db.execute(select(Tenant).where(Tenant.subdomain == "default"))
        default_tenant = tenant_result.scalar_one_or_none()
        if not default_tenant:
            default_tenant = Tenant(name="Default Tenant", subdomain="default", settings={})
            db.add(default_tenant)
            await db.commit()
            await db.refresh(default_tenant)

        result = await db.execute(select(User).where(User.username == "admin"))
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            print("ℹ️  Пользователь admin уже существует")
            changed = False
            if not existing_admin.email:
                existing_admin.email = "admin@example.com"
                changed = True
            if not existing_admin.tenant_id:
                existing_admin.tenant_id = default_tenant.id
                changed = True
            if changed:
                await db.commit()
                print("✅ Tenant/email добавлены существующему admin")
            return

        admin = User(
            username="admin",
            email="admin@example.com",
            hashed_password=get_password_hash("admin123"),
            role="admin",
            is_active=True,
            tenant_id=default_tenant.id,
        )
        db.add(admin)
        await db.commit()

        print("=" * 60)
        print("🔐 СОЗДАН ПЕРВЫЙ АДМИНИСТРАТОР")
        print("   Логин:    admin")
        print("   Пароль:   admin")
        print("   Email:    admin@example.com")
        print("   Роль:     admin")
        print("=" * 60)
