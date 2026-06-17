"""add system config tables

Revision ID: add_system_config_tables
Revises: add_username
Create Date: 2026-06-16 00:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = "add_system_config_tables"
down_revision: Union[str, None] = "add_username"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system_config (
            id INT NOT NULL AUTO_INCREMENT,
            `key` VARCHAR(100) NOT NULL,
            value TEXT NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            updated_by INT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uq_system_config_key (`key`),
            KEY ix_system_config_key (`key`),
            KEY ix_system_config_updated_by (updated_by),
            CONSTRAINT fk_system_config_updated_by_users
                FOREIGN KEY (updated_by) REFERENCES users (id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_config (
            id INT NOT NULL AUTO_INCREMENT,
            user_id INT NOT NULL,
            `key` VARCHAR(100) NOT NULL,
            value TEXT NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_user_config_user_key (user_id, `key`),
            KEY ix_user_config_user_id (user_id),
            KEY ix_user_config_key (`key`),
            CONSTRAINT fk_user_config_user_id_users
                FOREIGN KEY (user_id) REFERENCES users (id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS config_audit_log (
            id INT NOT NULL AUTO_INCREMENT,
            admin_id INT NULL,
            `key` VARCHAR(100) NOT NULL,
            old_value TEXT NULL,
            new_value TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY ix_config_audit_log_admin_id (admin_id),
            KEY ix_config_audit_log_key (`key`),
            CONSTRAINT fk_config_audit_log_admin_id_users
                FOREIGN KEY (admin_id) REFERENCES users (id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS config_audit_log")
    op.execute("DROP TABLE IF EXISTS user_config")
    op.execute("DROP TABLE IF EXISTS system_config")
