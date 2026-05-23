"""drop payments table

Revision ID: drop_payments_table
Revises: add_plans_transactions_credits
Create Date: 2026-05-23 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'drop_payments_table'
down_revision: Union[str, None] = 'add_plans_transactions_credits'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('payments')


def downgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('credits', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('sepay_transaction_id', sa.String(255), unique=True, nullable=True),
        sa.Column('transfer_content', sa.String(500), nullable=True, index=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
