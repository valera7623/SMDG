import logging
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# Импорт Base из standalone модуля (НЕ тянет Settings)
from app.models.base import Base
from app.models.user import User
from app.models.file import File
from app.models.file_link import FileLink
try:
    from app.models.webhook import WebhookSubscription, WebhookDelivery
except ImportError:
    pass

target_metadata = Base.metadata

if not config.get_main_option("sqlalchemy.url"):
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    if not database_url:
        database_url = "postgresql://smdg_user:password@localhost:5432/smdg"
    config.set_main_option("sqlalchemy.url", database_url)

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
