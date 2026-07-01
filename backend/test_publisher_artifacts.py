from __future__ import annotations

from pathlib import Path
import asyncio
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.services.textbook import publisher
from app.services.textbook import orchestrator, workflow_runner


def _state(title: str = "Lập trình C# Cơ bản") -> dict:
    return {
        "request": title,
        "textbook_title": title,
        "final_content": "# CHƯƠNG 1: MỞ ĐẦU\n\nNội dung kiểm thử.",
        "current_content": "",
        "preface_content": "",
        "enable_images": False,
        "language": "vi",
        "export_formats": ["PDF", "Word"],
    }


def _fake_pandoc(*, fail_pdf: bool, fail_docx: bool):
    def convert_file(source, *, to, outputfile, extra_args):
        if to == "pdf" and fail_pdf:
            raise RuntimeError("synthetic PDF failure")
        if to == "docx" and fail_docx:
            raise RuntimeError("synthetic DOCX failure")
        payload = b"%PDF-1.7\n" if to == "pdf" else b"PK\x03\x04DOCX"
        Path(outputfile).write_bytes(payload)
        return ""

    return SimpleNamespace(convert_file=convert_file)


@pytest.mark.parametrize(
    ("fail_pdf", "fail_docx", "has_pdf", "has_docx"),
    [
        (False, False, True, True),
        (True, False, False, True),
        (False, True, True, False),
        (True, True, False, False),
    ],
)
def test_publisher_keeps_export_artifacts_distinct(
    tmp_path: Path,
    monkeypatch,
    fail_pdf: bool,
    fail_docx: bool,
    has_pdf: bool,
    has_docx: bool,
) -> None:
    monkeypatch.setattr(publisher, "BASE_DIR", tmp_path)
    monkeypatch.setattr(publisher, "image_dir", tmp_path / "outputs" / "images")
    monkeypatch.setattr(
        publisher,
        "pypandoc",
        _fake_pandoc(fail_pdf=fail_pdf, fail_docx=fail_docx),
    )
    monkeypatch.setattr(publisher, "_get_word_reference_doc", lambda path: None)

    result = publisher.publish_curriculum(_state())

    assert bool(result["final_pdf_filepath"]) is has_pdf
    assert bool(result["final_docx_filepath"]) is has_docx
    assert result["final_filepath"] == result["final_pdf_filepath"]
    assert result["final_markdown_filepath"].endswith(".md")
    if result["final_pdf_filepath"]:
        assert result["final_pdf_filepath"].endswith(".pdf")
    if result["final_docx_filepath"]:
        assert result["final_docx_filepath"].endswith(".docx")
    assert ("pdf" in result["export_errors"]) is fail_pdf
    assert ("docx" in result["export_errors"]) is fail_docx


@pytest.mark.parametrize(
    "title",
    [
        "Lập trình C# Cơ bản",
        'Tiêu đề có "dấu nháy"',
        "Mảng [A] và đường dẫn C:\\Temp",
        "Giáo trình tiếng Việt",
    ],
)
def test_typst_title_block_uses_a_string_literal(title: str) -> None:
    block = publisher._build_title_block(title)
    assert "#text(" in block
    assert f")[{title}]" not in block
    assert publisher._typst_string_literal(title) in block


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst is not installed")
def test_special_title_compiles_with_typst(tmp_path: Path) -> None:
    block = publisher._build_title_block('Lập trình C# [Cơ bản] "2026" C:\\Temp')
    typst_source = block.removeprefix("```{=typst}\n").removesuffix("\n```")
    result = subprocess.run(
        ["typst", "compile", "--format", "pdf", "-", str(tmp_path / "title.pdf")],
        input=typst_source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "title.pdf").stat().st_size > 0


def test_workflow_fails_when_a_required_export_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    markdown = tmp_path / "book.md"
    docx = tmp_path / "book.docx"
    markdown.write_text("# Book", encoding="utf-8")
    docx.write_bytes(b"PK\x03\x04DOCX")

    class Workflow:
        def stream(self, state, config):
            yield {"publisher": {
                "final_markdown_filepath": str(markdown),
                "final_pdf_filepath": None,
                "final_docx_filepath": str(docx),
                "export_errors": {"pdf": "synthetic PDF failure"},
            }}

    monkeypatch.setattr(
        orchestrator,
        "create_content_after_confirm_workflow",
        lambda: Workflow(),
    )
    result = asyncio.run(workflow_runner.continue_after_curriculum_confirmation(
        textbook_id=1,
        confirmed_curriculum={
            "topic": "C#",
            "chapters": [{
                "title": "Chapter 1",
                "subsections": [{
                    "title": "Section 1",
                    "description": "Description",
                    "search_query": "C# basics",
                    "section_type": "medium",
                }],
            }],
        },
        initial_state={
            "request": "C#",
            "core_topic": "C#",
            "user_requirements": "",
            "language": "vi",
            "textbook_title": "C# Basics",
            "export_formats": ["PDF", "Word"],
        },
        db=None,
    ))

    assert result["success"] is False
    assert "PDF" in result["error"]
    assert result["pdf_path"] is None
    assert result["docx_path"] == str(docx)


def test_workflow_reports_terminal_insufficient_context_before_export(
    monkeypatch,
) -> None:
    class Workflow:
        def stream(self, state, config):
            yield {"context_evaluator": {
                "context_quality": "insufficient",
                "current_chapter_index": 0,
                "current_subsection_index": 0,
                "rag_source_audit": {
                    "warnings": [
                        "Context did not meet strict RAG gate: chars=1293, chunks=1."
                    ],
                },
            }}

    monkeypatch.setattr(
        orchestrator,
        "create_content_after_confirm_workflow",
        lambda: Workflow(),
    )
    result = asyncio.run(workflow_runner.continue_after_curriculum_confirmation(
        textbook_id=1,
        confirmed_curriculum={
            "topic": "C#",
            "chapters": [{
                "title": "Chapter 1",
                "subsections": [{
                    "title": "Section 1",
                    "description": "Description",
                    "search_query": "C# basics",
                    "section_type": "medium",
                }],
            }],
        },
        initial_state={
            "request": "C#",
            "core_topic": "C#",
            "user_requirements": "",
            "language": "vi",
            "textbook_title": "C# Basics",
            "export_formats": ["PDF", "Word"],
        },
        db=None,
    ))

    assert result["success"] is False
    assert "Insufficient RAG context for Chapter 1.1" in result["error"]
    assert "PDF" not in result["error"]
    assert result["source_audit"]["warnings"]
