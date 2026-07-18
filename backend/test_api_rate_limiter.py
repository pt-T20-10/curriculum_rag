from __future__ import annotations

import pytest

from app.services import api_rate_limiter


def test_rate_limiter_disabled_bypasses_wait(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(api_rate_limiter, "_runtime_bool", lambda key, default: False)
    monkeypatch.setattr(api_rate_limiter, "wait_for_api_slot", lambda **kwargs: calls.append("wait"))

    result = api_rate_limiter.rate_limited_call(lambda: "ok", bucket="chat")

    assert result == "ok"
    assert calls == []


def test_rate_limiter_retries_openai_429(monkeypatch) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    monkeypatch.setattr(api_rate_limiter, "_runtime_bool", lambda key, default: True)
    monkeypatch.setattr(api_rate_limiter, "_runtime_int", lambda key, default: 1)
    monkeypatch.setattr(api_rate_limiter, "_runtime_float", lambda key, default: 0.0)
    monkeypatch.setattr(api_rate_limiter, "wait_for_api_slot", lambda **kwargs: None)
    monkeypatch.setattr(api_rate_limiter, "_sleep_with_jitter", lambda seconds, provider: sleeps.append(seconds))

    def flaky_call() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("429 Too Many Requests")
        return "ok"

    assert api_rate_limiter.rate_limited_call(flaky_call, bucket="chat") == "ok"
    assert attempts["count"] == 2
    assert sleeps == [0.1]


def test_rate_limiter_does_not_retry_non_rate_limit_errors(monkeypatch) -> None:
    attempts = {"count": 0}

    monkeypatch.setattr(api_rate_limiter, "_runtime_bool", lambda key, default: True)
    monkeypatch.setattr(api_rate_limiter, "_runtime_int", lambda key, default: 3)
    monkeypatch.setattr(api_rate_limiter, "_runtime_float", lambda key, default: 0.0)
    monkeypatch.setattr(api_rate_limiter, "wait_for_api_slot", lambda **kwargs: None)

    def failing_call() -> str:
        attempts["count"] += 1
        raise ValueError("bad prompt")

    with pytest.raises(ValueError, match="bad prompt"):
        api_rate_limiter.rate_limited_call(failing_call, bucket="chat")

    assert attempts["count"] == 1


def test_embedding_calls_apply_post_call_cooldown(monkeypatch) -> None:
    sleeps: list[float] = []

    monkeypatch.setattr(api_rate_limiter, "_runtime_bool", lambda key, default: True)
    monkeypatch.setattr(api_rate_limiter, "_runtime_int", lambda key, default: 0)
    monkeypatch.setattr(api_rate_limiter, "_runtime_float", lambda key, default: 0.0)
    monkeypatch.setattr(api_rate_limiter, "wait_for_api_slot", lambda **kwargs: None)
    monkeypatch.setattr(api_rate_limiter, "_sleep_with_jitter", lambda seconds, provider: sleeps.append(seconds))

    assert api_rate_limiter.rate_limited_call(lambda: "ok", bucket="embedding") == "ok"
    assert sleeps == [1.0]
