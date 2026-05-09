"""add password reset columns to users

Revision ID: add_password_reset
Revises: add_user_role_and_lock
Create Date: 2026-05-09 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_password_reset'
down_revision: Union[str, None] = 'add_user_role_and_lock'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users',
        sa.Column('password_reset_code', sa.String(64), nullable=True))
    op.add_column('users',
        sa.Column('password_reset_expires', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'password_reset_expires')
    op.drop_column('users', 'password_reset_code')
