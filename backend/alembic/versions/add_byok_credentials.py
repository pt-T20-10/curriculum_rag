"""add byok credential tables

Revision ID: add_byok_credentials
Revises: add_structure_depth
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_byok_credentials"
down_revision: Union[str, None] = "add_structure_depth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_api_credentials" not in tables:
        op.create_table(
            "user_api_credentials",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("encrypted_value", sa.Text(), nullable=False),
            sa.Column("last4", sa.String(length=8), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "provider", name="uq_user_api_credentials_user_provider"),
        )

    if "textbook_job_secrets" not in tables:
        op.create_table(
            "textbook_job_secrets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("textbook_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("encrypted_value", sa.Text(), nullable=False),
            sa.Column("last4", sa.String(length=8), nullable=False, server_default=""),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["textbook_id"], ["textbooks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("textbook_id", "provider", name="uq_textbook_job_secrets_textbook_provider"),
        )

    indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in ("user_api_credentials", "textbook_job_secrets")
        if table in set(sa.inspect(bind).get_table_names())
    }
    if "ix_user_api_credentials_user_id" not in indexes.get("user_api_credentials", set()):
        op.create_index("ix_user_api_credentials_user_id", "user_api_credentials", ["user_id"])
    if "ix_user_api_credentials_provider" not in indexes.get("user_api_credentials", set()):
        op.create_index("ix_user_api_credentials_provider", "user_api_credentials", ["provider"])
    if "ix_textbook_job_secrets_textbook_id" not in indexes.get("textbook_job_secrets", set()):
        op.create_index("ix_textbook_job_secrets_textbook_id", "textbook_job_secrets", ["textbook_id"])
    if "ix_textbook_job_secrets_provider" not in indexes.get("textbook_job_secrets", set()):
        op.create_index("ix_textbook_job_secrets_provider", "textbook_job_secrets", ["provider"])
    if "ix_textbook_job_secrets_expires_at" not in indexes.get("textbook_job_secrets", set()):
        op.create_index("ix_textbook_job_secrets_expires_at", "textbook_job_secrets", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_textbook_job_secrets_expires_at", table_name="textbook_job_secrets")
    op.drop_index("ix_textbook_job_secrets_provider", table_name="textbook_job_secrets")
    op.drop_index("ix_textbook_job_secrets_textbook_id", table_name="textbook_job_secrets")
    op.drop_table("textbook_job_secrets")
    op.drop_index("ix_user_api_credentials_provider", table_name="user_api_credentials")
    op.drop_index("ix_user_api_credentials_user_id", table_name="user_api_credentials")
    op.drop_table("user_api_credentials")
