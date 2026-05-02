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
from app.models.archive import ArchiveRecord, ArchiveRestoreRequest
from app.models.deleted_user import DeletedUser
try:
    from app.models.webhook import WebhookSubscription, WebhookDelivery
except ImportError:
    pass

target_metadata = Base.metadata

database_url = os.getenv("DATABASE_URL", "")
_async = "postgresql+asyncpg://"
_sync = "postgresql" + "://"
if database_url.startswith(_async):
    database_url = database_url.replace(_async, _sync, 1)

# Always prioritize DATABASE_URL from runtime environment (entrypoint composes it
# from Docker secret postgres_password). This prevents stale credentials from
# sqlalchemy.url in alembic.ini after password rotations.
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)
elif not config.get_main_option("sqlalchemy.url"):
    _default_sqlalchemy = "postgresql" + "://" + "smdg_user@localhost:5432/smdg"
    config.set_main_option("sqlalchemy.url", _default_sqlalchemy)

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
