"""In-process graceful cancellation signals for textbook workflows."""

from __future__ import annotations

import threading


class WorkflowStoppedException(Exception):
    """Raised by graph node wrappers to exit LangGraph streaming cleanly."""


STOP = threading.Event()
STOPPING = threading.Event()

_local = threading.local()
_lock = threading.RLock()
_events: dict[int, threading.Event] = {}


def _event_for(textbook_id: int) -> threading.Event:
    with _lock:
        event = _events.get(textbook_id)
        if event is None:
            event = threading.Event()
            _events[textbook_id] = event
        return event


def set_current(textbook_id: int) -> None:
    """Bind a textbook id to the current worker thread."""
    _local.textbook_id = textbook_id


def clear_current() -> None:
    if hasattr(_local, "textbook_id"):
        delattr(_local, "textbook_id")


def request_stop() -> None:
    STOPPING.set()
    STOP.set()


def clear() -> None:
    STOP.clear()
    STOPPING.clear()


def is_stopped() -> bool:
    textbook_id = getattr(_local, "textbook_id", None)
    if textbook_id is not None:
        return is_stopped_for(int(textbook_id))
    return STOP.is_set()


def is_stopping() -> bool:
    textbook_id = getattr(_local, "textbook_id", None)
    if textbook_id is not None:
        return is_stopped_for(int(textbook_id))
    return STOPPING.is_set()


def request_stop_for(textbook_id: int) -> None:
    _event_for(int(textbook_id)).set()


def is_stopped_for(textbook_id: int) -> bool:
    with _lock:
        event = _events.get(int(textbook_id))
    return bool(event and event.is_set())


def clear_for(textbook_id: int) -> None:
    with _lock:
        _events.pop(int(textbook_id), None)
