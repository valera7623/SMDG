"""add dead letter queue tables

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dead_letter_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("queue_name", sa.String(length=50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_dead_letter_messages_message_id", "dead_letter_messages", ["message_id"], unique=False)
    op.create_index("ix_dead_letter_messages_queue_name", "dead_letter_messages", ["queue_name"], unique=False)
    op.create_index("ix_dead_letter_messages_status", "dead_letter_messages", ["status"], unique=False)
    op.create_index("idx_dlq_queue_status", "dead_letter_messages", ["queue_name", "status"], unique=False)
    op.create_index("idx_dlq_next_retry", "dead_letter_messages", ["next_retry_at"], unique=False)

    op.create_table(
        "dead_letter_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["message_id"], ["dead_letter_messages.message_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dead_letter_logs_message_id", "dead_letter_logs", ["message_id"], unique=False)
    op.create_index("idx_dlq_logs_message", "dead_letter_logs", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_dlq_logs_message", table_name="dead_letter_logs")
    op.drop_index("ix_dead_letter_logs_message_id", table_name="dead_letter_logs")
    op.drop_table("dead_letter_logs")

    op.drop_index("idx_dlq_next_retry", table_name="dead_letter_messages")
    op.drop_index("idx_dlq_queue_status", table_name="dead_letter_messages")
    op.drop_index("ix_dead_letter_messages_status", table_name="dead_letter_messages")
    op.drop_index("ix_dead_letter_messages_queue_name", table_name="dead_letter_messages")
    op.drop_index("ix_dead_letter_messages_message_id", table_name="dead_letter_messages")
    op.drop_table("dead_letter_messages")
