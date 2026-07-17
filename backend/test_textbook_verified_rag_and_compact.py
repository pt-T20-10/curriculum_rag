from app.services.textbook.evaluator import deterministic_context_is_sufficient
from app.services.textbook.page_budget import allocate_page_budget
from app.services.textbook.retriever import build_source_audit_summary
from app.services.textbook.reviewer import (
    _normalize_unnumbered_h3_to_bold,
    deterministic_quality_gate_passes,
)


def _context(statuses: list[str]) -> str:
    parts = []
    for idx, status in enumerate(statuses, start=1):
        parts.append(
            f"Document {idx} (Source: https://example{idx}.edu/course | Score: 0.72 | Status: {status}):\n"
            + ("relevant academic context " * 80)
        )
    return "\n\n---\n\n".join(parts)


def test_balanced_gate_rejects_pass_only_context() -> None:
    context = _context(["pass", "pass", "pass", "pass"])
    audit = build_source_audit_summary(context, used_queries=["network administration"])

    assert audit["pass_chunks"] == 4
    assert audit["verified_chunks"] == 0
    assert not deterministic_context_is_sufficient(
        context,
        audit,
        require_verified=True,
        min_verified_chunks=2,
    )


def test_balanced_gate_accepts_two_verified_sources() -> None:
    context = _context(["verified", "verified", "pass"])
    audit = build_source_audit_summary(context, used_queries=["image processing"])

    assert audit["verified_chunks"] == 2
    assert audit["verified_sources"] == 2
    assert deterministic_context_is_sufficient(
        context,
        audit,
        require_verified=True,
        min_verified_chunks=2,
    )


def test_compact_page_budget_marks_mode_and_reduces_image_words() -> None:
    curriculum = {
        "topic": "Quản trị mạng",
        "chapters": [
            {
                "title": "Windows Server",
                "target_pages": 2,
                "subsections": [
                    {
                        "title": "Giới thiệu quản trị mạng",
                        "description": "Khái niệm cơ bản",
                        "search_query": "network administration basics",
                        "target_pages": 1,
                    }
                ],
            }
        ],
    }
    plain, _ = allocate_page_budget(curriculum, target_pages=3, enable_images=False)
    with_images, _ = allocate_page_budget(curriculum, target_pages=3, enable_images=True)

    plain_sub = plain["chapters"][0]["subsections"][0]
    image_sub = with_images["chapters"][0]["subsections"][0]
    assert image_sub["page_budget_mode"] == "compact"
    assert image_sub["target_words"] < plain_sub["target_words"]


def test_reviewer_downgrades_unnumbered_h3_to_bold_lead_in() -> None:
    content = "## 1.1 Giới thiệu\n\n### Đặc điểm kỹ thuật\n\nNội dung chính."
    fixed = _normalize_unnumbered_h3_to_bold(content)

    assert "### Đặc điểm kỹ thuật" not in fixed
    assert "**Đặc điểm kỹ thuật:**" in fixed


def test_compact_gate_allows_no_h3_when_core_content_is_present() -> None:
    body = (
        "## 1.1 Giới thiệu quản trị mạng\n\n"
        + "Quản trị mạng là hoạt động cấu hình, giám sát và bảo trì tài nguyên mạng. " * 18
    )

    assert deterministic_quality_gate_passes(
        body,
        char_min=300,
        char_max=1800,
        section_num="1.1",
        section_title="Giới thiệu quản trị mạng",
        section_type="medium",
        language="vi",
        page_budget_mode="compact",
    )
