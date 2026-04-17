"""add multi tenant core

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f7
Create Date: 2026-04-17 22:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subdomain", sa.String(length=100), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("subdomain", name="uq_tenants_subdomain"),
    )
    op.create_index("ix_tenants_subdomain", "tenants", ["subdomain"], unique=True)

    op.execute(
        sa.text(
            "INSERT INTO tenants (name, subdomain, settings) VALUES "
            "('Default Tenant', 'default', '{}'::jsonb)"
        )
    )

    op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("files", sa.Column("tenant_id", sa.Integer(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE users SET tenant_id = (SELECT id FROM tenants WHERE subdomain = 'default') "
            "WHERE tenant_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE files SET tenant_id = COALESCE("
            "(SELECT u.tenant_id FROM users u WHERE u.id = files.user_id), "
            "(SELECT id FROM tenants WHERE subdomain = 'default')"
            ") WHERE tenant_id IS NULL"
        )
    )

    op.create_foreign_key("fk_users_tenant_id_tenants", "users", "tenants", ["tenant_id"], ["id"])
    op.create_foreign_key("fk_files_tenant_id_tenants", "files", "tenants", ["tenant_id"], ["id"])
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
    op.create_index("ix_files_tenant_id", "files", ["tenant_id"], unique=False)

    op.alter_column("users", "tenant_id", nullable=False)
    op.alter_column("files", "tenant_id", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_files_tenant_id", table_name="files")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_constraint("fk_files_tenant_id_tenants", "files", type_="foreignkey")
    op.drop_constraint("fk_users_tenant_id_tenants", "users", type_="foreignkey")
    op.drop_column("files", "tenant_id")
    op.drop_column("users", "tenant_id")
    op.drop_index("ix_tenants_subdomain", table_name="tenants")
    op.drop_table("tenants")
