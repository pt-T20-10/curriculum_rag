from __future__ import annotations


def test_workflow_runner_emergency_publish_creates_artifacts(monkeypatch, tmp_path) -> None:
    from app.services.textbook import publisher, workflow_runner

    md_path = tmp_path / "partial.md"
    pdf_path = tmp_path / "partial.pdf"
    docx_path = tmp_path / "partial.docx"
    for path in (md_path, pdf_path, docx_path):
        path.write_text("ok", encoding="utf-8")

    def fake_publish(state):
        return {
            "final_markdown_filepath": str(md_path),
            "final_pdf_filepath": str(pdf_path),
            "final_filepath": str(pdf_path),
            "final_docx_filepath": str(docx_path),
            "export_errors": {},
        }

    monkeypatch.setattr(publisher, "publish_curriculum", fake_publish)

    state = {
        "request": "Test",
        "final_content": "## 1.1 Content",
        "current_content": "",
    }

    artifacts = workflow_runner._publish_recoverable_content(state, "test")

    assert artifacts["markdown_path"] == str(md_path)
    assert artifacts["pdf_path"] == str(pdf_path)
    assert artifacts["docx_path"] == str(docx_path)
    assert state["final_markdown_filepath"] == str(md_path)


def test_workflow_runner_emergency_publish_skips_empty_content(monkeypatch) -> None:
    from app.services.textbook import publisher, workflow_runner

    called = False

    def fake_publish(state):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(publisher, "publish_curriculum", fake_publish)

    artifacts = workflow_runner._publish_recoverable_content(
        {"final_content": "", "current_content": ""},
        "test",
    )

    assert artifacts == {}
    assert called is False
