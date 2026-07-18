"""add structure depth fields

Revision ID: add_structure_depth
Revises: add_formula_policy
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_structure_depth"
down_revision: Union[str, None] = "add_formula_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "textbooks",
        sa.Column("structure_depth", sa.String(length=20), nullable=False, server_default="level1"),
    )
    op.add_column(
        "textbooks",
        sa.Column("max_child_subsections_per_section", sa.Integer(), nullable=False, server_default="3"),
    )
    op.create_index("ix_textbooks_structure_depth", "textbooks", ["structure_depth"])


def downgrade() -> None:
    op.drop_index("ix_textbooks_structure_depth", table_name="textbooks")
    op.drop_column("textbooks", "max_child_subsections_per_section")
    op.drop_column("textbooks", "structure_depth")
