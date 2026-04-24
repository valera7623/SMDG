"""Add archive tables and file archive flags

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("files", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "deleted_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("original_user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deleted_users_original_user_id", "deleted_users", ["original_user_id"], unique=False)
    op.create_index("ix_deleted_users_tenant_id", "deleted_users", ["tenant_id"], unique=False)

    op.create_table(
        "archive_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("archive_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_table", sa.String(length=64), nullable=False),
        sa.Column("archive_path", sa.String(length=1024), nullable=False),
        sa.Column("archive_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("archive_checksum", sa.String(length=128), nullable=False),
        sa.Column("storage_tier", sa.String(length=32), nullable=False, server_default="glacier"),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="archived"),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("archive_id"),
    )
    op.create_index("ix_archive_records_archive_id", "archive_records", ["archive_id"], unique=False)
    op.create_index("ix_archive_records_source_type", "archive_records", ["source_type"], unique=False)
    op.create_index("ix_archive_records_source_id", "archive_records", ["source_id"], unique=False)
    op.create_index("ix_archive_records_status", "archive_records", ["status"], unique=False)

    op.create_table(
        "archive_restore_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("archive_id", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("request_reason", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("restored_path", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["archive_id"], ["archive_records.archive_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_archive_restore_requests_request_id",
        "archive_restore_requests",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_archive_restore_requests_archive_id",
        "archive_restore_requests",
        ["archive_id"],
        unique=False,
    )
    op.create_index(
        "ix_archive_restore_requests_status",
        "archive_restore_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_deleted_users_tenant_id", table_name="deleted_users")
    op.drop_index("ix_deleted_users_original_user_id", table_name="deleted_users")
    op.drop_table("deleted_users")

    op.drop_index("ix_archive_restore_requests_status", table_name="archive_restore_requests")
    op.drop_index("ix_archive_restore_requests_archive_id", table_name="archive_restore_requests")
    op.drop_index("ix_archive_restore_requests_request_id", table_name="archive_restore_requests")
    op.drop_table("archive_restore_requests")

    op.drop_index("ix_archive_records_status", table_name="archive_records")
    op.drop_index("ix_archive_records_source_id", table_name="archive_records")
    op.drop_index("ix_archive_records_source_type", table_name="archive_records")
    op.drop_index("ix_archive_records_archive_id", table_name="archive_records")
    op.drop_table("archive_records")

    op.drop_column("files", "archived_at")
    op.drop_column("files", "is_archived")
