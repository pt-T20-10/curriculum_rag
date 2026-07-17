from app.routers.textbook import _sanitize_confirmed_curriculum
from app.services.textbook.page_budget import allocate_page_budget, validate_page_configuration
from app.services.textbook.writer import write_section_crag, WriterAgent


def _curriculum() -> dict:
    return {
        "topic": "Python",
        "chapters": [
            {
                "title": "Basics",
                "subsections": [
                    {"title": "Syntax", "description": "Syntax", "search_query": "python syntax", "section_type": "medium"},
                    {"title": "Practice", "description": "Practice", "search_query": "python practice", "section_type": "applied"},
                ],
            },
            {
                "title": "Advanced",
                "subsections": [
                    {"title": "Decorators", "description": "Decorators", "search_query": "python decorators", "section_type": "deep"},
                ],
            },
        ],
    }


def test_page_budget_allocates_words_and_chars_without_images() -> None:
    enriched, validation = allocate_page_budget(
        _curriculum(),
        target_pages=30,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )

    assert validation["severity"] == "ok"
    assert enriched["target_pages"] == 30
    assert enriched["front_matter_pages"] == 1
    assert enriched["content_intro_pages"] == 1
    assert enriched["excluded_export_pages"] == 2
    assert isinstance(enriched["estimated_pages"], int)
    assert isinstance(enriched["chapters"][0]["estimated_pages"], int)
    first_sub = enriched["chapters"][0]["subsections"][0]
    assert isinstance(first_sub["estimated_pages"], int)
    assert isinstance(first_sub["target_pages"], int)
    assert first_sub["estimated_pages"] > 0
    assert first_sub["target_words"] > 0
    assert first_sub["target_chars_max"] > first_sub["target_chars_min"]


def test_page_budget_images_reduce_words_per_page() -> None:
    plain, _ = allocate_page_budget(
        _curriculum(),
        target_pages=30,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )
    with_images, _ = allocate_page_budget(
        _curriculum(),
        target_pages=30,
        enable_images=True,
        language="vi",
        textbook_mode="standard",
    )

    plain_words = plain["chapters"][0]["subsections"][0]["target_words"]
    image_words = with_images["chapters"][0]["subsections"][0]["target_words"]
    assert image_words < plain_words


def test_code_heavy_layout_reduces_word_budget() -> None:
    code_curriculum = {
        "topic": "Lập trình Python",
        "chapters": [
            {
                "title": "Cú pháp Python và vòng lặp",
                "subsections": [
                    {"title": "Viết chương trình Python đầu tiên", "target_pages": 1},
                    {"title": "Bài tập thực hành với list và tuple", "target_pages": 1},
                ],
            }
        ],
    }
    prose_curriculum = {
        "topic": "Kỹ năng đọc hiểu học thuật",
        "chapters": [
            {
                "title": "Nền tảng đọc hiểu",
                "subsections": [
                    {"title": "Xây dựng thói quen đọc", "target_pages": 1},
                    {"title": "Ghi chú và phản tư", "target_pages": 1},
                ],
            }
        ],
    }

    code, _ = allocate_page_budget(
        code_curriculum,
        target_pages=5,
        enable_images=True,
        language="vi",
        textbook_mode="standard",
    )
    prose, _ = allocate_page_budget(
        prose_curriculum,
        target_pages=5,
        enable_images=True,
        language="vi",
        textbook_mode="standard",
    )

    assert code["layout_profile"] == "code"
    assert prose["layout_profile"] == "prose"
    assert code["layout_word_scale"] < prose["layout_word_scale"]
    assert code["chapters"][0]["subsections"][0]["target_words"] < prose["chapters"][0]["subsections"][0]["target_words"]


def test_long_target_applies_fill_bias_without_overfitting_topic() -> None:
    curriculum = {
        "topic": "Quản trị nhân sự",
        "chapters": [
            {
                "title": "Đánh giá hiệu suất và KPI",
                "target_pages": 40,
                "subsections": [
                    {"title": "Rubric đánh giá năng lực", "target_pages": 20},
                    {"title": "Tình huống quản lý nhân sự", "target_pages": 20},
                ],
            }
        ],
    }

    enriched, validation = allocate_page_budget(
        curriculum,
        target_pages=100,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
        formula_policy="include",
    )

    assert enriched["layout_profile"] in {"case_based", "technical"}
    assert enriched["page_fill_bias"] > 1.0
    assert enriched["formula_density"] == "contextual"
    assert enriched["expansion_strategy"] in {
        "case_studies_rubrics_metrics",
        "models_metrics_examples",
    }
    assert validation["page_fill_bias"] == enriched["page_fill_bias"]
    assert enriched["chapters"][0]["subsections"][0]["formula_density"] == "contextual"


def test_comparative_subject_uses_structured_strategy_without_fake_formulas() -> None:
    curriculum = {
        "topic": "Lịch sử Việt Nam",
        "chapters": [
            {
                "title": "Các giai đoạn lịch sử và hệ quả xã hội",
                "subsections": [
                    {"title": "So sánh các giai đoạn phát triển", "target_pages": 8},
                ],
            }
        ],
    }

    enriched, _ = allocate_page_budget(
        curriculum,
        target_pages=80,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
        formula_policy="include",
    )

    subsection = enriched["chapters"][0]["subsections"][0]
    assert enriched["layout_profile"] == "comparative"
    assert subsection["expansion_strategy"] == "comparison_tables_timelines_frameworks"
    assert subsection["formula_density"] == "contextual"


def test_software_engineering_uses_technical_structuring_with_formula_priority() -> None:
    curriculum = {
        "topic": "Nhập môn công nghệ phần mềm",
        "chapters": [
            {
                "title": "Tiến trình phần mềm",
                "target_pages": 50,
                "subsections": [
                    {"title": "Phân tích yêu cầu và đặc tả"},
                    {"title": "Kiểm thử và quản lý chất lượng"},
                    {"title": "Ước lượng chi phí phần mềm"},
                ],
            }
        ],
    }

    enriched, _ = allocate_page_budget(
        curriculum,
        target_pages=100,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
        formula_policy="include",
    )

    assert enriched["layout_profile"] in {"technical", "procedure", "case_based"}
    assert enriched["formula_density"] == "contextual"
    assert enriched["page_fill_bias"] > 1.0
    assert all(
        subsection["formula_density"] == "contextual"
        for chapter in enriched["chapters"]
        for subsection in chapter["subsections"]
    )


def test_page_budget_fills_missing_pages_by_enriched_section_weights() -> None:
    curriculum = {
        "topic": "Thiết kế hệ thống phần mềm",
        "chapters": [
            {
                "title": "Nền tảng",
                "subsections": [
                    {"title": "Khái niệm tổng quan", "section_type": "light"},
                    {"title": "Mô hình kiến trúc", "section_type": "deep"},
                ],
            },
            {
                "title": "Triển khai",
                "subsections": [
                    {"title": "Quy trình thực hành", "section_type": "applied"},
                ],
            },
        ],
    }

    enriched, validation = allocate_page_budget(
        curriculum,
        target_pages=31,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )

    assert validation["severity"] == "ok"
    first_chapter = enriched["chapters"][0]
    light_sub, deep_sub = first_chapter["subsections"]
    assert deep_sub["target_pages"] > light_sub["target_pages"]
    assert (
        sum(sub["target_pages"] for sub in first_chapter["subsections"])
        <= first_chapter["target_pages"]
    )


def test_page_budget_fills_missing_subsections_inside_existing_chapter_budget() -> None:
    curriculum = {
        "topic": "Nhập môn công nghệ phần mềm",
        "chapters": [
            {
                "title": "Tiến trình phần mềm",
                "target_pages": 30,
                "subsections": [
                    {"title": "Tổng quan", "target_pages": 10, "section_type": "light"},
                    {"title": "Kiểm thử", "section_type": "deep"},
                    {"title": "Triển khai", "section_type": "applied"},
                ],
            }
        ],
    }

    enriched, validation = allocate_page_budget(
        curriculum,
        target_pages=31,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )

    subsections = enriched["chapters"][0]["subsections"]
    assert validation["severity"] == "ok"
    assert enriched["chapters"][0]["target_pages"] == 30
    assert subsections[0]["target_pages"] == 10
    assert sum(sub["target_pages"] for sub in subsections) == 30
    assert subsections[1]["target_pages"] > subsections[2]["target_pages"]


def test_page_budget_fills_missing_chapters_from_remaining_body_budget() -> None:
    curriculum = {
        "topic": "Quản trị nhân sự",
        "chapters": [
            {
                "title": "Nền tảng",
                "target_pages": 10,
                "subsections": [
                    {"title": "Khái niệm", "section_type": "light"},
                    {"title": "Vai trò", "section_type": "medium"},
                ],
            },
            {
                "title": "Đánh giá hiệu suất",
                "subsections": [
                    {"title": "KPI", "section_type": "deep"},
                    {"title": "Rubric", "section_type": "applied"},
                ],
            },
        ],
    }

    enriched, validation = allocate_page_budget(
        curriculum,
        target_pages=31,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )

    assert validation["severity"] == "ok"
    assert enriched["chapters"][0]["target_pages"] == 10
    assert enriched["chapters"][1]["target_pages"] == 20
    assert sum(chapter["target_pages"] for chapter in enriched["chapters"]) == 30


def test_page_budget_errors_when_subsection_pages_exceed_chapter_budget() -> None:
    curriculum = {
        "topic": "Quản trị dự án",
        "chapters": [
            {
                "title": "Lập kế hoạch",
                "target_pages": 30,
                "subsections": [
                    {"title": "Phạm vi", "target_pages": 10},
                    {"title": "Tiến độ", "target_pages": 12},
                    {"title": "Chi phí", "target_pages": 9},
                ],
            }
        ],
    }

    _, validation = allocate_page_budget(
        curriculum,
        target_pages=31,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )

    assert validation["severity"] == "error"
    assert "không được vượt quá" in " ".join(validation["errors"])


def test_page_budget_warns_and_errors_for_mismatch() -> None:
    warning_curriculum = _curriculum()
    warning_curriculum["chapters"][0]["target_pages"] = 10
    warning_curriculum["chapters"][1]["target_pages"] = 10
    _, warning = allocate_page_budget(
        warning_curriculum,
        target_pages=30,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )
    assert warning["severity"] == "warning"

    error_curriculum = _curriculum()
    error_curriculum["chapters"][0]["target_pages"] = 2
    error_curriculum["chapters"][1]["target_pages"] = 2
    _, error = allocate_page_budget(
        error_curriculum,
        target_pages=30,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )
    assert error["severity"] == "error"


def test_page_configuration_rejects_too_few_pages_for_auto_limits() -> None:
    validation = validate_page_configuration(
        target_pages=5,
        num_chapters=3,
        max_subsections_per_chapter=5,
        enable_images=True,
        language="vi",
        textbook_mode="standard",
    )

    assert validation["severity"] == "error"
    assert validation["target_pages"] == 5
    assert validation["front_matter_pages"] == 1
    assert validation["content_intro_pages"] == 1
    assert validation["excluded_export_pages"] == 3
    assert "Số trang nội dung chưa phù hợp" in validation["errors"][0]
    assert "Chapter" not in " ".join(validation["errors"])


def test_page_configuration_warns_when_budget_is_tight() -> None:
    validation = validate_page_configuration(
        target_pages=23,
        num_chapters=3,
        max_subsections_per_chapter=5,
        enable_images=True,
        language="vi",
        textbook_mode="standard",
    )

    assert validation["severity"] == "warning"
    assert "khá sát" in validation["warnings"][0]


def test_page_configuration_uses_english_when_requested() -> None:
    validation = validate_page_configuration(
        target_pages=5,
        num_chapters=3,
        max_subsections_per_chapter=5,
        enable_images=True,
        language="en",
        textbook_mode="standard",
    )

    assert validation["severity"] == "error"
    assert "Content page count is not compatible" in validation["errors"][0]


def test_page_budget_subsection_mismatch_messages_are_localized() -> None:
    curriculum = _curriculum()
    curriculum["chapters"][0]["target_pages"] = 12
    curriculum["chapters"][0]["subsections"][0]["target_pages"] = 1
    curriculum["chapters"][0]["subsections"][1]["target_pages"] = 1

    _, validation = allocate_page_budget(
        curriculum,
        target_pages=20,
        enable_images=False,
        language="vi",
        textbook_mode="standard",
    )

    messages = " ".join(validation["warnings"] + validation["errors"])
    assert validation["severity"] in {"warning", "error"}
    assert "Chương 1" in messages
    assert "Chapter" not in messages


def test_sanitize_confirmed_curriculum_preserves_page_fields() -> None:
    curriculum = _curriculum()
    curriculum["target_pages"] = 30
    curriculum["chapters"][0]["target_pages"] = 12
    curriculum["chapters"][0]["subsections"][0]["target_pages"] = 6
    curriculum["chapters"][0]["subsections"][0]["target_chars_min"] = 2400
    curriculum["chapters"][0]["subsections"][0]["layout_profile"] = "case_based"
    curriculum["chapters"][0]["subsections"][0]["formula_density"] = "contextual"
    curriculum["chapters"][0]["subsections"][0]["expansion_strategy"] = "case_studies_rubrics_metrics"
    curriculum["page_fill_bias"] = 1.12

    sanitized, _, _ = _sanitize_confirmed_curriculum(curriculum)

    assert sanitized["target_pages"] == 30
    assert sanitized["chapters"][0]["target_pages"] == 12
    assert sanitized["chapters"][0]["subsections"][0]["target_pages"] == 6
    assert sanitized["chapters"][0]["subsections"][0]["target_chars_min"] == 2400
    assert sanitized["chapters"][0]["subsections"][0]["layout_profile"] == "case_based"
    assert sanitized["chapters"][0]["subsections"][0]["formula_density"] == "contextual"
    assert sanitized["chapters"][0]["subsections"][0]["expansion_strategy"] == "case_studies_rubrics_metrics"
    assert sanitized["page_fill_bias"] == 1.12


def test_writer_uses_page_budget_char_target(monkeypatch) -> None:
    captured = {}

    def fake_write_section(self, **kwargs):
        captured.update(kwargs)
        return "## 1.1 Syntax\n\nContent"

    monkeypatch.setattr(WriterAgent, "write_section", fake_write_section)

    state = {
        "curriculum": {
            "chapters": [
                {
                    "title": "Basics",
                    "subsections": [
                        {
                            "title": "Syntax",
                            "description": "Syntax",
                            "search_query": "python syntax",
                            "section_type": "medium",
                            "target_chars_min": 2500,
                            "target_chars_max": 3300,
                            "writer_call_count": 2,
                            "target_pages": 2,
                            "layout_profile": "code",
                            "formula_density": "contextual",
                            "expansion_strategy": "code_examples_debugging_tasks",
                            "page_fill_bias": 1.1,
                        }
                    ],
                }
            ]
        },
        "current_chapter_index": 0,
        "current_subsection_index": 0,
        "content_level": "Ngắn",
        "language": "en",
        "enable_images": False,
        "request": "Python",
        "rag_context": "context",
        "chapter_header_written": False,
        "section_summaries": [],
    }

    result = write_section_crag(state)

    assert "## 1.1" in result["current_content"]
    assert captured["char_target"] == (2500, 3300)
    assert captured["writer_call_count"] == 2
    assert captured["target_pages"] == 2
    assert captured["layout_profile"] == "code"
    assert captured["formula_density"] == "contextual"
    assert captured["expansion_strategy"] == "code_examples_debugging_tasks"
    assert captured["page_fill_bias"] == 1.1
