import json

from app.services.textbook import validator
from app.services.textbook.validator import _unexplained_topic_noise


def _result(core_topic: str, user_requirements: str = "") -> dict:
    return {
        "valid": True,
        "core_topic": core_topic,
        "user_requirements": user_requirements,
    }


def test_rejects_trailing_random_letters() -> None:
    assert _unexplained_topic_noise(
        "Lập trình Python abc",
        _result("Lập trình Python"),
    ) == ["abc"]


def test_rejects_trailing_meaningless_number() -> None:
    assert _unexplained_topic_noise(
        "Lập trình Python 123",
        _result("Lập trình Python"),
    ) == ["123"]


def test_allows_numbers_when_part_of_core_topic() -> None:
    assert _unexplained_topic_noise(
        "Toán lớp 10",
        _result("Toán lớp 10"),
    ) == []
    assert _unexplained_topic_noise(
        "Lập trình Python 3",
        _result("Lập trình Python 3"),
    ) == []


def test_allows_language_control_phrase_removed_from_core_topic() -> None:
    assert _unexplained_topic_noise(
        "Lập trình Python cơ bản bằng tiếng Anh",
        _result("Basic Python Programming"),
    ) == []


def test_validate_topic_rejects_noise_even_if_llm_accepts(monkeypatch) -> None:
    class FakeResponse:
        content = json.dumps({
            "valid": True,
            "reason": "",
            "suggestion": "",
            "content_type": "technical",
            "core_topic": "Lập trình Python",
            "user_requirements": "",
            "input_language": "vi",
            "requested_language": "",
            "target_language": "vi",
            "language_source": "input",
        })

    class FakeChatGroq:
        def __init__(self, **kwargs):
            pass

        def invoke(self, prompt: str) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(validator, "ChatGroq", FakeChatGroq)
    monkeypatch.setattr(validator, "get_api_key", lambda key: "fake-key")

    result = validator.validate_topic("Lập trình Python abc", ui_language="vi")

    assert result["valid"] is False
    assert "không liên quan" in result["reason"]
