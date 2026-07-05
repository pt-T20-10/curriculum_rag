from __future__ import annotations

from app.schemas.curriculum import build_initial_state


def test_initial_state_exports_pdf_and_word_by_default() -> None:
    state = build_initial_state(request="Test topic")

    assert state["export_formats"] == ["PDF", "Word"]


def test_content_level_min_words_raise_character_floor(monkeypatch) -> None:
    from app.schemas import curriculum
    from app.services import runtime_config

    overrides = {
        "CONTENT_LEVEL_SHORT_MIN_WORDS": 600,
    }
    monkeypatch.setattr(
        runtime_config,
        "get_runtime_config",
        lambda key, required=False: overrides.get(key),
    )

    min_chars, max_chars = curriculum.get_char_target("light", "Ngắn")

    assert min_chars == 3000
    assert max_chars >= min_chars + 250


def test_content_level_word_ratio_uses_language(monkeypatch) -> None:
    from app.schemas import curriculum
    from app.services import runtime_config

    overrides = {
        "CONTENT_LEVEL_SHORT_MIN_WORDS": 600,
        "CONTENT_WORD_TO_CHAR_RATIO_VI": 5.0,
        "CONTENT_WORD_TO_CHAR_RATIO_EN": 6.0,
    }
    monkeypatch.setattr(
        runtime_config,
        "get_runtime_config",
        lambda key, required=False: overrides.get(key),
    )

    vi_min, _ = curriculum.get_char_target("light", "Ngắn", language="vi")
    en_min, _ = curriculum.get_char_target("light", "Ngắn", language="en")

    assert vi_min == 3000
    assert en_min == 3600


def test_content_level_min_words_prefer_advanced_config(monkeypatch) -> None:
    from app.schemas import curriculum
    from app.services import runtime_config

    monkeypatch.setattr(
        runtime_config,
        "get_runtime_config",
        lambda key, required=False: 300,
    )

    min_chars, _ = curriculum.get_char_target(
        "light",
        "Ngắn",
        {
            "CONTENT_LEVEL_SHORT_MIN_WORDS": 700,
            "CONTENT_WORD_TO_CHAR_RATIO_VI": 6.0,
        },
    )

    assert min_chars == 4200


def test_content_level_max_words_caps_character_ceiling() -> None:
    from app.schemas import curriculum

    min_chars, max_chars = curriculum.get_char_target(
        "light",
        "Ngắn",
        {
            "CONTENT_LEVEL_SHORT_MIN_WORDS": 300,
            "CONTENT_LEVEL_SHORT_MAX_WORDS": 350,
            "CONTENT_WORD_TO_CHAR_RATIO_VI": 5.0,
        },
        language="vi",
    )

    assert min_chars == 1500
    assert max_chars == 1750
