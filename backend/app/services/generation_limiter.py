"""Redis-backed generation queue and concurrency gates.

Scaling model:
- CELERY_POOL and CELERY_CONCURRENCY are process-level environment settings.
  Change them in Railway Variables/.env/systemd and restart the worker.
- GENERATION_GLOBAL_CONCURRENCY is the runtime semaphore for active generation
  jobs across all users. It should never exceed the worker capacity you have
  actually deployed.
- GENERATION_PER_USER_CONCURRENCY is intentionally fixed to 1 for now. The DB
  gate below keeps a user's second textbook queued while their older textbook is
  pending/reviewing/generating.
- CHROMA_MODE=local_shared is forced back to one global job when Celery is
  scaled above one, because multiple workers sharing the same embedded Chroma
  directory is not a safe production scale path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.textbook import Textbook, TextbookStatus
from app.services.chroma_runtime import CHROMA_LOCAL_SHARED, chroma_mode
from app.services.runtime_config import get_runtime_config
from app.utils.log_config import setup_logger

logger = setup_logger(name="GenerationLimiter", logfile="logs/celery_tasks.log")

_redis_client: Any | None = None
_redis_failed_until = 0.0
_REDIS_RETRY_AFTER_SECONDS = 30.0
_LOCK_TTL_SECONDS = 2 * 60 * 60


class GenerationSlotUnavailable(RuntimeError):
    def __init__(self, reason: str, retry_seconds: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_seconds = retry_seconds


@dataclass
class GenerationLease:
    token: str
    global_key: str = "generation:active:global"

    def release(self) -> None:
        if self.token.startswith("local-"):
            return
        client = _get_redis_client()
        if client is None:
            return
        try:
            client.zrem(self.global_key, self.token)
        except Exception as exc:
            logger.warning("Could not release generation lease %s: %s", self.token, exc)


def _runtime_int(key: str, default: int, minimum: int = 1) -> int:
    value = get_runtime_config(key, required=False)
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def queue_retry_seconds() -> int:
    return _runtime_int(
        "GENERATION_QUEUE_RETRY_SECONDS",
        settings.GENERATION_QUEUE_RETRY_SECONDS,
        minimum=5,
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
        logger.warning("Redis generation limiter unavailable: %s", exc)
        return None


async def _has_older_active_textbook(db: AsyncSession, textbook: Textbook) -> bool:
    rows = await db.execute(
        select(Textbook.id, Textbook.progress_data)
        .where(
            Textbook.user_id == textbook.user_id,  # type: ignore[arg-type]
            Textbook.id != textbook.id,  # type: ignore[arg-type]
            Textbook.status.in_([TextbookStatus.PENDING.value, TextbookStatus.GENERATING.value]),
            Textbook.created_at <= textbook.created_at,  # type: ignore[arg-type]
        )
        .order_by(Textbook.created_at.asc(), Textbook.id.asc())
        .limit(5)
    )
    for _, progress_data in rows.all():
        phase = ""
        if isinstance(progress_data, dict):
            phase = str(progress_data.get("phase") or "")
        if phase in {"", "queued", "planning", "reviewing", "generating"}:
            return True
    return False


def _acquire_global_slot(textbook_id: int) -> GenerationLease | None:
    global_limit = _runtime_int(
        "GENERATION_GLOBAL_CONCURRENCY",
        settings.GENERATION_GLOBAL_CONCURRENCY,
    )
    if settings.CELERY_CONCURRENCY > 1 and chroma_mode() == CHROMA_LOCAL_SHARED:
        logger.warning(
            "Forcing generation global concurrency to 1 because CHROMA_MODE=local_shared "
            "with CELERY_CONCURRENCY=%s",
            settings.CELERY_CONCURRENCY,
        )
        global_limit = 1
    if global_limit <= 1 and settings.CELERY_CONCURRENCY <= 1:
        return GenerationLease(token=f"local-single:{textbook_id}")

    client = _get_redis_client()
    if client is None:
        if global_limit <= 1:
            return GenerationLease(token=f"local-fallback:{textbook_id}")
        return None

    key = "generation:active:global"
    token = f"textbook:{textbook_id}:{uuid.uuid4().hex}"
    now = time.time()
    expires_at = now + _LOCK_TTL_SECONDS
    script = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
    local active = redis.call('ZCARD', KEYS[1])
    if active >= tonumber(ARGV[2]) then
      return 0
    end
    redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
    redis.call('EXPIRE', KEYS[1], ARGV[5])
    return 1
    """
    try:
        acquired = client.eval(script, 1, key, now, global_limit, expires_at, token, _LOCK_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Redis generation limiter failed: %s", exc)
        return None
    if acquired:
        return GenerationLease(token=token, global_key=key)
    return None


async def acquire_generation_slot(db: AsyncSession, textbook: Textbook) -> GenerationLease:
    retry_seconds = queue_retry_seconds()
    if await _has_older_active_textbook(db, textbook):
        raise GenerationSlotUnavailable(
            "User already has an active textbook; queued until that textbook finishes.",
            retry_seconds,
        )

    lease = _acquire_global_slot(int(textbook.id))  # type: ignore[arg-type]
    if lease is None:
        raise GenerationSlotUnavailable(
            "Global generation limit reached; queued until a worker slot is free.",
            retry_seconds,
        )
    return lease
