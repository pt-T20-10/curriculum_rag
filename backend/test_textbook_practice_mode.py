from pydantic import ValidationError

from app.schemas.curriculum import build_initial_state
from app.schemas.textbook import TextbookCreate
from app.services.textbook.planner import HybridPlanner
from app.services.textbook.query_formulator import formulate_query


def test_textbook_create_defaults_to_standard_mode() -> None:
    payload = TextbookCreate(topic="Lập trình Python cơ bản", target_pages=20)

    assert payload.textbook_mode == "standard"


def test_textbook_create_accepts_practice_mode_only_from_literal_values() -> None:
    payload = TextbookCreate(
        topic="Thực hành lập trình Python cho sinh viên đại học",
        target_pages=20,
        textbook_mode="practice",
    )

    assert payload.textbook_mode == "practice"

    try:
        TextbookCreate(topic="Python", target_pages=20, textbook_mode="lab")  # type: ignore[arg-type]
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("invalid textbook_mode should fail validation")


def test_build_initial_state_carries_textbook_mode() -> None:
    state = build_initial_state(
        request="Thực hành cơ sở dữ liệu",
        textbook_mode="practice",
    )

    assert state["textbook_mode"] == "practice"


def test_practice_structured_fallback_is_applied_and_practical() -> None:
    planner = object.__new__(HybridPlanner)

    metadata = planner._fallback_structured_metadata(
        core_topic="Cơ sở dữ liệu",
        user_requirements="học phần thực hành",
        chapter_title="Truy vấn dữ liệu",
        subsection_title="Viết truy vấn SELECT",
        language="vi",
        textbook_mode="practice",
    )

    assert metadata["section_type"] == "applied"
    assert "lab" in metadata["search_query"]
    assert "hands-on" in metadata["search_query"]
    assert "exercise" in metadata["search_query"]
    assert "bài nâng cao" in metadata["description"]


def test_query_formulator_adds_practice_retrieval_terms() -> None:
    state = build_initial_state(
        request="Thực hành lập trình Python",
        textbook_mode="practice",
    )
    state.update({
        "curriculum": {
            "chapters": [{
                "title": "Thực hành vòng lặp",
                "subsections": [{
                    "title": "Viết vòng lặp for",
                    "description": "Hoàn thành bài thực hành vòng lặp.",
                    "search_query": "python for loop",
                    "section_type": "applied",
                }],
            }],
        },
        "current_chapter_index": 0,
        "current_subsection_index": 0,
    })

    result = formulate_query(state)  # type: ignore[arg-type]

    query = result["retrieval_query"]
    assert "lab" in query
    assert "hands-on" in query
    assert "exercise" in query
