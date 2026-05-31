"""Add users.otp_confirmed flag

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-06-01

2FA должна считаться включённой только после подтверждения кода. Ранее
``/setup-2fa`` сохранял ``otp_secret`` сразу, и незавершённая настройка
блокировала вход формой ввода кода. Колонка ``otp_confirmed`` разделяет
"секрет сгенерирован" и "2FA реально включена".

Без бэкофилла: колонка добавляется со ``server_default = false``, поэтому
у всех существующих строк ``otp_confirmed = false``. Это безопасно по
умолчанию — незавершённые/унаследованные секреты не будут требовать код
при входе. Пользователи, желающие 2FA, проходят настройку заново; флаг
выставляется в ``true`` только после успешного подтверждения кода в
``/verify-2fa-setup``.

Намеренно НЕ помечаем существующие ``otp_secret`` как подтверждённые: в БД
невозможно отличить реально завершённую настройку от брошенной, а ложное
``true`` как раз и приводило к появлению формы 2FA там, где её не настраивали.
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
    # Намеренно без бэкофилла: все существующие строки получают
    # otp_confirmed = false (server_default). 2FA включается только после
    # подтверждения кода в /verify-2fa-setup.


def downgrade() -> None:
    op.drop_column("users", "otp_confirmed")
