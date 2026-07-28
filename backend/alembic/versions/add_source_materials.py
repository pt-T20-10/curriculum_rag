"""add source materials manifest

Revision ID: add_source_materials
Revises: rename_textbook_task_id
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_source_materials"
down_revision: Union[str, None] = "rename_textbook_task_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("textbooks", sa.Column("source_materials", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("textbooks", "source_materials")
