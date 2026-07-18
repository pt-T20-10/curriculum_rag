"""
Runtime configuration resolver.

External service credentials are resolved DB-first from system_config, then
fall back to pydantic Settings/.env. Bootstrap values such as MYSQL_*,
REDIS_*, and SECRET_KEY intentionally remain environment-only.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings


logger = logging.getLogger("RuntimeConfig")

MASKED_VALUE = "••••••••"
_CACHE_TTL_SECONDS = 30
_cache: dict[str, tuple[float, Any]] = {}
_engine: Engine | None = None
_lock = RLock()
_database_lookup_enabled: ContextVar[bool] = ContextVar(
    "runtime_config_database_lookup_enabled",
    default=True,
)
_runtime_overrides: ContextVar[dict[str, Any]] = ContextVar(
    "runtime_config_overrides",
    default={},
)


class RuntimeConfigError(RuntimeError):
    """Raised when a required runtime setting is missing from DB and .env."""


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


def _decode(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == MASKED_VALUE


def _read_db_value(key: str) -> Any:
    try:
        with _get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT value FROM system_config WHERE `key` = :key LIMIT 1"),
                {"key": key},
            ).first()
    except Exception as exc:
        logger.warning("DB runtime config lookup failed for %s: %s", key, exc)
        return None

    if not row:
        return None
    return _decode(row[0])


def invalidate_runtime_config_cache() -> None:
    """Clear cached DB-first runtime config values after admin updates."""
    with _lock:
        _cache.clear()
    try:
        from app.config import get_embedding_model

        if hasattr(get_embedding_model, "cache_clear"):
            get_embedding_model.cache_clear()
    except Exception as exc:
        logger.debug("Could not clear embedding model cache: %s", exc)
    try:
        from app.services.textbook import retriever

        retriever._chunk_classifier = None
        retriever._retriever_instances.clear()
    except Exception as exc:
        logger.debug("Could not clear retriever runtime caches: %s", exc)


@contextmanager
def environment_only_runtime_config() -> Iterator[None]:
    """Resolve runtime values from Settings/.env without touching MySQL.

    The regular web and Celery paths retain DB-first configuration. Standalone
    commands can use this context to avoid requiring application infrastructure.
    """
    token = _database_lookup_enabled.set(False)
    with _lock:
        _cache.clear()
    try:
        yield
    finally:
        _database_lookup_enabled.reset(token)
        with _lock:
            _cache.clear()


def get_runtime_config(key: str, required: bool = False) -> Any:
    """
    Resolve a runtime config value using DB-first fallback semantics.

    Order:
        1. system_config table
        2. Settings/.env
        3. RuntimeConfigError when required=True
    """
    overrides = _runtime_overrides.get()
    if key in overrides and not _is_missing(overrides[key]):
        return overrides[key]

    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            value = cached[1]
        else:
            db_value = _read_db_value(key) if _database_lookup_enabled.get() else None
            value = db_value if not _is_missing(db_value) else getattr(settings, key, None)
            _cache[key] = (now, value)

    if required and _is_missing(value):
        raise RuntimeConfigError(
            f"{key} is required but missing. Tried system_config first, "
            "then Settings/.env fallback."
        )
    return value


@contextmanager
def runtime_config_overrides(overrides: dict[str, Any] | None) -> Iterator[None]:
    """Temporarily prefer explicit runtime values for the current request/job."""
    current = dict(_runtime_overrides.get())
    if overrides:
        current.update({k: v for k, v in overrides.items() if not _is_missing(v)})
    token = _runtime_overrides.set(current)
    try:
        yield
    finally:
        _runtime_overrides.reset(token)


def get_api_key(key: str, required: bool = True) -> str:
    """Resolve a credential-like setting as a string."""
    value = get_runtime_config(key, required=required)
    return "" if _is_missing(value) else str(value)


def get_runtime_config_with_overrides(
    key: str,
    overrides: dict[str, Any] | None = None,
    required: bool = False,
) -> Any:
    """
    Resolve runtime config with an explicit per-request/user override layer.

    This prepares BYOK plumbing without exposing user secret storage yet:
    callers can pass already-authorized, already-decrypted overrides and this
    helper falls back to the existing DB-first system config resolver.
    """
    if overrides and key in overrides and not _is_missing(overrides[key]):
        return overrides[key]
    return get_runtime_config(key, required=required)


def get_api_key_with_overrides(
    key: str,
    overrides: dict[str, Any] | None = None,
    required: bool = True,
) -> str:
    """Resolve a credential-like setting with optional per-request overrides."""
    value = get_runtime_config_with_overrides(key, overrides=overrides, required=required)
    return "" if _is_missing(value) else str(value)
