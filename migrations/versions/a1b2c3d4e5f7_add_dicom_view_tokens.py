"""add dicom_view_tokens table

Revision ID: a1b2c3d4e5f7
Revises: 43641187ffc2
Create Date: 2026-04-12 22:00:00.000000

Добавляет таблицу dicom_view_tokens для DICOM Viewer.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] = '43641187ffc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dicom_view_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('token', sa.String(36), unique=True, nullable=False),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('files.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_dicom_view_tokens_token', 'dicom_view_tokens', ['token'])
    op.create_index('ix_dicom_view_tokens_file_id', 'dicom_view_tokens', ['file_id'])


def downgrade() -> None:
    op.drop_index('ix_dicom_view_tokens_file_id', table_name='dicom_view_tokens')
    op.drop_index('ix_dicom_view_tokens_token', table_name='dicom_view_tokens')
    op.drop_table('dicom_view_tokens')
