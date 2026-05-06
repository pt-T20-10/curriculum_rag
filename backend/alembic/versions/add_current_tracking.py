"""add current chapter and subsection tracking

Revision ID: add_current_tracking
Revises: 084c96af4337
Create Date: 2026-05-05 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_current_tracking'
down_revision: Union[str, None] = '084c96af4337'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add current position tracking columns
    op.add_column('textbooks', 
        sa.Column('current_chapter', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('textbooks', 
        sa.Column('current_subsection', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('textbooks', 'current_subsection')
    op.drop_column('textbooks', 'current_chapter')