"""update_textbook_config_fields

Revision ID: a3895665ca3f
Revises: 1353ebcf0cd0
Create Date: 2026-04-29 20:11:36.708930

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3895665ca3f'
down_revision: Union[str, None] = '1353ebcf0cd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('textbooks', sa.Column('content_level', sa.String(50), nullable=True))
    op.add_column('textbooks', sa.Column('max_subsections_per_chapter', sa.Integer(), nullable=True))

    op.execute("UPDATE textbooks SET content_level = 'Trung Bình' WHERE content_level IS NULL")
    op.execute("UPDATE textbooks SET max_subsections_per_chapter = 3 WHERE max_subsections_per_chapter IS NULL")

    op.drop_column('textbooks', 'min_words_per_section')


def downgrade() -> None:
    op.add_column('textbooks', sa.Column('min_words_per_section', sa.Integer(), nullable=True))
    op.execute("UPDATE textbooks SET min_words_per_section = 500 WHERE min_words_per_section IS NULL")

    op.drop_column('textbooks', 'max_subsections_per_chapter')
    op.drop_column('textbooks', 'content_level')
