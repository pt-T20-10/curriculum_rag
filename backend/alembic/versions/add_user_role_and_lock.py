"""add role and lock fields to users

Revision ID: add_user_role_and_lock
Revises: add_current_tracking
Create Date: 2026-05-06 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_user_role_and_lock'
down_revision: Union[str, None] = 'add_current_tracking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users',
        sa.Column('role', sa.String(20), nullable=False, server_default='user'))
    op.add_column('users',
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users',
        sa.Column('locked_at', sa.DateTime(), nullable=True))
    op.add_column('users',
        sa.Column('locked_by', sa.Integer(), nullable=True))
    op.create_index('ix_users_role', 'users', ['role'])


def downgrade() -> None:
    op.drop_index('ix_users_role', table_name='users')
    op.drop_column('users', 'locked_by')
    op.drop_column('users', 'locked_at')
    op.drop_column('users', 'is_locked')
    op.drop_column('users', 'role')
