"""add billing subscriptions and payments tables

Revision ID: g7h8i9j0k1l2
Revises: a2b3c4d5e6f7
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_type", sa.String(length=32), nullable=False, server_default="freemium"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("monthly_uploads_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_uploads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yookassa_payment_id", sa.String(length=128), nullable=True),
        sa.Column("yookassa_payment_method", sa.String(length=64), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=128), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=128), nullable=True),
        sa.Column("payment_provider", sa.String(length=32), nullable=False, server_default="freemium"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index(
        "ix_subscriptions_stripe_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
        unique=True,
        postgresql_where=sa.text("stripe_customer_id IS NOT NULL"),
    )
    op.create_index(
        "ix_subscriptions_stripe_subscription_id",
        "subscriptions",
        ["stripe_subscription_id"],
        unique=True,
        postgresql_where=sa.text("stripe_subscription_id IS NOT NULL"),
    )

    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_method", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="yookassa"),
        sa.Column("stripe_payment_intent_id", sa.String(length=128), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_provider", "payments", ["provider"])
    op.create_index("ix_payments_stripe_payment_intent_id", "payments", ["stripe_payment_intent_id"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("subscriptions")
