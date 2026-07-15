from sqlalchemy import Text

from app.models.textbook import Textbook
from app.schemas.curriculum import build_initial_state
from app.schemas.textbook import TextbookCreate
from app.services.textbook.query_formulator import formulate_query
from app.services.textbook.validator import (
    apply_formula_validation,
    classify_formula_need,
)


def _validation(core_topic: str) -> dict:
    return {
        "valid": True,
        "reason": "",
        "suggestion": "",
        "content_type": "technical",
        "core_topic": core_topic,
        "user_requirements": "",
    }


def test_textbook_create_defaults_to_auto_formula_policy() -> None:
    payload = TextbookCreate(topic="Lập trình Python cơ bản")

    assert payload.formula_policy == "auto"


def test_textbook_topic_column_allows_long_text() -> None:
    assert isinstance(Textbook.__table__.c.topic.type, Text)
    assert isinstance(Textbook.__table__.c.user_requirements.type, Text)


def test_formula_need_classification_examples() -> None:
    assert classify_formula_need("Toán cao cấp 1") == "essential"
    assert classify_formula_need("Machine Learning cơ bản") == "likely"
    assert classify_formula_need("Giáo trình Xử lý ảnh dành cho bậc đại học") == "likely"
    assert classify_formula_need("Nhập môn công nghệ phần mềm") == "likely"
    assert classify_formula_need("Lịch sử Việt Nam hiện đại") == "none"


def test_essential_topic_auto_resolves_to_include() -> None:
    result = apply_formula_validation(
        _validation("Toán cao cấp 1"),
        "Toán cao cấp 1",
        formula_policy="auto",
        ui_language="vi",
    )

    assert result["formula_need"] == "essential"
    assert result["formula_policy"] == "include"
    assert result["formula_confirmation_required"] is False
    assert result["formula_conflict"] is False


def test_likely_topic_auto_requires_confirmation() -> None:
    result = apply_formula_validation(
        _validation("Machine Learning cơ bản"),
        "Machine Learning cơ bản",
        formula_policy="auto",
        ui_language="vi",
    )

    assert result["formula_need"] == "likely"
    assert result["formula_policy"] == "auto"
    assert result["formula_confirmation_required"] is True
    assert result["formula_conflict"] is False


def test_likely_topic_include_requires_confirmation_first() -> None:
    result = apply_formula_validation(
        _validation("Machine Learning cơ bản"),
        "Machine Learning cơ bản",
        formula_policy="include",
        ui_language="vi",
    )

    assert result["formula_need"] == "likely"
    assert result["formula_policy"] == "include"
    assert result["formula_confirmation_required"] is True
    assert result["formula_conflict"] is False


def test_likely_topic_include_is_accepted_after_confirmation() -> None:
    result = apply_formula_validation(
        _validation("Machine Learning cơ bản"),
        "Machine Learning cơ bản",
        formula_policy="include",
        formula_confirmed=True,
        ui_language="vi",
    )

    assert result["formula_need"] == "likely"
    assert result["formula_policy"] == "include"
    assert result["formula_confirmation_required"] is False
    assert result["formula_conflict"] is False


def test_likely_topic_with_negative_formula_intent_does_not_ask() -> None:
    result = apply_formula_validation(
        _validation("Machine Learning cơ bản"),
        "Machine Learning cơ bản không cần công thức",
        formula_policy="auto",
        ui_language="vi",
    )

    assert result["formula_need"] == "likely"
    assert result["formula_policy"] == "exclude"
    assert result["formula_confirmation_required"] is False
    assert result["formula_conflict"] is False


def test_non_formula_topic_include_is_conflict() -> None:
    result = apply_formula_validation(
        _validation("Lịch sử Việt Nam hiện đại"),
        "Lịch sử Việt Nam hiện đại",
        formula_policy="include",
        ui_language="vi",
    )

    assert result["formula_need"] == "none"
    assert result["formula_conflict"] is True


def test_non_formula_topic_text_formula_request_is_conflict() -> None:
    result = apply_formula_validation(
        _validation("Lịch sử Việt Nam hiện đại"),
        "Lịch sử Việt Nam hiện đại có công thức",
        formula_policy="auto",
        ui_language="vi",
    )

    assert result["formula_need"] == "none"
    assert result["formula_intent_present"] is True
    assert result["formula_conflict"] is True


def test_build_initial_state_carries_formula_metadata() -> None:
    state = build_initial_state(
        request="Machine Learning cơ bản",
        formula_policy="include",
        formula_need="likely",
    )

    assert state["formula_policy"] == "include"
    assert state["formula_need"] == "likely"


def test_query_formulator_adds_formula_terms_when_included() -> None:
    state = build_initial_state(
        request="Machine Learning cơ bản",
        formula_policy="include",
        formula_need="likely",
    )
    state.update({
        "curriculum": {
            "chapters": [{
                "title": "Hồi quy tuyến tính",
                "subsections": [{
                    "title": "Hàm mất mát",
                    "description": "Trình bày hàm mất mát trong mô hình hồi quy.",
                    "search_query": "linear regression loss function",
                    "section_type": "deep",
                }],
            }],
        },
        "current_chapter_index": 0,
        "current_subsection_index": 0,
    })

    result = formulate_query(state)  # type: ignore[arg-type]

    assert "formula" in result["retrieval_query"]
    assert "equation" in result["retrieval_query"]
