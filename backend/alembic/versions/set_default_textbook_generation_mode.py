"""set default textbook generation mode to user-provided api keys

Revision ID: set_byok_default
Revises: add_byok_credentials
Create Date: 2026-07-18 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "set_byok_default"
down_revision: Union[str, None] = "add_byok_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO system_config (`key`, `value`, `updated_by`)
        VALUES ('TEXTBOOK_GENERATION_MODE', '"user_provided_api_keys"', NULL)
        ON DUPLICATE KEY UPDATE
            `value` = CASE
                WHEN `value` IN ('"system_credit_billing"', 'system_credit_billing', '', 'null')
                THEN '"user_provided_api_keys"'
                ELSE `value`
            END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE system_config
        SET `value` = '"system_credit_billing"'
        WHERE `key` = 'TEXTBOOK_GENERATION_MODE'
          AND `value` = '"user_provided_api_keys"'
        """
    )
