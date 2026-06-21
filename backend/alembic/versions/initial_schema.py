"""Create the schema that predates the recorded incremental migrations.

Revision ID: initial_schema
Revises:
Create Date: 2026-06-21

The project originally created these tables through SQLAlchemy ``create_all``.
Later Alembic revisions therefore started by altering existing tables.  This
baseline makes a fresh production database migratable without changing the
upgrade path of databases already stamped at a later revision.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {name for name in ("users", "textbooks", "payments") if inspector.has_table(name)}
    if existing:
        names = ", ".join(sorted(existing))
        raise RuntimeError(
            "Cannot apply the initial Alembic baseline over existing tables "
            f"({names}). Back up the database and stamp the matching revision first."
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("auth_provider", sa.String(length=20), nullable=False),
        sa.Column("google_id", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)

    op.create_table(
        "textbooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("num_chapters", sa.Integer(), nullable=False),
        sa.Column("min_words_per_section", sa.Integer(), nullable=False),
        sa.Column("enable_images", sa.Boolean(), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("pdf_path", sa.String(length=1000), nullable=True),
        sa.Column("docx_path", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("credits_used", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_textbooks_id", "textbooks", ["id"], unique=False)
    op.create_index("ix_textbooks_user_id", "textbooks", ["user_id"], unique=False)
    op.create_index("idx_textbooks_content_type", "textbooks", ["content_type"], unique=False)

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sepay_transaction_id", sa.String(length=255), nullable=True),
        sa.Column("transfer_content", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_id", "payments", ["id"], unique=False)
    op.create_index("ix_payments_user_id", "payments", ["user_id"], unique=False)
    op.create_index("ix_payments_sepay_transaction_id", "payments", ["sepay_transaction_id"], unique=True)
    op.create_index("ix_payments_transfer_content", "payments", ["transfer_content"], unique=False)


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("textbooks")
    op.drop_table("users")
