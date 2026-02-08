# migrations/versions/add_medical_fields.py
"""add medical fields

Revision ID: add_medical_fields
Revises: otp_secret_added
Create Date: 2026-01-19 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'add_medical_fields'
down_revision: Union[str, Sequence[str], None] = 'otp_secret_added'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавить email к таблице users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)
    
    # 2. Добавить медицинские поля к таблице files
    with op.batch_alter_table('files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('patient_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('metadata', JSONB(), nullable=True))
        batch_op.create_index(batch_op.f('ix_files_patient_id'), ['patient_id'], unique=False)


def downgrade() -> None:
    # 1. Удалить медицинские поля из files
    with op.batch_alter_table('files', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_files_patient_id'))
        batch_op.drop_column('metadata')
        batch_op.drop_column('patient_id')
    
    # 2. Удалить email из users
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))
        batch_op.drop_column('email')