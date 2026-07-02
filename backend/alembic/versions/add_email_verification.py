"""add email verification columns

Revision ID: add_email_verification
Revises: repair_invalid_pdf_artifacts
Create Date: 2026-07-02 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_email_verification"
down_revision: Union[str, None] = "repair_invalid_pdf_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verification_code", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("email_verification_expires", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE users SET is_verified = 1 "
        "WHERE auth_provider = 'local' AND is_verified = 0"
    )


def downgrade() -> None:
    op.drop_column("users", "email_verification_expires")
    op.drop_column("users", "email_verification_code")
