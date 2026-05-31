"""Add users.otp_confirmed flag

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-06-01

2FA должна считаться включённой только после подтверждения кода. Ранее
``/setup-2fa`` сохранял ``otp_secret`` сразу, и незавершённая настройка
блокировала вход формой ввода кода. Колонка ``otp_confirmed`` разделяет
"секрет сгенерирован" и "2FA реально включена".

Бэкофилл: существующие пользователи с ``otp_secret`` считаются уже
подтверждёнными, чтобы не заблокировать работающую 2FA.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "otp_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Existing users with a configured secret are assumed to have working 2FA.
    op.execute(
        "UPDATE users SET otp_confirmed = true WHERE otp_secret IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "otp_confirmed")
