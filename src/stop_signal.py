"""Shared stop signal for graceful cancellation across all pipeline layers."""
import threading

STOP = threading.Event()


def request_stop() -> None:
    STOP.set()


def clear() -> None:
    STOP.clear()


def is_stopped() -> bool:
    return STOP.is_set()
