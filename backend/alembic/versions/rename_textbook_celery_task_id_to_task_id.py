"""rename textbook celery_task_id to task_id

Revision ID: rename_textbook_task_id
Revises: set_byok_default
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "rename_textbook_task_id"
down_revision: Union[str, None] = "set_byok_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "textbooks",
        "celery_task_id",
        new_column_name="task_id",
        existing_type=sa.String(length=200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "textbooks",
        "task_id",
        new_column_name="celery_task_id",
        existing_type=sa.String(length=200),
        existing_nullable=True,
    )
