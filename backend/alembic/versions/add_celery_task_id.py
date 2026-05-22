"""add celery_task_id to textbooks

Revision ID: add_celery_task_id
Revises: add_password_reset
Create Date: 2026-05-22 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_celery_task_id'
down_revision: Union[str, None] = 'add_password_reset'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('textbooks',
        sa.Column('celery_task_id', sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column('textbooks', 'celery_task_id')
