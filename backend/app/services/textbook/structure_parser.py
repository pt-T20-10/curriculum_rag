"""Helpers for user-provided textbook structures."""

from __future__ import annotations

import re
from typing import Any


class StructureParseError(ValueError):
    """Raised when a user-provided outline cannot be parsed safely."""


_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_SUBSECTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"\(?\d+(?:\.\d+)+\)?"
    r"|(?:mục|section)\s+\d+(?:\.\d+)+"
    r")\s*[:.)\-\s]*",
    re.IGNORECASE,
)


def _clean_heading_text(value: Any) -> str:
    return str(value or "").strip()


def clean_subsection_title(value: Any) -> str:
    title = _clean_heading_text(value)
    cleaned = _SUBSECTION_PREFIX_RE.sub("", title).strip()
    return cleaned or title


def parse_structure_markdown(markdown: str, topic: str = "") -> dict[str, Any]:
    """
    Parse a Markdown outline where ``##`` is a chapter and ``###`` is a subsection.

    Non-empty non-heading lines are rejected so the contract remains predictable
    for both the UI serializer and external API callers.
    """
    chapters: list[dict[str, Any]] = []
    current_chapter: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(str(markdown or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        match = _HEADING_RE.match(line)
        if not match:
            raise StructureParseError(
                f"Line {line_number} must be a ## chapter or ### subsection heading"
            )

        marker, raw_title = match.groups()
        title = _clean_heading_text(raw_title)
        if not title:
            raise StructureParseError(f"Line {line_number} has an empty heading title")

        if marker == "##":
            current_chapter = {"title": title, "subsections": []}
            chapters.append(current_chapter)
            continue

        if current_chapter is None:
            raise StructureParseError("A ### subsection cannot appear before a ## chapter")

        subsection_title = clean_subsection_title(title)
        current_chapter["subsections"].append({"title": subsection_title})

    if not chapters:
        raise StructureParseError("Structure must contain at least one chapter")

    for idx, chapter in enumerate(chapters, start=1):
        if not chapter["title"]:
            raise StructureParseError(f"Chapter {idx} title cannot be empty")
        if not chapter["subsections"]:
            raise StructureParseError(f"Chapter {idx} must contain at least one subsection")

    return {
        "topic": _clean_heading_text(topic),
        "chapters": chapters,
    }


def structure_to_markdown(curriculum: dict[str, Any]) -> str:
    """Serialize a curriculum-like dict to the Markdown outline contract."""
    lines: list[str] = []
    chapters = curriculum.get("chapters") if isinstance(curriculum, dict) else []
    for chapter_index, chapter in enumerate(chapters or [], start=1):
        chapter_title = _clean_heading_text(chapter.get("title"))
        if not chapter_title:
            continue
        lines.append(f"## {chapter_title}")
        subsections = chapter.get("subsections") or []
        for subsection_index, subsection in enumerate(subsections, start=1):
            subsection_title = _clean_heading_text(subsection.get("title"))
            if subsection_title:
                lines.append(f"### {chapter_index}.{subsection_index} {subsection_title}")
    return "\n".join(lines)
