"""add_core_topic_and_user_requirements

Revision ID: 45665cd98e48
Revises: a3895665ca3f
Create Date: 2026-04-30 11:00:58.197636

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45665cd98e48'
down_revision: Union[str, None] = 'a3895665ca3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('textbooks', sa.Column('core_topic', sa.String(length=500), nullable=True))
    op.add_column('textbooks', sa.Column('user_requirements', sa.String(length=500), nullable=True))
    
    # Backfill existing records
    op.execute("UPDATE textbooks SET core_topic = topic WHERE core_topic IS NULL")
    op.execute("UPDATE textbooks SET user_requirements = '' WHERE user_requirements IS NULL")


def downgrade() -> None:
    op.drop_column('textbooks', 'user_requirements')
    op.drop_column('textbooks', 'core_topic')
