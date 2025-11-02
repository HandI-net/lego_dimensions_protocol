"""Tests covering timeout handling in the RFID tag tracker."""

from pathlib import Path
import sys

import logging
import threading

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.rfid import TagTracker


class _TimeoutGateway:
    def __init__(self, *, raises: Exception | None = None):
        self._raises = raises

    def read_packet(self, timeout=None):  # noqa: D401 - signature matches Gateway
        if self._raises is not None:
            raise self._raises
        return None

    def is_timeout_error(self, exc: Exception) -> bool:  # pragma: no cover - helper
        return isinstance(exc, type(self._raises)) if self._raises else False


def test_tagtracker_logs_timeout_when_gateway_returns_none(caplog):
    gateway = _TimeoutGateway()
    tracker = TagTracker(gateway, poll_timeout=123, auto_start=False)

    with caplog.at_level(logging.DEBUG):
        assert tracker.poll_once() is None

    assert any(
        record.levelno == logging.DEBUG
        and "RFID poll timed out after 123ms" in record.getMessage()
        for record in caplog.records
    )


def test_tagtracker_swallows_gateway_timeout_exception(caplog):
    timeout_exc = TimeoutError("Operation timed out")
    gateway = _TimeoutGateway(raises=timeout_exc)
    tracker = TagTracker(gateway, poll_timeout=77, auto_start=False)

    with caplog.at_level(logging.DEBUG):
        assert tracker.poll_once() is None

    assert any(
        record.levelno == logging.DEBUG
        and "RFID poll timed out after 77ms" in record.getMessage()
        for record in caplog.records
    )


def test_tagtracker_propagates_unexpected_errors():
    class _BoomGateway(_TimeoutGateway):
        def is_timeout_error(self, exc: Exception) -> bool:
            return False

    gateway = _BoomGateway(raises=RuntimeError("usb disconnected"))
    tracker = TagTracker(gateway, auto_start=False)

    with pytest.raises(RuntimeError):
        tracker.poll_once()


def test_tagtracker_surfaces_worker_thread_errors():
    class _WorkerFailGateway(_TimeoutGateway):
        def __init__(self) -> None:
            super().__init__()
            self._worker_triggered = threading.Event()

        def read_packet(self, timeout=None):  # noqa: D401 - signature matches Gateway
            if threading.current_thread().name == "TagTracker":
                self._worker_triggered.set()
                raise RuntimeError("portal disconnected")
            return None

        def is_timeout_error(self, exc: Exception) -> bool:
            return False

    gateway = _WorkerFailGateway()
    tracker = TagTracker(gateway, auto_start=True)

    try:
        assert gateway._worker_triggered.wait(1), "worker thread did not attempt read"
        events = tracker.iter_events()
        with pytest.raises(RuntimeError):
            next(events)
    finally:
        tracker.close()
