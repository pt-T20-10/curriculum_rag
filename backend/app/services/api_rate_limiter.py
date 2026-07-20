"""Shared API throttling helpers for external model providers.

The limiter is intentionally small and synchronous because the textbook
pipeline calls LangChain/OpenAI synchronously from background task threads.
When Redis is available and explicitly enabled, processes that share the same
Redis URL also share the same throttle bucket. If Redis is unavailable, the
process falls back to a local in-memory throttle so a single worker still
behaves politely.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, TypeVar

from app.config import settings
from app.services.runtime_config import get_runtime_config
from app.utils.log_config import setup_logger

logger = setup_logger(name="ApiRateLimiter", logfile="logs/api_rate_limiter.log")

T = TypeVar("T")

_local_lock = threading.RLock()
_local_next_allowed: dict[str, float] = {}
_redis_client: Any | None = None
_redis_failed_until = 0.0
_REDIS_RETRY_AFTER_SECONDS = 30.0
_usage_context: ContextVar[dict[str, Any]] = ContextVar("api_usage_context", default={})
_usage_lock = threading.RLock()
_usage_summaries: dict[str, dict[str, Any]] = {}

_MODEL_PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "text-embedding-3-small": (0.02, 0.0),
}


@contextmanager
def api_usage_context(**values: Any):
    """Attach run/node metadata to API calls made inside the context."""
    current = dict(_usage_context.get())
    current.update({k: v for k, v in values.items() if v is not None})
    token = _usage_context.set(current)
    try:
        yield
    finally:
        _usage_context.reset(token)


def reset_api_usage_summary(run_id: str) -> None:
    with _usage_lock:
        _usage_summaries.pop(run_id, None)


def get_api_usage_summary(run_id: str) -> dict[str, Any]:
    with _usage_lock:
        return deepcopy(_usage_summaries.get(run_id, _new_usage_summary(run_id)))


def _new_usage_summary(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "total_calls": 0,
        "total_estimated_usd": 0.0,
        "premium_chat_calls": 0,
        "cheap_chat_calls": 0,
        "other_chat_calls": 0,
        "by_bucket": {},
        "by_model": {},
        "by_agent": {},
        "by_node": {},
    }


def _runtime_bool(key: str, default: bool) -> bool:
    value = get_runtime_config(key, required=False)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _runtime_float(key: str, default: float) -> float:
    value = get_runtime_config(key, required=False)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _runtime_int(key: str, default: int) -> int:
    value = get_runtime_config(key, required=False)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _infer_model(runnable: Any, metadata: dict[str, Any]) -> str:
    if metadata.get("model"):
        return str(metadata["model"])
    for attr in ("model_name", "model", "deployment_name"):
        value = getattr(runnable, attr, None)
        if value:
            return str(value)
    return ""


def _usage_value(raw: Any, *keys: str) -> int:
    for key in keys:
        if isinstance(raw, dict) and key in raw:
            try:
                return int(raw[key] or 0)
            except (TypeError, ValueError):
                return 0
        value = getattr(raw, key, None)
        if value is not None:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _extract_usage(result: Any) -> dict[str, int]:
    usage = getattr(result, "usage", None)
    if usage is None:
        usage = getattr(result, "usage_metadata", None)
    if usage is None:
        response_metadata = getattr(result, "response_metadata", None)
        if isinstance(response_metadata, dict):
            usage = response_metadata.get("token_usage") or response_metadata.get("usage")
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _estimate_usd(model: str, usage: dict[str, int]) -> float:
    prices = _MODEL_PRICES_PER_MILLION.get(model)
    if not prices:
        return 0.0
    input_price, output_price = prices
    return (
        (usage.get("input_tokens", 0) / 1_000_000) * input_price
        + (usage.get("output_tokens", 0) / 1_000_000) * output_price
    )


def _bump_bucket(summary: dict[str, Any], bucket_name: str, key: str, estimated_usd: float) -> None:
    if not key:
        key = "unknown"
    bucket = summary[bucket_name].setdefault(
        key,
        {"calls": 0, "estimated_usd": 0.0},
    )
    bucket["calls"] += 1
    bucket["estimated_usd"] = round(bucket["estimated_usd"] + estimated_usd, 8)


def _record_api_usage(
    *,
    provider: str,
    bucket: str,
    model: str,
    elapsed_seconds: float,
    metadata: dict[str, Any],
    result: Any,
) -> None:
    context = dict(_usage_context.get())
    merged = {**context, **metadata}
    run_id = str(merged.get("run_id") or merged.get("textbook_id") or "global")
    agent = str(merged.get("agent") or "")
    node = str(merged.get("node") or "")
    usage = _extract_usage(result)
    estimated_usd = _estimate_usd(model, usage)

    with _usage_lock:
        summary = _usage_summaries.setdefault(run_id, _new_usage_summary(run_id))
        summary["total_calls"] += 1
        summary["total_estimated_usd"] = round(
            summary["total_estimated_usd"] + estimated_usd,
            8,
        )
        if bucket == "chat":
            if model == settings.LLM_MODEL_PREMIUM:
                summary["premium_chat_calls"] += 1
            elif model == settings.LLM_MODEL_CHEAP:
                summary["cheap_chat_calls"] += 1
            else:
                summary["other_chat_calls"] += 1
        _bump_bucket(summary, "by_bucket", bucket, estimated_usd)
        _bump_bucket(summary, "by_model", model or f"{provider}:{bucket}", estimated_usd)
        _bump_bucket(summary, "by_agent", agent, estimated_usd)
        _bump_bucket(summary, "by_node", node, estimated_usd)

    logger.info(
        "API usage run=%s provider=%s bucket=%s model=%s agent=%s node=%s "
        "elapsed=%.3fs tokens(in=%s,out=%s,total=%s) estimated_usd=%.8f",
        run_id,
        provider,
        bucket,
        model or "unknown",
        agent or "unknown",
        node or "unknown",
        elapsed_seconds,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["total_tokens"],
        estimated_usd,
    )


def _execute_and_record(
    fn: Callable[[], T],
    *,
    provider: str,
    bucket: str,
    model: str = "",
    metadata: dict[str, Any] | None = None,
) -> T:
    started = time.monotonic()
    result = fn()
    elapsed = time.monotonic() - started
    _record_api_usage(
        provider=provider,
        bucket=bucket,
        model=model,
        elapsed_seconds=elapsed,
        metadata=metadata or {},
        result=result,
    )
    _sleep_after_api_call(provider=provider, bucket=bucket)
    return result


def _sleep_after_api_call(provider: str, bucket: str) -> None:
    """Apply a small post-call cooldown for bursty embedding batches."""
    if bucket != "embedding":
        return
    if not _runtime_bool(f"{provider.upper()}_RATE_LIMIT_ENABLED", False):
        return
    interval = _bucket_interval(provider, bucket)
    if provider.lower() == "openai":
        interval = max(interval, float(settings.OPENAI_EMBEDDING_MIN_INTERVAL_SECONDS))
    if interval <= 0:
        return
    logger.debug(
        "Post-call cooldown for %s %s bucket: %.2fs",
        provider,
        bucket,
        interval,
    )
    _sleep_with_jitter(interval, provider)


def _bucket_interval(provider: str, bucket: str) -> float:
    provider_key = provider.upper()
    bucket_key = bucket.upper()
    return max(
        0.0,
        _runtime_float(
            f"{provider_key}_{bucket_key}_MIN_INTERVAL_SECONDS",
            _runtime_float(f"{provider_key}_REQUEST_MIN_INTERVAL_SECONDS", 0.0),
        ),
    )


def _get_redis_client() -> Any | None:
    global _redis_client, _redis_failed_until
    now = time.monotonic()
    if _redis_failed_until > now:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis

        _redis_client = redis.Redis.from_url(
            settings.REDIS_CONNECTION_URL,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
            decode_responses=True,
        )
        _redis_client.ping()
        return _redis_client
    except Exception as exc:
        _redis_failed_until = now + _REDIS_RETRY_AFTER_SECONDS
        logger.warning("Redis shared API limiter unavailable; using local limiter: %s", exc)
        return None


def _sleep_with_jitter(wait_seconds: float, provider: str) -> None:
    jitter = _runtime_float(f"{provider.upper()}_RATE_LIMIT_JITTER_SECONDS", 0.0)
    if jitter > 0:
        wait_seconds += random.uniform(0.0, jitter)
    if wait_seconds > 0:
        time.sleep(wait_seconds)


def _acquire_local_slot(key: str, interval: float, provider: str) -> None:
    with _local_lock:
        now = time.monotonic()
        next_allowed = _local_next_allowed.get(key, now)
        wait_seconds = max(0.0, next_allowed - now)
        _local_next_allowed[key] = max(now, next_allowed) + interval

    _sleep_with_jitter(wait_seconds, provider)


def _acquire_redis_slot(key: str, interval: float, provider: str) -> bool:
    global _redis_failed_until
    client = _get_redis_client()
    if client is None:
        return False

    ttl_ms = max(1, int(interval * 1000))
    for _ in range(600):
        try:
            acquired = client.set(key, "1", nx=True, px=ttl_ms)
            if acquired:
                return True
            remaining_ms = client.pttl(key)
            wait_seconds = 0.1 if remaining_ms is None or remaining_ms < 0 else remaining_ms / 1000
            _sleep_with_jitter(min(max(wait_seconds, 0.05), max(interval, 0.1)), provider)
        except Exception as exc:
            _redis_failed_until = time.monotonic() + _REDIS_RETRY_AFTER_SECONDS
            logger.warning("Redis shared API limiter failed; falling back local: %s", exc)
            return False

    logger.warning("Redis shared API limiter waited too long for %s; proceeding local", key)
    return False


def wait_for_api_slot(provider: str = "openai", bucket: str = "chat") -> None:
    if not _runtime_bool(f"{provider.upper()}_RATE_LIMIT_ENABLED", False):
        return

    interval = _bucket_interval(provider, bucket)
    if interval <= 0:
        return

    key = f"api_rate_limit:{provider}:{bucket}"
    if _runtime_bool(f"{provider.upper()}_SHARED_RATE_LIMIT_ENABLED", True):
        if _acquire_redis_slot(key, interval, provider):
            return

    _acquire_local_slot(key, interval, provider)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = f"{exc.__class__.__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "ratelimit",
            "rate limit",
            "too many requests",
            "429",
            "resource_exhausted",
        )
    )


def rate_limited_call(
    fn: Callable[[], T],
    *,
    provider: str = "openai",
    bucket: str = "chat",
    model: str = "",
    metadata: dict[str, Any] | None = None,
) -> T:
    if not _runtime_bool(f"{provider.upper()}_RATE_LIMIT_ENABLED", False):
        return _execute_and_record(
            fn,
            provider=provider,
            bucket=bucket,
            model=model,
            metadata=metadata,
        )

    max_retries = max(0, _runtime_int(f"{provider.upper()}_RATE_LIMIT_MAX_RETRIES", 5))
    base = max(0.1, _runtime_float(f"{provider.upper()}_RATE_LIMIT_BACKOFF_BASE_SECONDS", 2.0))
    cap = max(base, _runtime_float(f"{provider.upper()}_RATE_LIMIT_BACKOFF_MAX_SECONDS", 60.0))

    for attempt in range(max_retries + 1):
        wait_for_api_slot(provider=provider, bucket=bucket)
        try:
            return _execute_and_record(
                fn,
                provider=provider,
                bucket=bucket,
                model=model,
                metadata=metadata,
            )
        except Exception as exc:
            if not _is_rate_limit_error(exc) or attempt >= max_retries:
                raise
            wait_seconds = min(cap, base * (2 ** attempt))
            logger.warning(
                "%s %s rate limit hit; retrying in %.1fs (attempt %s/%s): %s",
                provider,
                bucket,
                wait_seconds,
                attempt + 1,
                max_retries,
                exc,
            )
            _sleep_with_jitter(wait_seconds, provider)

    return _execute_and_record(
        fn,
        provider=provider,
        bucket=bucket,
        model=model,
        metadata=metadata,
    )


def rate_limited_invoke(
    runnable: Any,
    input_value: Any,
    *,
    provider: str = "openai",
    bucket: str = "chat",
    metadata: dict[str, Any] | None = None,
) -> Any:
    resolved_metadata = metadata or {}
    return rate_limited_call(
        lambda: runnable.invoke(input_value),
        provider=provider,
        bucket=bucket,
        model=_infer_model(runnable, resolved_metadata),
        metadata=resolved_metadata,
    )
