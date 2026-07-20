"""Small idempotent schema repairs for deployments upgraded without SQL init."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import engine
from app.utils.log_config import setup_logger


logger = setup_logger(name="SchemaCompat", logfile="logs/schema_compat.log")


async def _textbooks_columns(conn: AsyncConnection) -> set[str] | None:
    table_exists = await conn.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = 'textbooks'
            """
        )
    )
    if not table_exists:
        return None

    result = await conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'textbooks'
            """
        )
    )
    return {str(row[0]) for row in result}


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
