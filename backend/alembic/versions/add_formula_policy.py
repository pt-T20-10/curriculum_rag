"""add formula policy metadata

Revision ID: add_formula_policy
Revises: add_source_preferences
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "add_formula_policy"
down_revision: Union[str, None] = "add_source_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "textbooks",
        "topic",
        existing_type=mysql.VARCHAR(length=500),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "textbooks",
        "user_requirements",
        existing_type=mysql.VARCHAR(length=1000),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.add_column(
        "textbooks",
        sa.Column(
            "formula_policy",
            sa.String(length=20),
            nullable=False,
            server_default="auto",
        ),
    )
    op.add_column(
        "textbooks",
        sa.Column(
            "formula_need",
            sa.String(length=20),
            nullable=False,
            server_default="none",
        ),
    )
    op.create_index("ix_textbooks_formula_policy", "textbooks", ["formula_policy"], unique=False)
    op.create_index("ix_textbooks_formula_need", "textbooks", ["formula_need"], unique=False)
    op.alter_column("textbooks", "formula_policy", server_default=None)
    op.alter_column("textbooks", "formula_need", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_textbooks_formula_need", table_name="textbooks")
    op.drop_index("ix_textbooks_formula_policy", table_name="textbooks")
    op.drop_column("textbooks", "formula_need")
    op.drop_column("textbooks", "formula_policy")
    op.alter_column(
        "textbooks",
        "user_requirements",
        existing_type=sa.Text(),
        type_=mysql.VARCHAR(length=1000),
        existing_nullable=True,
    )
    op.alter_column(
        "textbooks",
        "topic",
        existing_type=sa.Text(),
        type_=mysql.VARCHAR(length=500),
        existing_nullable=False,
    )
