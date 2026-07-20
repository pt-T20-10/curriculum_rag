"""In-process registry mapping textbook_id -> active server task_id."""

from __future__ import annotations

import threading

_lock = threading.RLock()
_tasks_by_textbook: dict[int, str] = {}


def store(textbook_id: int, task_id: str) -> None:
    with _lock:
        _tasks_by_textbook[int(textbook_id)] = str(task_id)


def get(textbook_id: int) -> str | None:
    with _lock:
        return _tasks_by_textbook.get(int(textbook_id))


def delete(textbook_id: int) -> None:
    with _lock:
        _tasks_by_textbook.pop(int(textbook_id), None)
