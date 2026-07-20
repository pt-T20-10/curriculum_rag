from __future__ import annotations

import time
from threading import Event

from app.services.server_task_manager import (
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RUNNING,
    ServerTaskManager,
)
from app.utils import stop_signal, task_registry


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


def test_submit_task_runs_to_completed() -> None:
    manager = ServerTaskManager(max_workers=1)
    started = Event()
    release = Event()

    def target(textbook_id: int, task_id: str) -> dict:
        started.set()
        release.wait(timeout=1)
        return {"status": "success", "textbook_id": textbook_id, "task_id": task_id}

    try:
        task_id = manager.submit(textbook_id=101, kind="planning", target=target)

        assert task_id
        assert task_registry.get(101) == task_id
        _wait_until(lambda: manager.get(task_id).status == TASK_RUNNING)
        assert started.is_set()

        release.set()
        _wait_until(lambda: manager.get(task_id).status == TASK_COMPLETED)
        record = manager.get(task_id)
        assert record.result["textbook_id"] == 101
        assert task_registry.get(101) is None
    finally:
        release.set()
        manager.shutdown()
        stop_signal.clear_for(101)
        task_registry.delete(101)


def test_exception_marks_task_failed() -> None:
    manager = ServerTaskManager(max_workers=1)

    def target(textbook_id: int, task_id: str) -> dict:
        raise RuntimeError("boom")

    try:
        task_id = manager.submit(textbook_id=102, kind="planning", target=target)
        _wait_until(lambda: manager.get(task_id).status == TASK_FAILED)
        assert "boom" in manager.get(task_id).error_message
    finally:
        manager.shutdown()
        stop_signal.clear_for(102)
        task_registry.delete(102)


def test_cancel_queued_task() -> None:
    manager = ServerTaskManager(max_workers=1)
    release_first = Event()

    def blocking_target(textbook_id: int, task_id: str) -> dict:
        release_first.wait(timeout=1)
        return {"status": "success"}

    def queued_target(textbook_id: int, task_id: str) -> dict:
        return {"status": "success"}

    try:
        first_id = manager.submit(textbook_id=103, kind="planning", target=blocking_target)
        _wait_until(lambda: manager.get(first_id).status == TASK_RUNNING)

        queued_id = manager.submit(textbook_id=104, kind="planning", target=queued_target)
        assert manager.request_stop(104) is True
        _wait_until(lambda: manager.get(queued_id).status == TASK_CANCELLED)
        assert task_registry.get(104) is None
    finally:
        release_first.set()
        manager.shutdown()
        stop_signal.clear_for(103)
        stop_signal.clear_for(104)
        task_registry.delete(103)
        task_registry.delete(104)


def test_request_stop_running_task_sets_stop_flag() -> None:
    manager = ServerTaskManager(max_workers=1)

    def target(textbook_id: int, task_id: str) -> dict:
        _wait_until(lambda: stop_signal.is_stopped_for(textbook_id))
        return {"status": "stopped"}

    try:
        task_id = manager.submit(textbook_id=105, kind="generation", target=target)
        _wait_until(lambda: manager.get(task_id).status == TASK_RUNNING)

        assert manager.request_stop(105) is True
        _wait_until(lambda: manager.get(task_id).status == TASK_CANCELLED)
    finally:
        manager.shutdown()
        stop_signal.clear_for(105)
        task_registry.delete(105)
