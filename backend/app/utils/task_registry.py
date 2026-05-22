"""Redis-based registry mapping textbook_id → active Celery task_id."""
import redis
from redis.connection import ConnectionPool

_TTL = 86_400  # 24 hours

_pool: ConnectionPool | None = None


def _r() -> redis.Redis:
    global _pool
    if _pool is None:
        from app.config import settings
        _pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=True,
            max_connections=10,
        )
    return redis.Redis(connection_pool=_pool)


def store(textbook_id: int, task_id: str) -> None:
    _r().setex(f"task:{textbook_id}", _TTL, task_id)


def get(textbook_id: int) -> str | None:
    return _r().get(f"task:{textbook_id}")  #type: ignore[return-value]


def delete(textbook_id: int) -> None:
    _r().delete(f"task:{textbook_id}")
