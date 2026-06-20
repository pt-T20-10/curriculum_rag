"""add site contact config

Revision ID: add_site_contact_config
Revises: add_textbook_language
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_site_contact_config"
down_revision: Union[str, None] = "add_textbook_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The application currently calls Base.metadata.create_all() at startup.
    # A development server with reload may therefore create this table before
    # Alembic records the revision. Preserve that compatible empty/existing
    # table and let Alembic advance normally.
    if sa.inspect(op.get_bind()).has_table("site_contact_config"):
        return

    op.create_table(
        "site_contact_config",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("service_name_vi", sa.String(length=200), nullable=False),
        sa.Column("service_name_en", sa.String(length=200), nullable=False),
        sa.Column("operator_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("address_vi", sa.Text(), nullable=False),
        sa.Column("address_en", sa.Text(), nullable=False),
        sa.Column("support_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("privacy_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("support_hours_vi", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("support_hours_en", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("response_time_vi", sa.Text(), nullable=False),
        sa.Column("response_time_en", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_site_contact_config_updated_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_site_contact_config_updated_by",
        "site_contact_config",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_site_contact_config_updated_by", table_name="site_contact_config")
    op.drop_table("site_contact_config")
