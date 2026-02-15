"""initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-02-15 14:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаём таблицу users
    op.create_table('users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=30), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('otp_secret', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email')
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=False)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Создаём таблицу files
    op.create_table('files',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('encrypted_name', sa.String(length=255), nullable=False),
        sa.Column('encrypted_path', sa.String(length=512), nullable=False),
        sa.Column('original_size', sa.Integer(), nullable=False),
        sa.Column('encrypted_size', sa.Integer(), nullable=False),
        sa.Column('original_hash', sa.String(length=128), nullable=True),
        sa.Column('mime_type', sa.String(length=100), nullable=True),
        sa.Column('patient_id', sa.String(length=100), nullable=True),
        sa.Column('medical_metadata', JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_files_encrypted_name', 'files', ['encrypted_name'], unique=False)
    op.create_index('ix_files_patient_id', 'files', ['patient_id'], unique=False)

    # Создаём таблицу file_links
    op.create_table('file_links',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('token', sa.String(length=36), nullable=False),
        sa.Column('file_id', sa.Integer(), nullable=False),
        sa.Column('max_downloads', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('downloads_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['files.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )
    op.create_index('ix_file_links_token', 'file_links', ['token'], unique=True)


def downgrade() -> None:
    op.drop_table('file_links')
    op.drop_table('files')
    op.drop_table('users')