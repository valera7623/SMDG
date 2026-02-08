"""add otp_secret field to user (already added manually)

Revision ID: otp_secret_added
Revises: fa73cd88b6d0
Create Date: 2026-01-19 10:20:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'otp_secret_added'
down_revision: Union[str, Sequence[str], None] = 'fa73cd88b6d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Поле уже добавлено вручную, НИЧЕГО не делаем
    # НЕ ВЫПОЛНЯЕМ: op.add_column('users', sa.Column('otp_secret', sa.Text(), nullable=True))
    pass


def downgrade() -> None:
    # При откате удалить поле
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('otp_secret')
