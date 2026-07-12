"""add textbook mode

Revision ID: add_textbook_mode
Revises: add_email_verification
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_textbook_mode"
down_revision: Union[str, None] = "add_email_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "textbooks",
        sa.Column(
            "textbook_mode",
            sa.String(length=20),
            nullable=False,
            server_default="standard",
        ),
    )
    op.create_index(
        "ix_textbooks_textbook_mode",
        "textbooks",
        ["textbook_mode"],
        unique=False,
    )
    op.execute("UPDATE textbooks SET textbook_mode = 'standard' WHERE textbook_mode IS NULL")


def downgrade() -> None:
    op.drop_index("ix_textbooks_textbook_mode", table_name="textbooks")
    op.drop_column("textbooks", "textbook_mode")
