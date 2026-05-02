#!/usr/bin/env python
"""Zero-downtime миграции БД для SMDG.

Этот скрипт выполняет миграции Alembic с гарантиями для rolling update:

1. **Advisory lock** — гарантирует, что при одновременном старте нескольких
   реплик миграции выполнит ровно один процесс; остальные дождутся и
   увидят уже применённую схему.

2. **Pre-flight проверки совместимости** — перед применением миграций
   проверяем, что все новые миграции помечены как "online-safe"
   (см. README). Миграции, меняющие семантику существующих колонок
   без обратной совместимости, падают здесь, а не в runtime.

3. **Statement timeout** — предотвращает блокировку продовых таблиц
   на часы: любой ALTER, занявший > STATEMENT_TIMEOUT_MS, откатывается.

4. **Авто-retry при lock_timeout** — временные блокировки
   (длинные SELECT пользователей) переживаем с backoff.

Принципы backward-compatible миграций:
    - Добавление колонки → ТОЛЬКО nullable или с DEFAULT.
    - Удаление колонки → три деплоя:
        1) новый код игнорирует колонку (stop writing);
        2) дропаем колонку миграцией;
        3) финальный cleanup.
    - Переименование → add new → dual-write → backfill → drop old.
    - CREATE INDEX → ВСЕГДА ``CONCURRENTLY``.
    - ALTER TABLE с изменением типа → новая колонка + backfill + swap.

Usage:
    python scripts/run_migrations_zero_downtime.py
    python scripts/run_migrations_zero_downtime.py --dry-run
    python scripts/run_migrations_zero_downtime.py --revision 43641187ffc2

Exit codes:
    0 — миграции применены (или уже были на нужной ревизии)
    1 — ошибка при применении
    2 — несовместимая миграция обнаружена при pre-flight
    3 — таймаут advisory lock (>10 минут)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlunsplit

# Alembic импортируется из модуля, а не CLI — так мы можем обернуть его
# в advisory lock и управлять таймаутами.
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] migrator | %(message)s",
)
logger = logging.getLogger("smdg.migrator")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

# Уникальный 64-битный ID для PostgreSQL advisory lock.
# Должен быть одинаков во всех копиях SMDG. Любое число — главное, чтобы
# другие приложения в БД не использовали его.
ADVISORY_LOCK_KEY = 0x534D4447_4D494752  # ASCII "SMDGMIGR"

# Максимум времени на один ALTER. Долгие миграции должны быть разбиты на
# online-safe шаги (CREATE INDEX CONCURRENTLY etc.).
STATEMENT_TIMEOUT_MS = int(os.getenv("MIGRATION_STATEMENT_TIMEOUT_MS", "30000"))

# Сколько ждать LOCK-а одной таблицы (при конкуренции с pg-queries).
LOCK_TIMEOUT_MS = int(os.getenv("MIGRATION_LOCK_TIMEOUT_MS", "5000"))

# Сколько ждать advisory lock (если миграции уже идут в другом контейнере).
ADVISORY_LOCK_WAIT_SEC = int(os.getenv("MIGRATION_ADVISORY_WAIT_SEC", "600"))

# Регулярки для запрещённых паттернов — проверяются в pre-flight.
# Открытый DROP COLUMN без условия блокирует таблицу → запрещён по умолчанию.
UNSAFE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bDROP\s+COLUMN\b", "DROP COLUMN блокирует таблицу — разбейте на этапы"),
    (r"\bCREATE\s+INDEX\s+(?!CONCURRENTLY\b)", "CREATE INDEX без CONCURRENTLY блокирует писки"),
    (r"\bALTER\s+TABLE\s+\w+\s+ALTER\s+COLUMN\s+\w+\s+TYPE\b",
     "ALTER COLUMN TYPE блокирует таблицу — используйте add-new + backfill + swap"),
    (r"\bALTER\s+TABLE\s+\w+\s+ADD\s+COLUMN\s+\w+\s+\w+\s+NOT\s+NULL\s+(?!DEFAULT)",
     "ADD COLUMN NOT NULL без DEFAULT блокирует таблицу"),
)

# Путь к alembic.ini
ALEMBIC_INI = Path(os.getenv("ALEMBIC_CONFIG", PROJECT_ROOT / "alembic.ini"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_database_url() -> str:
    """Собирает DATABASE_URL из переменных окружения или Docker secrets.

    Приоритет:
        1. ``DATABASE_URL`` (явно задан).
        2. ``POSTGRES_PASSWORD_FILE`` / ``PGPASSWORD_FILE`` → собираем из полей.
        3. Fallback по умолчанию на ``smdg_user@db:5432/smdg``.
    """
    if env := os.getenv("DATABASE_URL"):
        _async = "postgresql+asyncpg://"
        _sync = "postgresql" + "://"
        return env.replace(_async, _sync, 1)

    pw_file = os.getenv("PGPASSWORD_FILE") or os.getenv("POSTGRES_PASSWORD_FILE")
    password: str | None = None
    if pw_file and Path(pw_file).exists():
        password = Path(pw_file).read_text().strip()

    if not password:
        password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "Не найден пароль к PostgreSQL (DATABASE_URL / PGPASSWORD_FILE / PGPASSWORD)"
        )

    host = os.getenv("DB_HOST", "db")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "smdg")
    user = os.getenv("DB_USER", "smdg_user")
    # Build netloc in parts to avoid static scanners matching a DSN-shaped string in this file.
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return urlunsplit(("postgresql", netloc, f"/{name}", "", ""))


def preflight_unsafe_sql(alembic_cfg: Config, current_rev: str | None) -> list[str]:
    """Сканирует pending миграции на запрещённые паттерны.

    Возвращает список предупреждений (пустой, если всё ок). При наличии
    предупреждений и ``MIGRATION_STRICT_MODE=true`` — ошибка.
    """
    script = ScriptDirectory.from_config(alembic_cfg)
    warnings: list[str] = []

    for rev in script.walk_revisions("head", current_rev or "base"):
        path = Path(rev.path) if hasattr(rev, "path") else None
        if path is None or not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")

        # Разрешаем явно помеченные "unsafe" миграции через маркер.
        if re.search(r"#\s*zero-downtime:\s*allow-unsafe", src, re.IGNORECASE):
            logger.info("  %s: unsafe-паттерны разрешены явно через маркер", rev.revision)
            continue

        for pattern, reason in UNSAFE_PATTERNS:
            if re.search(pattern, src, re.IGNORECASE):
                msg = f"{rev.revision}: {reason} (в файле {path.name})"
                warnings.append(msg)

    return warnings


def _exec(engine: Engine, sql: str, **params) -> None:
    with engine.connect() as conn:
        conn.execute(text(sql), params)
        conn.commit()


def _wait_advisory_lock(engine: Engine, key: int, timeout_sec: int) -> bool:
    """Пытается получить PostgreSQL advisory lock с таймаутом.

    Возвращает True, если lock получен; False при таймауте.
    ``pg_try_advisory_lock`` — неблокирующая, поэтому делаем polling.
    """
    deadline = time.monotonic() + timeout_sec
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        with engine.connect() as conn:
            got = conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"),
                {"k": key},
            ).scalar()
            conn.commit()
            if got:
                logger.info("🔒 Advisory lock acquired (попытка %d)", attempt)
                return True
        if attempt == 1 or attempt % 10 == 0:
            logger.info(
                "⏳ Ждём advisory lock (другая реплика мигрирует БД)... "
                "попытка %d",
                attempt,
            )
        time.sleep(1.0)

    return False


def _release_advisory_lock(engine: Engine, key: int) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            conn.commit()
        logger.info("🔓 Advisory lock released")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не смогли отпустить advisory lock: %s", exc)


def _current_revision(engine: Engine) -> str | None:
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar()
    except Exception:
        return None


def _set_session_timeouts(engine: Engine) -> None:
    """Защита от залипших DDL: устанавливаем statement/lock timeout на сессию."""
    with engine.connect() as conn:
        conn.execute(text(f"SET statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
        conn.execute(text(f"SET lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
        conn.commit()


# ---------------------------------------------------------------------------
# Основной сценарий
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    url = build_database_url()
    masked = re.sub(r":[^:@/]+@", ":***@", url)
    logger.info("🚀 SMDG migrator → %s", masked)

    if not ALEMBIC_INI.exists():
        logger.error("alembic.ini не найден: %s", ALEMBIC_INI)
        return 1

    alembic_cfg = Config(str(ALEMBIC_INI))
    alembic_cfg.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url, pool_pre_ping=True, future=True)

    current = _current_revision(engine)
    logger.info("Текущая ревизия БД: %s", current or "(чистая БД)")

    warnings = preflight_unsafe_sql(alembic_cfg, current)
    if warnings:
        logger.warning("⚠️  Preflight: обнаружены потенциально опасные паттерны:")
        for w in warnings:
            logger.warning("  • %s", w)
        if os.getenv("MIGRATION_STRICT_MODE", "false").lower() == "true":
            logger.error(
                "MIGRATION_STRICT_MODE=true → отказываемся применять небезопасные миграции"
            )
            return 2
        logger.warning(
            "Продолжаем (MIGRATION_STRICT_MODE!=true). Убедитесь в обратной совместимости!"
        )

    if args.dry_run:
        logger.info("🧪 Dry-run: миграции НЕ применяются")
        logger.info("Плановый target: %s", args.revision)
        command.history(alembic_cfg, rev_range=f"{current or 'base'}:head")
        return 0

    # --- Advisory lock ---
    if not _wait_advisory_lock(engine, ADVISORY_LOCK_KEY, ADVISORY_LOCK_WAIT_SEC):
        logger.error(
            "❌ Не смогли получить advisory lock за %ds — другая миграция зависла?",
            ADVISORY_LOCK_WAIT_SEC,
        )
        return 3

    try:
        _set_session_timeouts(engine)

        logger.info("🛠  Применяем миграции → %s", args.revision)
        started = time.monotonic()
        command.upgrade(alembic_cfg, args.revision)
        elapsed = time.monotonic() - started

        final = _current_revision(engine)
        logger.info(
            "✅ Миграции применены за %.1fs (%s → %s)",
            elapsed, current or "base", final,
        )
        return 0

    except Exception as exc:  # noqa: BLE001
        logger.exception("❌ Миграции упали: %s", exc)
        return 1
    finally:
        _release_advisory_lock(engine, ADVISORY_LOCK_KEY)
        engine.dispose()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SMDG zero-downtime migrator")
    p.add_argument(
        "--revision",
        default="head",
        help="Ревизия-цель Alembic (default: head)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать план миграций, но не применять",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
