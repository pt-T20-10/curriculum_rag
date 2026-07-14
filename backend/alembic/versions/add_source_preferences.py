"""add source preferences to textbooks

Revision ID: add_source_preferences
Revises: add_textbook_mode
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_source_preferences"
down_revision: Union[str, None] = "add_textbook_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("textbooks", sa.Column("source_preferences", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("textbooks", "source_preferences")

