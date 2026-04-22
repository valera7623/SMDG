# app/core/database.py
"""
Database configuration with lazy loading.
Uses standalone Base from app.models.base to avoid circular imports.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Awaitable, Callable, TypeVar

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.models.base import Base  # Используем общий Base
from app.core.timeout import TimeoutError, run_with_timeout

logger = logging.getLogger(__name__)

T = TypeVar("T")


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
        from app.core.config import settings
        _engine = create_async_engine(
            url,
            echo=debug,
            future=True,
            pool_pre_ping=True,
            connect_args={"timeout": settings.DB_CONNECTION_TIMEOUT_SECONDS},
        )
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


async def _db_session_ping(session: AsyncSession) -> None:
    """Минимальный запрос к PostgreSQL под circuit breaker (ленивое соединение)."""
    await execute_with_timeout(session.execute(text("SELECT 1")))


async def execute_with_timeout(coro: Awaitable[T], *, operation: str = "db_query") -> T:
    """Выполнить DB-операцию с таймаутом и HTTP 504 при превышении."""
    from app.core.config import settings

    try:
        return await run_with_timeout(
            coro,
            timeout_seconds=float(settings.DB_QUERY_TIMEOUT_SECONDS),
            error_message=(
                f"Database query timeout after {settings.DB_QUERY_TIMEOUT_SECONDS}s"
            ),
            service="database",
            operation=operation,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@asynccontextmanager
async def transaction_with_timeout(session: AsyncSession):
    """Транзакция с контролем общего времени выполнения."""
    from app.core.config import settings

    tx = await session.begin()
    try:
        yield session
        await run_with_timeout(
            tx.commit(),
            timeout_seconds=float(settings.DB_TRANSACTION_TIMEOUT_SECONDS),
            error_message="Transaction timeout",
            service="database",
            operation="db_transaction",
        )
    except Exception:
        await tx.rollback()
        raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Сессия БД; перед отдачей в обработчик выполняется ``SELECT 1`` через
    circuit breaker ``postgresql``, чтобы при падении БД считались ошибки
    и открывался брейкер (а при OPEN — мгновенный 503 без шторма к pool).
    """
    async with _get_sessionmaker()() as session:
        await execute_with_db_circuit_breaker(_db_session_ping, session)
        yield session


# ---------------------------------------------------------------------------
# Circuit Breaker integration (PostgreSQL)
# ---------------------------------------------------------------------------
#
# Критерий срабатывания: мы защищаем произвольную async-операцию над БД.
# HTTPException из бизнес-логики, а также CircuitBreakerOpenError (она и так
# не долетает до зависимости) — НЕ считаются ошибками брейкера: их генерирует
# приложение, а не упавшая БД.
#
# Идея использования:
#
#     async def _load(session):
#         return await session.execute(stmt)
#
#     data = await execute_with_db_circuit_breaker(_load, session)
#
# При открытом брейкере вместо реального SQL-запроса будет брошен
# ``HTTPException(status_code=503, ...)`` — хэндлеру FastAPI это удобнее,
# чем ловить кастомный класс в каждом роутере.


DB_CIRCUIT_BREAKER_NAME = "postgresql"


def _get_db_circuit_breaker():
    """Ленивый импорт, чтобы не тянуть circuit_breaker на старте миграций."""
    from app.core.circuit_breaker import get_circuit_breaker

    return get_circuit_breaker(
        DB_CIRCUIT_BREAKER_NAME,
        exclude_exceptions=(HTTPException,),
    )


async def execute_with_db_circuit_breaker(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Выполнить async-операцию над PostgreSQL под защитой Circuit Breaker.

    При открытом брейкере преобразует :class:`CircuitBreakerOpenError` в
    HTTP 503 с понятным сообщением и инкрементирует Prometheus-метрику
    ``smdg_circuit_breaker_rejected_calls_total``.
    """
    from app.core.circuit_breaker import CircuitBreakerOpenError
    from app.core.circuit_breaker_metrics import record_rejected_call

    cb = _get_db_circuit_breaker()
    try:
        return await cb.call(func, *args, **kwargs)
    except CircuitBreakerOpenError:
        record_rejected_call(DB_CIRCUIT_BREAKER_NAME)
        logger.warning(
            "DB circuit breaker is OPEN — rejecting request before reaching PostgreSQL"
        )
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable. Please try again later.",
        )
    except HTTPException:
        # Пробрасываем уже корректно сформированные HTTP-ошибки как есть.
        raise
    except Exception as exc:
        # UX-upgrade: пока брейкер ещё в CLOSED и только копит ошибки до порога,
        # наружу тоже отдаём 503 (а не сырой 500), чтобы для клиента поведение
        # было единообразным на всём деградированном интервале.
        logger.warning(
            "DB operation failed before circuit opens; returning 503: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable. Please try again later.",
        ) from exc
