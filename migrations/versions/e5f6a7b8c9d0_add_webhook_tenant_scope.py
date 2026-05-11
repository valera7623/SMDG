"""Add tenant scope to webhook subscriptions

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_subscriptions", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_webhook_subscriptions_tenant_id_tenants",
        "webhook_subscriptions",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE webhook_subscriptions AS ws
        SET tenant_id = u.tenant_id
        FROM users AS u
        WHERE ws.user_id = u.id
          AND ws.tenant_id IS NULL
        """
    )
    op.create_index(
        "ix_webhook_subscriptions_tenant_id",
        "webhook_subscriptions",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_subscriptions_tenant_id", table_name="webhook_subscriptions")
    op.drop_constraint(
        "fk_webhook_subscriptions_tenant_id_tenants",
        "webhook_subscriptions",
        type_="foreignkey",
    )
    op.drop_column("webhook_subscriptions", "tenant_id")
