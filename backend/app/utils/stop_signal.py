"""Shared stop signal for graceful cancellation across all pipeline layers."""


class WorkflowStoppedException(Exception):
    """Raised by _with_stop_check to immediately exit the LangGraph stream.

    Returning {} from a stopped node leaves routing functions running against
    unchanged state, causing an infinite loop until the recursion limit is hit.
    Raising this exception breaks the for-event-in-stream loop cleanly.
    """
import threading
import redis as _redis_module
from redis.connection import ConnectionPool

STOP     = threading.Event()
STOPPING = threading.Event()  # set immediately on user request, before STOP propagates

# Thread-local storage — Celery task sets textbook_id here before asyncio.run()
_local = threading.local()

# Redis connection pool — one pool per process, shared across all calls
_pool: ConnectionPool | None = None


def _r() -> _redis_module.Redis:
    global _pool
    if _pool is None:
        from app.config import settings
        _pool = ConnectionPool.from_url(
            settings.REDIS_CONNECTION_URL,
            decode_responses=True,
            max_connections=10,
        )
    return _redis_module.Redis(connection_pool=_pool)


def set_current(textbook_id: int) -> None:
    """Bind a textbook_id to the current Celery worker thread.

    Must be called in the Celery task function BEFORE asyncio.run().
    LangGraph coroutines run in the same OS thread, so threading.local()
    is visible to every node wrapper without touching AgentState.
    """
    _local.textbook_id = textbook_id


def request_stop() -> None:
    STOPPING.set()
    STOP.set()


def clear() -> None:
    STOP.clear()
    STOPPING.clear()


def is_stopped() -> bool:
    """Check stop for the current task thread.

    If a textbook_id was bound via set_current(), checks the Redis key
    (cross-process safe).  Falls back to the threading.Event for legacy
    single-process usage.
    """
    textbook_id = getattr(_local, "textbook_id", None)
    if textbook_id is not None:
        return _r().exists(f"textbook_stop:{textbook_id}") == 1
    return STOP.is_set()


def is_stopping() -> bool:
    """True from the moment user clicks Stop, until workflow fully resets."""
    return STOPPING.is_set()


# ---------------------------------------------------------------------------
# Redis-based per-textbook stop — works across FastAPI / Celery processes
# ---------------------------------------------------------------------------

def request_stop_for(textbook_id: int) -> None:
    """Set a cross-process stop flag for a specific textbook (TTL 1 h)."""
    _r().setex(f"textbook_stop:{textbook_id}", 3600, "1")


def is_stopped_for(textbook_id: int) -> bool:
    """Return True if a stop has been requested for this textbook."""
    return _r().exists(f"textbook_stop:{textbook_id}") == 1


def clear_for(textbook_id: int) -> None:
    """Remove the stop flag so a fresh run is not blocked."""
    _r().delete(f"textbook_stop:{textbook_id}")
