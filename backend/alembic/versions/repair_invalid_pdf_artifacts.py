"""repair invalid PDF artifact paths

Revision ID: repair_invalid_pdf_artifacts
Revises: add_user_soft_delete
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "repair_invalid_pdf_artifacts"
down_revision: Union[str, None] = "add_user_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REPAIR_MESSAGE = (
    "Legacy export repaired: pdf_path did not reference a PDF. "
    "The available DOCX artifact was preserved."
)


def upgrade() -> None:
    textbooks = sa.table(
        "textbooks",
        sa.column("pdf_path", sa.String()),
        sa.column("status", sa.String()),
        sa.column("completed_at", sa.DateTime()),
        sa.column("error_message", sa.Text()),
    )
    invalid_pdf = sa.and_(
        textbooks.c.pdf_path.is_not(None),
        textbooks.c.pdf_path != "",
        sa.not_(sa.func.lower(textbooks.c.pdf_path).like("%.pdf")),
    )
    op.execute(
        textbooks.update()
        .where(invalid_pdf)
        .values(
            pdf_path=None,
            status="failed",
            completed_at=None,
            error_message=_REPAIR_MESSAGE,
        )
    )


def downgrade() -> None:
    # The former pdf_path was not a PDF and restoring it would recreate the
    # corruption. DOCX paths and files are deliberately left untouched.
    pass

