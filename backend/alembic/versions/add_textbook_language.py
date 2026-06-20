"""add_textbook_language

Revision ID: add_textbook_language
Revises: add_system_config_tables
Create Date: 2026-06-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_textbook_language"
down_revision: Union[str, None] = "add_system_config_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "textbooks",
        sa.Column("language", sa.String(length=10), nullable=False, server_default="vi"),
    )
    op.create_index("ix_textbooks_language", "textbooks", ["language"], unique=False)
    op.alter_column("textbooks", "language", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_textbooks_language", table_name="textbooks")
    op.drop_column("textbooks", "language")
