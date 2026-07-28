"""Small idempotent schema repairs for deployments upgraded without SQL init."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import engine
from app.utils.log_config import setup_logger


logger = setup_logger(name="SchemaCompat", logfile="logs/schema_compat.log")


@dataclass(frozen=True)
class ColumnRepair:
    name: str
    ddl: str
    backfill_sql: tuple[str, ...] = ()


TEXTBOOK_COLUMN_REPAIRS: tuple[ColumnRepair, ...] = (
    ColumnRepair(
        "content_level",
        "ALTER TABLE textbooks ADD COLUMN content_level VARCHAR(50) NOT NULL DEFAULT 'Trung Bình'",
    ),
    ColumnRepair(
        "max_subsections_per_chapter",
        "ALTER TABLE textbooks ADD COLUMN max_subsections_per_chapter INT NOT NULL DEFAULT 3",
    ),
    ColumnRepair(
        "core_topic",
        "ALTER TABLE textbooks ADD COLUMN core_topic VARCHAR(500) NULL",
        (
            "UPDATE textbooks SET core_topic = topic WHERE core_topic IS NULL",
        ),
    ),
    ColumnRepair(
        "user_requirements",
        "ALTER TABLE textbooks ADD COLUMN user_requirements TEXT NULL",
    ),
    ColumnRepair(
        "curriculum_json",
        "ALTER TABLE textbooks ADD COLUMN curriculum_json JSON NULL",
    ),
    ColumnRepair(
        "total_chapters",
        "ALTER TABLE textbooks ADD COLUMN total_chapters INT NULL DEFAULT 0",
    ),
    ColumnRepair(
        "total_subsections",
        "ALTER TABLE textbooks ADD COLUMN total_subsections INT NULL DEFAULT 0",
    ),
    ColumnRepair(
        "current_chapter",
        "ALTER TABLE textbooks ADD COLUMN current_chapter INT NULL DEFAULT 0",
    ),
    ColumnRepair(
        "current_subsection",
        "ALTER TABLE textbooks ADD COLUMN current_subsection INT NULL DEFAULT 0",
    ),
    ColumnRepair(
        "language",
        "ALTER TABLE textbooks ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'vi'",
    ),
    ColumnRepair(
        "textbook_mode",
        "ALTER TABLE textbooks ADD COLUMN textbook_mode VARCHAR(20) NOT NULL DEFAULT 'standard'",
    ),
    ColumnRepair(
        "source_preferences",
        "ALTER TABLE textbooks ADD COLUMN source_preferences JSON NULL",
    ),
    ColumnRepair(
        "formula_policy",
        "ALTER TABLE textbooks ADD COLUMN formula_policy VARCHAR(20) NOT NULL DEFAULT 'auto'",
    ),
    ColumnRepair(
        "formula_need",
        "ALTER TABLE textbooks ADD COLUMN formula_need VARCHAR(20) NOT NULL DEFAULT 'none'",
    ),
    ColumnRepair(
        "structure_depth",
        "ALTER TABLE textbooks ADD COLUMN structure_depth VARCHAR(20) NOT NULL DEFAULT 'level1'",
    ),
    ColumnRepair(
        "max_child_subsections_per_section",
        "ALTER TABLE textbooks ADD COLUMN max_child_subsections_per_section INT NOT NULL DEFAULT 3",
    ),
    ColumnRepair(
        "source_materials",
        "ALTER TABLE textbooks ADD COLUMN source_materials JSON NULL",
    ),
)


USER_COLUMN_REPAIRS: tuple[ColumnRepair, ...] = (
    ColumnRepair(
        "username",
        "ALTER TABLE users ADD COLUMN username VARCHAR(50) NULL",
    ),
    ColumnRepair(
        "role",
        "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'",
    ),
    ColumnRepair(
        "is_locked",
        "ALTER TABLE users ADD COLUMN is_locked TINYINT(1) NOT NULL DEFAULT 0",
    ),
    ColumnRepair(
        "locked_at",
        "ALTER TABLE users ADD COLUMN locked_at DATETIME NULL",
    ),
    ColumnRepair(
        "locked_by",
        "ALTER TABLE users ADD COLUMN locked_by INT NULL",
    ),
    ColumnRepair(
        "password_reset_code",
        "ALTER TABLE users ADD COLUMN password_reset_code VARCHAR(64) NULL",
    ),
    ColumnRepair(
        "password_reset_expires",
        "ALTER TABLE users ADD COLUMN password_reset_expires DATETIME NULL",
    ),
    ColumnRepair(
        "email_verification_code",
        "ALTER TABLE users ADD COLUMN email_verification_code VARCHAR(64) NULL",
    ),
    ColumnRepair(
        "email_verification_expires",
        "ALTER TABLE users ADD COLUMN email_verification_expires DATETIME NULL",
    ),
    ColumnRepair(
        "is_deleted",
        "ALTER TABLE users ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0",
    ),
)


async def _table_columns(conn: AsyncConnection, table_name: str) -> set[str] | None:
    table_exists = await conn.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    if not table_exists:
        return None

    result = await conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return {str(row[0]) for row in result}


async def _textbooks_columns(conn: AsyncConnection) -> set[str] | None:
    return await _table_columns(conn, "textbooks")


async def _users_columns(conn: AsyncConnection) -> set[str] | None:
    return await _table_columns(conn, "users")


async def ensure_database_schema_compat() -> dict[str, str]:
    """Add missing columns for databases upgraded without init SQL.

    This is intentionally narrower than Alembic: it does not rebuild tables or
    drop legacy columns. It only performs idempotent compatibility repairs that
    let another machine run the current app without replaying ``init.sql``.
    """
    async with engine.begin() as conn:
        return await _ensure_database_schema_compat_on_connection(conn)


async def ensure_textbook_schema_compat() -> dict[str, str]:
    """Backward-compatible alias for startup code/tests."""
    async with engine.begin() as conn:
        return await _ensure_textbook_schema_compat_on_connection(conn)


async def ensure_textbook_task_id_column() -> str:
    """Ensure ``textbooks.task_id`` exists without rerunning init SQL.

    Returns a short action label for startup logs:
    ``already_exists``, ``renamed``, ``added``, or ``missing_table``.
    """
    async with engine.begin() as conn:
        return await _ensure_textbook_task_id_column_on_connection(conn)


async def _ensure_textbook_task_id_column_on_connection(conn: AsyncConnection) -> str:
    columns = await _textbooks_columns(conn)
    if columns is None:
        return "missing_table"

    has_task_id = "task_id" in columns
    has_legacy_task_id = "celery_task_id" in columns

    if has_task_id:
        if has_legacy_task_id:
            await conn.execute(
                text(
                    """
                    UPDATE textbooks
                    SET task_id = COALESCE(task_id, celery_task_id)
                    WHERE task_id IS NULL
                      AND celery_task_id IS NOT NULL
                    """
                )
            )
            logger.info("textbooks.task_id already exists; copied any legacy values")
        return "already_exists"

    if has_legacy_task_id:
        await conn.execute(
            text(
                """
                ALTER TABLE textbooks
                CHANGE COLUMN celery_task_id task_id VARCHAR(200) NULL
                """
            )
        )
        logger.info("Renamed textbooks.celery_task_id to textbooks.task_id")
        return "renamed"

    await conn.execute(text("ALTER TABLE textbooks ADD COLUMN task_id VARCHAR(200) NULL"))
    logger.info("Added missing textbooks.task_id column")
    return "added"


async def _ensure_textbook_schema_compat_on_connection(conn: AsyncConnection) -> dict[str, str]:
    columns = await _textbooks_columns(conn)
    if columns is None:
        return {"textbooks": "missing_table"}

    actions: dict[str, str] = {}
    task_action = await _ensure_textbook_task_id_column_on_connection(conn)
    actions["task_id"] = task_action

    columns = await _textbooks_columns(conn)
    if columns is None:
        return {"textbooks": "missing_table"}

    for repair in TEXTBOOK_COLUMN_REPAIRS:
        if repair.name in columns:
            actions[repair.name] = "already_exists"
            continue

        actions[repair.name] = await _add_missing_textbook_column(conn, repair)
        if actions[repair.name] == "added":
            columns.add(repair.name)

    added = sorted(name for name, action in actions.items() if action in {"added", "renamed"})
    if added:
        logger.info("Applied textbook schema compatibility repairs: %s", ", ".join(added))
    return actions


async def _ensure_database_schema_compat_on_connection(conn: AsyncConnection) -> dict[str, str]:
    actions: dict[str, str] = {}
    textbook_actions = await _ensure_textbook_schema_compat_on_connection(conn)
    actions.update(_prefix_table_actions("textbooks", textbook_actions))

    user_actions = await _ensure_user_schema_compat_on_connection(conn)
    actions.update(_prefix_table_actions("users", user_actions))

    return actions


def _prefix_table_actions(table_name: str, actions: dict[str, str]) -> dict[str, str]:
    return {
        key if key == table_name else f"{table_name}.{key}": action
        for key, action in actions.items()
    }


async def _ensure_user_schema_compat_on_connection(conn: AsyncConnection) -> dict[str, str]:
    columns = await _users_columns(conn)
    if columns is None:
        return {"users": "missing_table"}

    actions: dict[str, str] = {}
    for repair in USER_COLUMN_REPAIRS:
        if repair.name in columns:
            actions[repair.name] = "already_exists"
            continue

        actions[repair.name] = await _add_missing_table_column(conn, "users", repair)
        if actions[repair.name] == "added":
            columns.add(repair.name)

    added = sorted(name for name, action in actions.items() if action == "added")
    if added:
        logger.info("Applied user schema compatibility repairs: %s", ", ".join(added))
    return actions


async def _add_missing_textbook_column(conn: AsyncConnection, repair: ColumnRepair) -> str:
    return await _add_missing_table_column(conn, "textbooks", repair)


async def _add_missing_table_column(
    conn: AsyncConnection,
    table_name: str,
    repair: ColumnRepair,
) -> str:
    try:
        await conn.execute(text(repair.ddl))
        for sql in repair.backfill_sql:
            await conn.execute(text(sql))
        logger.info("Added missing %s.%s column", table_name, repair.name)
        return "added"
    except SQLAlchemyError as exc:
        columns = await _table_columns(conn, table_name)
        if columns is not None and repair.name in columns:
            logger.info(
                "%s.%s appeared while applying schema compatibility repair",
                table_name,
                repair.name,
            )
            return "already_exists"
        logger.error("Could not add missing %s.%s column: %s", table_name, repair.name, exc)
        raise
