from __future__ import annotations

from pathlib import Path
import asyncio
import re
import shutil
import subprocess
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.services.textbook import publisher
from app.services.textbook.reviewer import ReviewerAgent
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


def test_publisher_filename_sanitizes_control_whitespace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    title = "LẬP TRÌNH WEB Hệ đào tạo Đại học\t_\nNgành đào tạo C++"
    monkeypatch.setattr(publisher, "BASE_DIR", tmp_path)
    monkeypatch.setattr(publisher, "image_dir", tmp_path / "outputs" / "images")
    monkeypatch.setattr(
        publisher,
        "pypandoc",
        _fake_pandoc(fail_pdf=False, fail_docx=False),
    )
    monkeypatch.setattr(publisher, "_get_word_reference_doc", lambda path: None)

    result = publisher.publish_curriculum(_state(title))

    markdown_path = Path(result["final_markdown_filepath"])
    assert markdown_path.is_file()
    assert "\t" not in markdown_path.name
    assert "\n" not in markdown_path.name
    assert result["final_pdf_filepath"]
    assert result["final_docx_filepath"]


def test_partial_markdown_checkpoint_preserves_reviewed_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(publisher, "BASE_DIR", tmp_path)
    state = {
        **_state("Giáo trình Web"),
        "rag_collection_name": "dynamic_context_221_20260704",
        "final_content": "# CHƯƠNG 1: HTML\n\nNội dung đã hoàn thành.",
        "current_content": "## 1.2 CSS\n\nNội dung vừa qua reviewer và illustrator.",
    }

    path = publisher.save_partial_markdown_checkpoint(state)

    assert path is not None
    checkpoint = Path(path)
    assert checkpoint.is_file()
    content = checkpoint.read_text(encoding="utf-8")
    assert "Auto-saved checkpoint" in content
    assert "Nội dung đã hoàn thành." in content
    assert "Nội dung vừa qua reviewer và illustrator." in content
    assert checkpoint.name.endswith(".partial.md")


def test_context_route_runs_targeted_recovery_once(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.settings,
        "CRAG_MAX_CONTEXT_RETRIES",
        2,
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator.settings,
        "CRAG_TARGETED_RECOVERY_ENABLED",
        True,
        raising=False,
    )

    state = {
        "context_quality": "insufficient",
        "rag_retrieval_attempts": 2,
        "used_rag_queries": ["q1", "q2"],
        "rag_recovery_attempted": False,
    }

    assert (
        orchestrator.route_after_context_evaluation(state)
        == orchestrator.WorkflowDecision.RECOVER_CONTEXT
    )

    state["rag_recovery_attempted"] = True
    assert (
        orchestrator.route_after_context_evaluation(state)
        == orchestrator.WorkflowDecision.FINISHED
    )


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


def test_finalize_word_docx_localizes_toc_fonts_and_footer(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    path = tmp_path / "book.docx"
    doc = docx.Document()
    toc = doc.add_paragraph("Table of Contents")
    pstyle = OxmlElement("w:pStyle")
    pstyle.set(qn("w:val"), "TOCHeading")
    toc._p.get_or_add_pPr().append(pstyle)
    doc.add_heading("Lời nói đầu", level=1)
    doc.add_paragraph("Nội dung lời nói đầu.")
    doc.add_heading("CHƯƠNG 1: MỞ ĐẦU", level=1)
    doc.add_heading("1.1 Khái niệm", level=2)
    doc.add_heading("1.1.1 Chi tiết", level=3)
    doc.save(path)

    assert publisher.finalize_word_docx(
        path,
        "Mục lục",
        page_start_heading="Lời nói đầu",
    ) is True

    with ZipFile(path) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
        settings_xml = zf.read("word/settings.xml").decode("utf-8")
        styles_xml = zf.read("word/styles.xml").decode("utf-8")
        footer_names = [name for name in zf.namelist() if name.startswith("word/footer")]
        assert footer_names
        footer_xml = zf.read(footer_names[0]).decode("utf-8")

    assert "Mục lục" in document_xml
    assert "Table of Contents" not in document_xml
    assert document_xml.count("<w:sectPr") >= 2
    assert 'w:start="1"' in document_xml
    assert "w:updateFields" in settings_xml
    assert "PAGE" in footer_xml
    assert 'w:jc w:val="center"' in footer_xml

    for style_id in ("Heading1", "Heading2", "Heading3"):
        match = re.search(
            rf'<w:style\b[^>]*w:styleId="{style_id}"(?:(?!</w:style>).)*?</w:style>',
            styles_xml,
        )
        assert match, f"{style_id} style missing"
        style_xml = match.group(0)
        assert 'w:ascii="Times New Roman"' in style_xml
        assert "asciiTheme" not in style_xml


def test_reviewer_em_dash_cleanup_gate_is_vietnamese_only() -> None:
    assert ReviewerAgent._needs_em_dash_cleanup("CPU — bộ xử lý", "vi") is True
    assert ReviewerAgent._needs_em_dash_cleanup("CPU - bộ xử lý", "vi") is False
    assert ReviewerAgent._needs_em_dash_cleanup("CPU — processor", "en") is False


def test_remove_markdown_horizontal_rules_preserves_code_examples() -> None:
    content = (
        "## 1.2 Tiêu đề\n\n"
        "Đoạn một.\n\n"
        "---\n\n"
        "### 1.2.1 Mục con\n\n"
        "```markdown\n"
        "---\n"
        "title: Example\n"
        "---\n"
        "```\n\n"
        "----\n\n"
        "Đoạn hai."
    )

    cleaned = publisher.remove_markdown_horizontal_rules(content)

    assert "\n---\n\n###" not in cleaned
    assert "\n----\n\nĐoạn" not in cleaned
    assert "```markdown\n---\ntitle: Example\n---\n```" in cleaned


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
