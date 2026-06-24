from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = Path(__file__).parent / "alembic" / "versions" / "repair_invalid_pdf_artifacts.py"
    spec = importlib.util.spec_from_file_location("repair_invalid_pdf_artifacts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_repairs_only_non_pdf_paths(monkeypatch) -> None:
    migration = _load_migration()
    metadata = sa.MetaData()
    textbooks = sa.Table(
        "textbooks",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pdf_path", sa.String),
        sa.Column("docx_path", sa.String),
        sa.Column("status", sa.String),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("error_message", sa.Text),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(textbooks.insert(), [
            {
                "id": 1,
                "pdf_path": "/app/outputs/book.docx",
                "docx_path": "/app/outputs/book.docx",
                "status": "completed",
            },
            {
                "id": 2,
                "pdf_path": "/app/outputs/book.PDF",
                "docx_path": "/app/outputs/book.docx",
                "status": "completed",
            },
            {
                "id": 3,
                "pdf_path": None,
                "docx_path": None,
                "status": "pending",
            },
        ])
        monkeypatch.setattr(migration.op, "execute", connection.execute)
        migration.upgrade()
        rows = {
            row.id: row
            for row in connection.execute(sa.select(textbooks)).all()
        }

    assert rows[1].pdf_path is None
    assert rows[1].docx_path == "/app/outputs/book.docx"
    assert rows[1].status == "failed"
    assert "Legacy export repaired" in rows[1].error_message
    assert rows[2].pdf_path == "/app/outputs/book.PDF"
    assert rows[2].status == "completed"
    assert rows[3].status == "pending"

