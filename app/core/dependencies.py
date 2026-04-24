"""Database dependencies for read/write split."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.database_router import get_db_router


async def get_db_for_read(request: Request) -> AsyncGenerator[AsyncSession, None]:  # noqa: ARG001
    router = get_db_router()
    if router is None:
        async for session in get_db():
            yield session
        return

    session = await router.get_read_session()
    try:
        yield session
    finally:
        await session.close()


async def get_db_for_write(request: Request) -> AsyncGenerator[AsyncSession, None]:  # noqa: ARG001
    router = get_db_router()
    if router is None:
        async for session in get_db():
            yield session
        return

    session = await router.get_write_session()
    try:
        yield session
    finally:
        await session.close()


async def get_db_auto(request: Request) -> AsyncGenerator[AsyncSession, None]:
    router = get_db_router()
    if router is None:
        async for session in get_db():
            yield session
        return

    if request.method in {"GET", "HEAD", "OPTIONS"}:
        session = await router.get_read_session()
    else:
        session = await router.get_write_session()

    if session is None:
        raise HTTPException(status_code=503, detail="Database router unavailable")

    try:
        yield session
    finally:
        await session.close()
