"""Tests for reconnect and waiting behaviour in the USB gateway."""

from __future__ import annotations

import errno
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.gateway import (
    Gateway,
    PortalNotFoundError,
    _RECONNECT_DELAY_SECONDS,
)


class _DummyUSBError(Exception):
    def __init__(self, *, errno_value=None, backend_error_code=None, message="error"):
        super().__init__(message)
        self.errno = errno_value
        self.backend_error_code = backend_error_code


class _FailingWriteDevice:
    def write(self, endpoint, data, timeout=None):  # pragma: no cover - invoked via gateway
        raise _DummyUSBError(errno_value=errno.ENODEV)


class _RecordingWriteDevice:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bytes, int | None]] = []

    def write(self, endpoint, data, timeout=None):  # pragma: no cover - invoked via gateway
        self.calls.append((endpoint, bytes(data), timeout))


class _FailingReadDevice:
    def read(self, endpoint, length, timeout=None):  # pragma: no cover - invoked via gateway
        raise _DummyUSBError(errno_value=errno.ENODEV)


class _SuccessfulReadDevice:
    def __init__(self, data):
        self.data = data

    def read(self, endpoint, length, timeout=None):  # pragma: no cover - invoked via gateway
        return self.data


def test_connect_waits_until_device_available(monkeypatch):
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_connect_once(self):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PortalNotFoundError("missing")
        self.dev = object()

    monkeypatch.setattr(Gateway, "_connect_once", fake_connect_once)
    monkeypatch.setattr(Gateway, "_sleep", lambda self, duration: sleeps.append(duration))

    gateway = object.__new__(Gateway)
    gateway.dev = None

    gateway.connect(wait=True, poll_interval=0.1)

    assert attempts["count"] == 3
    assert sleeps == [0.1, 0.1]
    assert gateway.dev is not None


def test_connect_raises_when_wait_disabled(monkeypatch):
    def fake_connect_once(self):
        raise PortalNotFoundError("still missing")

    monkeypatch.setattr(Gateway, "_connect_once", fake_connect_once)

    gateway = object.__new__(Gateway)
    gateway.dev = None

    with pytest.raises(PortalNotFoundError):
        gateway.connect(wait=False)


def test_send_packet_reconnects_after_disconnect(monkeypatch):
    failing_device = _FailingWriteDevice()
    replacement = _RecordingWriteDevice()

    gateway = object.__new__(Gateway)
    gateway.dev = failing_device
    gateway.endpoint = 1
    gateway.timeout = 250
    gateway._usb_core = SimpleNamespace(USBError=_DummyUSBError)

    def fake_connect(self, wait=True, poll_interval=_RECONNECT_DELAY_SECONDS):
        self.dev = replacement

    monkeypatch.setattr(Gateway, "connect", fake_connect)
    monkeypatch.setattr(Gateway, "_handle_disconnect", lambda self, exc=None: setattr(self, "dev", None))

    gateway.send_packet([0] * 32)

    assert replacement.calls == [(1, bytes([0] * 32), 250)]


def test_read_packet_reconnects_after_disconnect(monkeypatch):
    data = [1] * 32
    failing_device = _FailingReadDevice()
    replacement = _SuccessfulReadDevice(data)

    gateway = object.__new__(Gateway)
    gateway.dev = failing_device
    gateway.read_endpoint = 0x81
    gateway.timeout = 500
    gateway._usb_core = SimpleNamespace(USBError=_DummyUSBError)

    def fake_connect(self, wait=True, poll_interval=_RECONNECT_DELAY_SECONDS):
        self.dev = replacement

    monkeypatch.setattr(Gateway, "connect", fake_connect)
    monkeypatch.setattr(Gateway, "_handle_disconnect", lambda self, exc=None: setattr(self, "dev", None))

    packet = gateway.read_packet()

    assert packet == tuple(data)
