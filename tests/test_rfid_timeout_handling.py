import logging
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lego_dimensions_protocol.gateway import Gateway
from lego_dimensions_protocol.rfid import TagTracker


class DummyUSBError(Exception):
    def __init__(self, errno=None, message="dummy usb error") -> None:
        super().__init__(message)
        self.errno = errno


class DummyUSBTimeoutError(DummyUSBError):
    """Simulate the dedicated timeout error added in newer PyUSB releases."""


def _build_gateway() -> Gateway:
    gateway = Gateway.__new__(Gateway)
    gateway.dev = SimpleNamespace()

    def _read(endpoint, length, timeout):  # noqa: D401 - test helper
        raise DummyUSBTimeoutError()

    gateway.dev.read = _read
    gateway.read_endpoint = 0x81
    gateway.timeout = 10
    gateway._usb_core = SimpleNamespace(
        USBTimeoutError=DummyUSBTimeoutError,
        USBError=DummyUSBError,
        LIBUSB_ERROR_TIMEOUT=-7,
    )
    gateway._reported_usb_messages = set()
    return gateway


def test_poll_once_returns_none_on_usb_timeout(caplog):
    gateway = _build_gateway()
    tracker = TagTracker(gateway=gateway, poll_timeout=1, auto_start=False)

    with caplog.at_level(logging.INFO, logger="lego_dimensions_protocol.gateway"):
        assert tracker.poll_once() is None

    timeout_messages = [
        record.message
        for record in caplog.records
        if "Timed out waiting for data from the LEGO Dimensions portal" in record.message
    ]
    assert timeout_messages

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="lego_dimensions_protocol.gateway"):
        assert tracker.poll_once() is None

    repeated_messages = [
        record.message
        for record in caplog.records
        if "Timed out waiting for data from the LEGO Dimensions portal" in record.message
    ]
    assert not repeated_messages
