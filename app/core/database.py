# app/core/database.py
"""
Database configuration with lazy loading.
Uses standalone Base from app.models.base to avoid circular imports.
"""
import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.models.base import Base  # Используем общий Base


# Read DATABASE_URL from environment first (for Alembic/Docker compatibility)
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_engine = None


def _get_database_url() -> str:
    """Get DATABASE_URL from env or settings."""
    if _DATABASE_URL:
        return _DATABASE_URL
    from app.core.config import settings
    return settings.database_url


def get_engine():
    """Get or create the async engine (lazy initialization)."""
    global _engine
    if _engine is None:
        url = _get_database_url()
        debug = os.environ.get("DEV_MODE", "").lower() == "true"
        if not debug:
            try:
                from app.core.config import settings
                debug = settings.debug
            except Exception:
                pass
        _engine = create_async_engine(url, echo=debug, future=True, pool_pre_ping=True)
    return _engine


def _get_sessionmaker():
    return sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


# Backwards compatibility
class _LazyEngine:
    def __getattr__(self, name):
        return getattr(get_engine(), name)


class _LazySession:
    def __call__(self):
        return _get_sessionmaker()()
    def __getattr__(self, name):
        return getattr(_get_sessionmaker(), name)


engine = _LazyEngine()
AsyncSessionLocal = _LazySession()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _get_sessionmaker()() as session:
        yield session
