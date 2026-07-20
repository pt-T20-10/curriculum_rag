"""In-process background task manager for textbook generation.

This replaces Celery/Redis for the small single-process deployment profile.
Task progress remains durable in MySQL via ``textbooks.progress_data``; this
manager only owns the live in-memory execution state.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.textbook import Textbook, TextbookStatus
from app.utils import stop_signal, task_registry
from app.utils.log_config import setup_logger


TaskTarget = Callable[..., dict[str, Any]]

TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_CANCEL_REQUESTED = "cancel_requested"
TASK_CANCELLED = "cancelled"

_TERMINAL_STATUSES = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}

logger = setup_logger(name="ServerTaskManager", logfile="logs/server_tasks.log")


@dataclass
class ServerTaskRecord:
    task_id: str
    textbook_id: int
    kind: str
    status: str = TASK_QUEUED
    error_message: str = ""
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    future: Future | None = field(default=None, repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "textbook_id": self.textbook_id,
            "kind": self.kind,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class ServerTaskManager:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers or 1)),
            thread_name_prefix="textbook-task",
        )
        self._lock = threading.RLock()
        self._records: dict[str, ServerTaskRecord] = {}
        self._task_by_textbook: dict[int, str] = {}

    def submit(
        self,
        *,
        textbook_id: int,
        kind: str,
        target: TaskTarget,
        args: tuple[Any, ...] = (),
        task_id: str | None = None,
    ) -> str:
        task_id = task_id or self.new_task_id()
        record = ServerTaskRecord(
            task_id=task_id,
            textbook_id=int(textbook_id),
            kind=kind,
        )
        with self._lock:
            self._records[task_id] = record
            self._task_by_textbook[int(textbook_id)] = task_id
        task_registry.store(int(textbook_id), task_id)
        record.future = self._executor.submit(
            self._run_task,
            task_id,
            target,
            args,
        )
        logger.info("Queued server task %s for textbook %s (%s)", task_id, textbook_id, kind)
        return task_id

    def new_task_id(self) -> str:
        return uuid.uuid4().hex

    def get(self, task_id: str) -> ServerTaskRecord | None:
        with self._lock:
            return self._records.get(str(task_id))

    def get_for_textbook(self, textbook_id: int) -> ServerTaskRecord | None:
        with self._lock:
            task_id = self._task_by_textbook.get(int(textbook_id))
            return self._records.get(task_id) if task_id else None

    def request_stop(self, textbook_id: int) -> bool:
        textbook_id = int(textbook_id)
        stop_signal.request_stop_for(textbook_id)
        record = self.get_for_textbook(textbook_id)
        if not record:
            return False
        with self._lock:
            if record.status == TASK_QUEUED:
                record.status = TASK_CANCEL_REQUESTED
                cancelled = bool(record.future and record.future.cancel())
                if cancelled:
                    record.status = TASK_CANCELLED
                    record.finished_at = datetime.utcnow()
                    task_registry.delete(textbook_id)
                    stop_signal.clear_for(textbook_id)
                return True
            if record.status not in _TERMINAL_STATUSES:
                record.status = TASK_CANCEL_REQUESTED
                return True
        return False

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_task(
        self,
        task_id: str,
        target: TaskTarget,
        args: tuple[Any, ...],
    ) -> dict[str, Any]:
        record = self.get(task_id)
        if not record:
            return {"status": "error", "error": "Task record not found"}
        with self._lock:
            if record.status == TASK_CANCEL_REQUESTED:
                record.status = TASK_CANCELLED
                record.finished_at = datetime.utcnow()
                return {"status": "cancelled"}
            record.status = TASK_RUNNING
            record.started_at = datetime.utcnow()

        try:
            stop_signal.clear_for(record.textbook_id)
            result = target(record.textbook_id, task_id, *args)
            if not isinstance(result, dict):
                result = {"status": "success", "result": result}
            with self._lock:
                record.result = result
                if record.status == TASK_CANCEL_REQUESTED or result.get("status") == "stopped":
                    record.status = TASK_CANCELLED
                elif result.get("status") == "error":
                    record.status = TASK_FAILED
                    record.error_message = str(result.get("error") or result.get("message") or "")
                else:
                    record.status = TASK_COMPLETED
                record.finished_at = datetime.utcnow()
            return result
        except Exception as exc:
            logger.error("Server task %s failed: %s", task_id, exc, exc_info=True)
            with self._lock:
                record.status = TASK_FAILED
                record.error_message = str(exc)
                record.finished_at = datetime.utcnow()
            return {"status": "error", "error": str(exc)}
        finally:
            stop_signal.clear_current()
            task_registry.delete(record.textbook_id)


server_task_manager = ServerTaskManager(
    max_workers=getattr(settings, "SERVER_TASK_MAX_WORKERS", 1),
)


async def mark_interrupted_textbook_tasks() -> int:
    """Mark live tasks from a previous server process as interrupted."""
    interrupted = 0
    active_phases = {"queued", "planning", "generating", "stopping"}
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Textbook).where(
                Textbook.task_id.is_not(None),
                Textbook.status.in_([
                    TextbookStatus.PENDING.value,
                    TextbookStatus.GENERATING.value,
                ]),
            )
        )
        for textbook in rows.scalars().all():
            progress_data = dict(textbook.progress_data or {})  # type: ignore[arg-type]
            phase = str(progress_data.get("phase") or "")
            if phase not in active_phases:
                continue
            message = "Server restarted before the background task completed."
            progress_data.update({
                "phase": "idle",
                "status_text": message,
                "error_message": message,
            })
            textbook.status = TextbookStatus.FAILED.value  # type: ignore[assignment]
            textbook.error_message = message  # type: ignore[assignment]
            textbook.progress_data = progress_data  # type: ignore[assignment]
            textbook.task_id = None  # type: ignore[assignment]
            interrupted += 1
        if interrupted:
            await db.commit()
    return interrupted
