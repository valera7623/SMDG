"""Test-only operational endpoints for reliability checks."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import TokenData, get_current_user
from app.core.database import execute_with_timeout as execute_db_with_timeout
from app.core.database import get_db

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/slow-query")
async def slow_query(
    sleep_seconds: int = Query(
        15,
        ge=1,
        le=120,
        description="How long PostgreSQL should sleep before returning",
    ),
    _user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute controlled slow DB query to validate timeout behavior."""
    dialect_name = getattr(getattr(db, "bind", None), "dialect", None)
    dialect = getattr(dialect_name, "name", "")
    if dialect != "postgresql":
        raise HTTPException(
            status_code=400,
            detail="slow-query endpoint requires PostgreSQL backend",
        )

    await execute_db_with_timeout(
        db.execute(
            text("SELECT pg_sleep(:sleep_seconds)"),
            {"sleep_seconds": sleep_seconds},
        ),
        operation="test_slow_query",
    )
    return {"status": "ok", "sleep_seconds": sleep_seconds}

