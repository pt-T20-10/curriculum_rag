from types import SimpleNamespace

from app.routers.textbook import (
    _apply_confirmed_curriculum_counts,
    _is_free_admin,
    _repair_textbook_chapter_count,
    _sanitize_confirmed_curriculum,
    estimate_textbook_credits,
)
from app.models.user import UserRole


def test_confirmed_curriculum_updates_legacy_num_chapters() -> None:
    textbook = SimpleNamespace(
        curriculum_json=None,
        num_chapters=4,
        total_chapters=4,
        total_subsections=12,
        current_chapter=2,
        current_subsection=1,
    )
    confirmed_curriculum = {
        "topic": "Software Engineering",
        "chapters": [
            {"title": "Chapter 1", "subsections": [{"title": "Section 1"}]},
            {"title": "Chapter 2", "subsections": [{"title": "Section 2"}]},
            {"title": "Chapter 3", "subsections": [{"title": "Section 3"}]},
        ],
    }

    sanitized, chapter_titles, total_subsections = _sanitize_confirmed_curriculum(
        confirmed_curriculum
    )
    chapter_count = _apply_confirmed_curriculum_counts(
        textbook,
        sanitized,
        chapter_titles,
        total_subsections,
    )

    assert chapter_count == 3
    assert textbook.num_chapters == 3
    assert textbook.total_chapters == 3
    assert textbook.total_subsections == 3
    assert textbook.curriculum_json == sanitized
    assert textbook.current_chapter == 0
    assert textbook.current_subsection == 0


def test_textbook_read_repair_uses_saved_curriculum_chapter_count() -> None:
    textbook = SimpleNamespace(
        curriculum_json={
            "topic": "Software Engineering",
            "chapters": [
                {"title": "Chapter 1", "subsections": []},
                {"title": "Chapter 2", "subsections": []},
                {"title": "Chapter 3", "subsections": []},
            ],
        },
        num_chapters=4,
        total_chapters=4,
        progress_data={"num_chapters": 4, "total_chapters": 4},
    )

    changed = _repair_textbook_chapter_count(textbook)

    assert changed is True
    assert textbook.num_chapters == 3
    assert textbook.total_chapters == 3
    assert textbook.progress_data["num_chapters"] == 3
    assert textbook.progress_data["total_chapters"] == 3


def test_credit_estimate_has_one_credit_minimum() -> None:
    assert estimate_textbook_credits(
        total_subsections=1,
        content_level="Ngắn",
        enable_images=False,
    ) == 1


def test_credit_estimate_scales_for_long_curriculum() -> None:
    assert estimate_textbook_credits(
        total_subsections=20,
        content_level="Trung Bình",
        enable_images=False,
    ) > 1


def test_credit_estimate_images_increase_cost() -> None:
    without_images = estimate_textbook_credits(
        total_subsections=12,
        content_level="Trung Bình",
        enable_images=False,
    )
    with_images = estimate_textbook_credits(
        total_subsections=12,
        content_level="Trung Bình",
        enable_images=True,
    )

    assert with_images > without_images


def test_credit_estimate_content_level_increases_cost() -> None:
    medium = estimate_textbook_credits(
        total_subsections=8,
        content_level="Trung Bình",
        enable_images=False,
    )
    long = estimate_textbook_credits(
        total_subsections=8,
        content_level="Dài",
        enable_images=False,
    )

    assert long > medium


def test_credit_estimate_uses_confirmed_curriculum_subsection_count() -> None:
    short_curriculum = {
        "topic": "Software Engineering",
        "chapters": [
            {"title": "Chapter 1", "subsections": [{"title": "Section 1"}]},
        ],
    }
    long_curriculum = {
        "topic": "Software Engineering",
        "chapters": [
            {
                "title": "Chapter 1",
                "subsections": [{"title": f"Section {idx}"} for idx in range(1, 13)],
            },
        ],
    }

    _, _, short_total = _sanitize_confirmed_curriculum(short_curriculum)
    _, _, long_total = _sanitize_confirmed_curriculum(long_curriculum)

    assert estimate_textbook_credits(short_total, "Trung Bình", False) == 1
    assert estimate_textbook_credits(long_total, "Trung Bình", False) > 1


def test_free_admin_requires_admin_role_and_unlocked_account() -> None:
    admin = SimpleNamespace(
        role=UserRole.ADMIN.value,
        is_locked=False,
        is_deleted=False,
    )
    locked_admin = SimpleNamespace(
        role=UserRole.ADMIN.value,
        is_locked=True,
        is_deleted=False,
    )
    user = SimpleNamespace(
        role=UserRole.USER.value,
        is_locked=False,
        is_deleted=False,
    )

    assert _is_free_admin(admin) is True
    assert _is_free_admin(locked_admin) is False
    assert _is_free_admin(user) is False
