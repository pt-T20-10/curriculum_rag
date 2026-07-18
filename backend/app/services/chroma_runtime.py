"""Runtime helpers for Chroma storage isolation.

Chroma scale modes:
- local_shared: one embedded persistent directory. Use only for local dev or a
  single generation worker.
- local_per_job: isolated embedded directory per textbook run. This is the
  Railway smoke-test path for two different users running at the same time.
- http: external Chroma service. This is the intended path before raising
  Celery/global generation concurrency to medium production levels.

Cleanup is deliberately constrained to CHROMA_RUNS_DIR so a bad runtime config
cannot delete arbitrary host paths.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.runtime_config import get_runtime_config
from app.utils.log_config import setup_logger

logger = setup_logger(name="ChromaRuntime", logfile="logs/agents.log")

CHROMA_LOCAL_SHARED = "local_shared"
CHROMA_LOCAL_PER_JOB = "local_per_job"
CHROMA_HTTP = "http"
CHROMA_MODES = {CHROMA_LOCAL_SHARED, CHROMA_LOCAL_PER_JOB, CHROMA_HTTP}


def chroma_mode() -> str:
    value = str(get_runtime_config("CHROMA_MODE", required=False) or settings.CHROMA_MODE)
    return value if value in CHROMA_MODES else CHROMA_LOCAL_SHARED


def chroma_runs_dir() -> Path:
    configured = str(get_runtime_config("CHROMA_RUNS_DIR", required=False) or settings.CHROMA_RUNS_DIR)
    path = Path(configured)
    if not path.is_absolute():
        path = settings.BASE_DIR / path
    return path


def rag_persist_dir_for_textbook(textbook_id: int, started_at: int | None = None) -> str | None:
    if chroma_mode() != CHROMA_LOCAL_PER_JOB:
        return None
    stamp = started_at or 0
    return str(chroma_runs_dir() / f"textbook_{int(textbook_id)}_{stamp}")


def effective_chroma_persist_dir(rag_persist_dir: Any = None) -> Path:
    if chroma_mode() == CHROMA_LOCAL_PER_JOB and rag_persist_dir:
        path = Path(str(rag_persist_dir))
        if not path.is_absolute():
            path = settings.BASE_DIR / path
        return path
    return settings.CHROMA_DB_DIR


def chroma_vector_store_kwargs(rag_persist_dir: Any = None) -> dict[str, Any]:
    mode = chroma_mode()
    if mode == CHROMA_HTTP:
        return {
            "host": str(get_runtime_config("CHROMA_HTTP_HOST", required=False) or settings.CHROMA_HTTP_HOST),
            "port": int(get_runtime_config("CHROMA_HTTP_PORT", required=False) or settings.CHROMA_HTTP_PORT),
        }
    return {"persist_directory": str(effective_chroma_persist_dir(rag_persist_dir))}


def cleanup_rag_persist_dir(rag_persist_dir: Any) -> bool:
    if chroma_mode() != CHROMA_LOCAL_PER_JOB or not rag_persist_dir:
        return False

    target = Path(str(rag_persist_dir)).resolve()
    root = chroma_runs_dir().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        logger.warning("Refusing to cleanup Chroma path outside CHROMA_RUNS_DIR: %s", target)
        return False

    if not target.exists():
        return False
    try:
        shutil.rmtree(target)
        logger.info("Cleaned per-job Chroma directory: %s", target)
        return True
    except Exception as exc:
        logger.warning("Could not cleanup per-job Chroma directory '%s': %s", target, exc)
        return False
