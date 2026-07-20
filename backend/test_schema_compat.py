from __future__ import annotations

import pytest

from app.services.schema_compat import _ensure_textbook_task_id_column_on_connection

pytestmark = pytest.mark.asyncio


class _FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def __iter__(self):
        return iter((value,) for value in self._values)


class _FakeConnection:
    def __init__(self, columns=None, table_exists=True):
        self.columns = set(columns or [])
        self.table_exists = table_exists
        self.statements: list[str] = []

    async def scalar(self, statement):
        self.statements.append(str(statement))
        return 1 if self.table_exists else 0

    async def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "information_schema.columns" in sql:
            return _FakeScalarResult(sorted(self.columns))
        if "CHANGE COLUMN celery_task_id task_id" in sql:
            self.columns.discard("celery_task_id")
            self.columns.add("task_id")
        if "ADD COLUMN task_id" in sql:
            self.columns.add("task_id")
        return _FakeScalarResult([])


async def test_schema_compat_renames_legacy_task_column() -> None:
    conn = _FakeConnection(columns={"id", "celery_task_id"})

    action = await _ensure_textbook_task_id_column_on_connection(conn)

    assert action == "renamed"
    assert "task_id" in conn.columns
    assert "celery_task_id" not in conn.columns


async def test_schema_compat_adds_missing_task_column() -> None:
    conn = _FakeConnection(columns={"id", "title"})

    action = await _ensure_textbook_task_id_column_on_connection(conn)

    assert action == "added"
    assert "task_id" in conn.columns


async def test_schema_compat_leaves_existing_task_column() -> None:
    conn = _FakeConnection(columns={"id", "task_id"})

    action = await _ensure_textbook_task_id_column_on_connection(conn)

    assert action == "already_exists"
    assert not any("ALTER TABLE" in statement for statement in conn.statements)


async def test_schema_compat_skips_missing_textbooks_table() -> None:
    conn = _FakeConnection(table_exists=False)

    action = await _ensure_textbook_task_id_column_on_connection(conn)

    assert action == "missing_table"
