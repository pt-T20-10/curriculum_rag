"""Shared API throttling helpers for external model providers.

The limiter is intentionally small and synchronous because the textbook
pipeline calls LangChain/OpenAI synchronously from Celery workers. When Redis is
available, local and hosted workers that share the same Redis URL also share the
same throttle bucket. If Redis is unavailable, the process falls back to a local
in-memory throttle so a single worker still behaves politely.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
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
) -> T:
    if not _runtime_bool(f"{provider.upper()}_RATE_LIMIT_ENABLED", False):
        return fn()

    max_retries = max(0, _runtime_int(f"{provider.upper()}_RATE_LIMIT_MAX_RETRIES", 5))
    base = max(0.1, _runtime_float(f"{provider.upper()}_RATE_LIMIT_BACKOFF_BASE_SECONDS", 2.0))
    cap = max(base, _runtime_float(f"{provider.upper()}_RATE_LIMIT_BACKOFF_MAX_SECONDS", 60.0))

    for attempt in range(max_retries + 1):
        wait_for_api_slot(provider=provider, bucket=bucket)
        try:
            return fn()
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

    return fn()


def rate_limited_invoke(
    runnable: Any,
    input_value: Any,
    *,
    provider: str = "openai",
    bucket: str = "chat",
) -> Any:
    return rate_limited_call(
        lambda: runnable.invoke(input_value),
        provider=provider,
        bucket=bucket,
    )
