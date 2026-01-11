# app/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from typing import AsyncGenerator
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

# DATABASE_URL должен быть в .env
# Пример: postgresql+asyncpg://user:password@localhost:5432/smdg
DATABASE_URL = settings.database_url

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.debug,           # логирование SQL в dev-режиме
    future=True,
    pool_pre_ping=True,
)

# Для обычных сессий (рекомендуется использовать в зависимостях)
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


# Зависимость для получения сессии в эндпоинтах
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session