import pytest

from app.services.textbook.structure_parser import (
    StructureParseError,
    parse_structure_markdown,
    structure_to_markdown,
)


def test_parse_structure_markdown_uses_chapters_and_subsections() -> None:
    curriculum = parse_structure_markdown(
        """
## Chapter One
### 1.1 First section
### (1.2) Second section
## Chapter Two
### Mục 2.1 Third section
""",
        topic="Test topic",
    )

    assert curriculum["topic"] == "Test topic"
    assert [chapter["title"] for chapter in curriculum["chapters"]] == [
        "Chapter One",
        "Chapter Two",
    ]
    assert [sub["title"] for sub in curriculum["chapters"][0]["subsections"]] == [
        "First section",
        "Second section",
    ]
    assert curriculum["chapters"][1]["subsections"][0]["title"] == "Third section"


def test_parse_structure_rejects_subsection_before_chapter() -> None:
    with pytest.raises(StructureParseError):
        parse_structure_markdown("### 1.1 No chapter")


def test_parse_structure_rejects_empty_chapter() -> None:
    with pytest.raises(StructureParseError):
        parse_structure_markdown("## Empty chapter")


def test_structure_to_markdown_round_trip_contract() -> None:
    markdown = structure_to_markdown({
        "chapters": [
            {
                "title": "Chapter",
                "subsections": [{"title": "Section"}],
            }
        ]
    })

    assert markdown == "## Chapter\n### 1.1 Section"


def test_structured_planner_preserves_user_structure(monkeypatch) -> None:
    from app.services.textbook.planner import HybridPlanner

    planner = HybridPlanner.__new__(HybridPlanner)

    def fake_enrich(*args, **kwargs):
        return [
            {
                "description": "Description A",
                "search_query": "query a",
                "section_type": "medium",
            },
            {
                "description": "Description B",
                "search_query": "query b",
                "section_type": "applied",
            },
        ]

    monkeypatch.setattr(planner, "_enrich_structured_chapter", fake_enrich)
    curriculum = planner.enrich_user_structure(
        "Topic",
        "Requirements",
        {
            "chapters": [
                {
                    "title": "Chapter A",
                    "subsections": [
                        {"title": "Section A"},
                        {"title": "Section B"},
                    ],
                }
            ]
        },
        language="en",
    )

    assert curriculum is not None
    assert curriculum.chapters[0].title == "Chapter A"
    assert [sub.title for sub in curriculum.chapters[0].subsections] == [
        "Section A",
        "Section B",
    ]
    assert curriculum.chapters[0].subsections[1].section_type == "applied"
