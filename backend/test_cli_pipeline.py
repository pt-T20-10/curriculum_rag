from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from app.cli import cli
from app.config import settings
from app.services import runtime_config
from app.services.textbook import automatic_runner
from app.services.textbook import ingester


VALIDATION = {
    "valid": True,
    "reason": "",
    "suggestion": "",
    "content_type": "technical",
    "core_topic": "Python",
    "user_requirements": "có bài tập",
    "target_language": "vi",
}


def _successful_result() -> dict:
    return {
        "success": True,
        "status": "completed",
        "query": "Python cơ bản",
        "validation": VALIDATION,
        "title": "Giáo trình Python",
        "language": "vi",
        "stats": {
            "chapter_count": 3,
            "subsection_count": 5,
            "word_count": 100,
            "character_count": 700,
            "image_count": 0,
            "elapsed_seconds": 1.25,
        },
        "artifacts": {"markdown": "book.md"},
        "error": None,
    }


def test_runner_passes_validator_output_and_generation_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    markdown = tmp_path / "book.md"
    pdf = tmp_path / "book.pdf"
    docx = tmp_path / "book.docx"
    markdown.write_text("# Python\n\nMột nội dung có ích.\n\n![Hình](figure.png)", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.7\n")
    docx.write_bytes(b"PK\x03\x04DOCX")
    captured = {}
    curriculum = SimpleNamespace(
        chapters=[
            SimpleNamespace(subsections=[SimpleNamespace(), SimpleNamespace()]),
            SimpleNamespace(subsections=[SimpleNamespace()]),
        ]
    )
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        ingester,
        "cleanup_rag_collection",
        lambda collection_name: cleanup_calls.append(collection_name) or True,
    )

    class Workflow:
        def stream(self, state, config):
            captured["state"] = state
            captured["config"] = config
            yield {"planner": {"curriculum": curriculum, "textbook_title": "Python thực hành"}}
            yield {"ingestion": {"messages": ["✓ Ingestion complete: Database ready with 2 sources"]}}
            yield {"publisher": {
                "final_filepath": str(pdf),
                "final_markdown_filepath": str(markdown),
                "final_pdf_filepath": str(pdf),
                "final_docx_filepath": str(docx),
            }}

    result = automatic_runner.run_automatic_textbook_workflow(
        query="  Python có bài tập  ",
        num_chapters=2,
        content_level="Dài",
        max_subsections_per_chapter=4,
        enable_images=True,
        _validator=lambda query, language: VALIDATION,
        _workflow_factory=Workflow,
    )

    assert result["success"] is True
    assert result["title"] == "Python thực hành"
    assert result["stats"]["chapter_count"] == 2
    assert result["stats"]["subsection_count"] == 3
    assert result["stats"]["image_count"] == 1
    assert result["artifacts"] == {
        "markdown": str(markdown.resolve()),
        "pdf": str(pdf.resolve()),
        "word": str(docx.resolve()),
    }
    assert captured["config"] == {
        "recursion_limit": settings.CONTENT_WORKFLOW_RECURSION_LIMIT
    }
    assert captured["state"]["request"] == "Python có bài tập"
    assert captured["state"]["core_topic"] == "Python"
    assert captured["state"]["user_requirements"] == "có bài tập"
    assert captured["state"]["content_level"] == "Dài"
    assert captured["state"]["enable_images"] is True
    assert captured["state"]["export_formats"] == ["PDF", "Word"]
    assert cleanup_calls == [captured["state"]["rag_collection_name"]]


def test_invalid_query_does_not_build_workflow() -> None:
    called = False

    def workflow_factory():
        nonlocal called
        called = True
        raise AssertionError("workflow must not be built")

    validation = {
        **VALIDATION,
        "valid": False,
        "reason": "Chủ đề quá chung chung",
        "suggestion": "Python cơ bản | Python cho sinh viên",
    }
    result = automatic_runner.run_automatic_textbook_workflow(
        query="Python",
        _validator=lambda query, language: validation,
        _workflow_factory=workflow_factory,
    )

    assert result["status"] == "invalid_query"
    assert result["validation"] == validation
    assert result["error"] == "Chủ đề quá chung chung"
    assert called is False


def test_runner_reports_ingestion_failure() -> None:
    class Workflow:
        def stream(self, state, config):
            yield {"planner": {"curriculum": SimpleNamespace(chapters=[])}}
            yield {"ingestion": {"messages": ["✗ Ingestion failed: No search results"]}}

    result = automatic_runner.run_automatic_textbook_workflow(
        query="Python cơ bản",
        _validator=lambda query, language: VALIDATION,
        _workflow_factory=Workflow,
    )

    assert result["success"] is False
    assert result["error"] == "Ingestion failed: No search results"


def test_runner_requires_markdown_artifact() -> None:
    class Workflow:
        def stream(self, state, config):
            yield {"planner": {"curriculum": SimpleNamespace(chapters=[])}}
            yield {"publisher": {"final_filepath": None}}

    result = automatic_runner.run_automatic_textbook_workflow(
        query="Python cơ bản",
        _validator=lambda query, language: VALIDATION,
        _workflow_factory=Workflow,
    )

    assert result["success"] is False
    assert "Markdown" in result["error"]


def test_runner_reports_terminal_insufficient_context_before_artifacts() -> None:
    class Workflow:
        def stream(self, state, config):
            yield {"planner": {"curriculum": SimpleNamespace(chapters=[])}}
            yield {"context_evaluator": {
                "context_quality": "insufficient",
                "current_chapter_index": 0,
                "current_subsection_index": 0,
                "rag_source_audit": {
                    "warnings": [
                        "Context did not meet strict RAG gate: chunks=1."
                    ],
                },
            }}

    result = automatic_runner.run_automatic_textbook_workflow(
        query="Python cơ bản",
        _validator=lambda query, language: VALIDATION,
        _workflow_factory=Workflow,
    )

    assert result["success"] is False
    assert "Insufficient RAG context for Chapter 1.1" in result["error"]
    assert "Markdown" not in result["error"]


def test_runner_requires_pdf_and_docx_exports(tmp_path: Path) -> None:
    markdown = tmp_path / "book.md"
    markdown.write_text("# Python", encoding="utf-8")

    class Workflow:
        def stream(self, state, config):
            yield {"planner": {"curriculum": SimpleNamespace(chapters=[])}}
            yield {"publisher": {"final_markdown_filepath": str(markdown)}}

    result = automatic_runner.run_automatic_textbook_workflow(
        query="Python cơ bản",
        _validator=lambda query, language: VALIDATION,
        _workflow_factory=Workflow,
    )

    assert result["success"] is False
    assert "PDF" in result["error"]
    assert "DOCX" in result["error"]


def test_runner_returns_workflow_exception() -> None:
    class Workflow:
        def stream(self, state, config):
            raise RuntimeError("planner exploded")
            yield  # pragma: no cover - keeps this function a generator

    result = automatic_runner.run_automatic_textbook_workflow(
        query="Python cơ bản",
        _validator=lambda query, language: VALIDATION,
        _workflow_factory=Workflow,
    )

    assert result["success"] is False
    assert result["status"] == "error"
    assert result["error"] == "planner exploded"


def test_environment_only_config_never_reads_database(monkeypatch) -> None:
    def fail_if_called(key):
        raise AssertionError(f"database lookup attempted for {key}")

    monkeypatch.setattr(runtime_config, "_read_db_value", fail_if_called)
    with runtime_config.environment_only_runtime_config():
        assert runtime_config.get_runtime_config("RAG_TOP_K") == settings.RAG_TOP_K


def test_cli_defaults_mapping_and_json(monkeypatch) -> None:
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _successful_result()

    monkeypatch.setattr(automatic_runner, "run_automatic_textbook_workflow", fake_run)
    result = CliRunner().invoke(cli, ["--query", "Python cơ bản", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "completed"
    assert captured["num_chapters"] == 3
    assert captured["content_level"] == "Trung Bình"
    assert captured["max_subsections_per_chapter"] == 5
    assert captured["enable_images"] is False
    assert captured["progress_callback"] is None


def test_cli_custom_options_and_ranges(monkeypatch) -> None:
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return _successful_result()

    monkeypatch.setattr(automatic_runner, "run_automatic_textbook_workflow", fake_run)
    result = CliRunner().invoke(
        cli,
        [
            "--query", "Python cơ bản",
            "--images",
            "--chapters", "12",
            "--length", "very-long",
            "--sections", "8",
        ],
    )

    assert result.exit_code == 0
    assert captured["enable_images"] is True
    assert captured["num_chapters"] == 12
    assert captured["content_level"] == "Rất Dài"
    assert captured["max_subsections_per_chapter"] == 8
    assert CliRunner().invoke(cli, ["--query", "x", "--chapters", "13"]).exit_code == 2
    assert CliRunner().invoke(cli, ["--query", "x", "--sections", "1"]).exit_code == 2


def test_cli_invalid_query_exit_code_and_json(monkeypatch) -> None:
    response = _successful_result()
    response.update({
        "success": False,
        "status": "invalid_query",
        "error": "Chủ đề quá chung chung",
        "validation": {**VALIDATION, "valid": False, "suggestion": "Python cơ bản"},
    })
    monkeypatch.setattr(
        automatic_runner,
        "run_automatic_textbook_workflow",
        lambda **kwargs: response,
    )

    result = CliRunner().invoke(cli, ["--query", "Python", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["validation"]["suggestion"] == "Python cơ bản"


def test_cli_keyboard_interrupt_uses_130(monkeypatch) -> None:
    def interrupted(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(automatic_runner, "run_automatic_textbook_workflow", interrupted)
    result = CliRunner().invoke(cli, ["--query", "Python cơ bản"])
    assert result.exit_code == 130
