"""Shared stop signal for graceful cancellation across all pipeline layers."""
import threading

STOP     = threading.Event()
STOPPING = threading.Event()  # set immediately on user request, before STOP propagates


def request_stop() -> None:
    STOPPING.set()
    STOP.set()


def clear() -> None:
    STOP.clear()
    STOPPING.clear()


def is_stopped() -> bool:
    return STOP.is_set()


def is_stopping() -> bool:
    """True from the moment user clicks Stop, until workflow fully resets."""
    return STOPPING.is_set()