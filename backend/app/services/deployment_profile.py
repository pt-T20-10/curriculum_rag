"""Deployment profile detection for admin setup guidance.

The profile is an operator-facing summary, not the source of truth for scaling.
Celery process capacity still comes from CELERY_POOL/CELERY_CONCURRENCY at
worker startup, while runtime limits and Chroma mode may come from Admin Config
or environment fallback. The Admin popup/banner uses this detector to make
misalignment visible immediately after login.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.chroma_runtime import CHROMA_HTTP, CHROMA_LOCAL_PER_JOB, CHROMA_LOCAL_SHARED


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def detect_deployment_profile(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify the active deployment into small, actionable scale profiles."""
    config = config or {}
    chroma_mode = str(config.get("CHROMA_MODE") or settings.CHROMA_MODE)
    celery_pool = str(config.get("CELERY_POOL") or settings.CELERY_POOL)
    celery_concurrency = _as_int(config.get("CELERY_CONCURRENCY"), settings.CELERY_CONCURRENCY)
    global_limit = _as_int(config.get("GENERATION_GLOBAL_CONCURRENCY"), settings.GENERATION_GLOBAL_CONCURRENCY)
    per_user_limit = _as_int(config.get("GENERATION_PER_USER_CONCURRENCY"), settings.GENERATION_PER_USER_CONCURRENCY)
    redis_shared = _as_bool(
        config.get("OPENAI_SHARED_RATE_LIMIT_ENABLED"),
        settings.OPENAI_SHARED_RATE_LIMIT_ENABLED,
    )
    has_key_pool = bool(str(config.get("OPENAI_API_KEYS") or settings.OPENAI_API_KEYS or "").strip())

    settings_snapshot = {
        "CHROMA_MODE": chroma_mode,
        "CELERY_POOL": celery_pool,
        "CELERY_CONCURRENCY": celery_concurrency,
        "GENERATION_GLOBAL_CONCURRENCY": global_limit,
        "GENERATION_PER_USER_CONCURRENCY": per_user_limit,
        "OPENAI_SHARED_RATE_LIMIT_ENABLED": redis_shared,
        "OPENAI_API_KEYS_CONFIGURED": has_key_pool,
    }
    signature = "|".join(f"{key}={value}" for key, value in settings_snapshot.items())

    if celery_concurrency > 1 and chroma_mode == CHROMA_LOCAL_SHARED:
        key = "misconfigured"
        severity = "danger"
        title = "Cấu hình production đang mâu thuẫn"
        summary = "Worker đang cho chạy song song nhưng Chroma vẫn dùng shared local path."
        recommended_action = "Đổi CHROMA_MODE=local_per_job cho Railway test 2 user, hoặc dùng CHROMA_MODE=http khi có Chroma server."
        max_parallel_jobs = 1
    elif chroma_mode == CHROMA_HTTP and celery_concurrency >= 5 and global_limit >= 5:
        key = "medium_ready"
        severity = "success"
        title = "Medium production ready"
        summary = "Cấu hình phù hợp để chạy nhiều user song song với Chroma server."
        recommended_action = "Theo dõi Redis limiter, key pool, RAM/CPU worker và quota provider khi tăng tải."
        max_parallel_jobs = min(celery_concurrency, global_limit)
    elif chroma_mode == CHROMA_LOCAL_PER_JOB and celery_concurrency >= 2 and global_limit >= 2 and per_user_limit == 1:
        key = "railway_test_2"
        severity = "info"
        title = "Railway test 2 tài khoản"
        summary = "Cấu hình phù hợp để 2 user khác nhau chạy giáo trình cùng lúc, mỗi user 1 giáo trình."
        recommended_action = "Giữ global concurrency ở 2; nếu crawl/embedding bị 429, đặt OPENAI_EMBEDDING_MIN_INTERVAL_SECONDS=2.0 và EMBEDDING_BATCH_SIZE=100."
        max_parallel_jobs = min(celery_concurrency, global_limit)
    else:
        key = "small_safe"
        severity = "warning"
        title = "Small safe production"
        summary = "Cấu hình an toàn cho deploy nhỏ: hệ thống xử lý 1 job generation tại một thời điểm."
        recommended_action = "Để test 2 tài khoản trên Railway, đặt CHROMA_MODE=local_per_job, CELERY_POOL=threads, CELERY_CONCURRENCY=2 và GENERATION_GLOBAL_CONCURRENCY=2."
        max_parallel_jobs = min(celery_concurrency, global_limit)

    return {
        "key": key,
        "severity": severity,
        "title": title,
        "summary": summary,
        "recommended_action": recommended_action,
        "max_parallel_jobs": max(1, max_parallel_jobs),
        "settings": settings_snapshot,
        "signature": signature,
    }
