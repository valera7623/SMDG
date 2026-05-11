"""Add file access events

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_access_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("destination", sa.String(length=512), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=True),
        sa.Column("encrypted_name", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("actor_username", sa.String(length=128), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failure_reason", sa.String(length=1024), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_access_events_tenant_id", "file_access_events", ["tenant_id"], unique=False)
    op.create_index("ix_file_access_events_file_id", "file_access_events", ["file_id"], unique=False)
    op.create_index("ix_file_access_events_actor_user_id", "file_access_events", ["actor_user_id"], unique=False)
    op.create_index("ix_file_access_events_action", "file_access_events", ["action"], unique=False)
    op.create_index("ix_file_access_events_success", "file_access_events", ["success"], unique=False)
    op.create_index("ix_file_access_events_created_at", "file_access_events", ["created_at"], unique=False)
    op.create_index(
        "ix_file_access_events_tenant_created_at",
        "file_access_events",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_access_events_tenant_action_created_at",
        "file_access_events",
        ["tenant_id", "action", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_access_events_tenant_actor_created_at",
        "file_access_events",
        ["tenant_id", "actor_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_access_events_tenant_file_created_at",
        "file_access_events",
        ["tenant_id", "file_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_file_access_events_tenant_file_created_at", table_name="file_access_events")
    op.drop_index("ix_file_access_events_tenant_actor_created_at", table_name="file_access_events")
    op.drop_index("ix_file_access_events_tenant_action_created_at", table_name="file_access_events")
    op.drop_index("ix_file_access_events_tenant_created_at", table_name="file_access_events")
    op.drop_index("ix_file_access_events_created_at", table_name="file_access_events")
    op.drop_index("ix_file_access_events_success", table_name="file_access_events")
    op.drop_index("ix_file_access_events_action", table_name="file_access_events")
    op.drop_index("ix_file_access_events_actor_user_id", table_name="file_access_events")
    op.drop_index("ix_file_access_events_file_id", table_name="file_access_events")
    op.drop_index("ix_file_access_events_tenant_id", table_name="file_access_events")
    op.drop_table("file_access_events")
