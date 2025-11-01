"""Tests for normalising backend timeout errors in the gateway."""

from pathlib import Path
import sys
from types import SimpleNamespace

import ctypes

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.gateway import Gateway, _LIBUSB_TIMEOUT_CODE


class _DummyUSBTimeoutError(Exception):
    def __init__(self, errno=None, strerror="Operation timed out", backend_error_code=None):
        super().__init__(strerror)
        self.errno = errno
        self.strerror = strerror
        self.backend_error_code = backend_error_code


class _DummyUSBError(Exception):
    def __init__(self, errno=None, strerror="Operation timed out", backend_error_code=None):
        super().__init__(strerror)
        self.errno = errno
        self.strerror = strerror
        self.backend_error_code = backend_error_code


@pytest.mark.parametrize(
    "usb_core, exc",
    [
        (
            SimpleNamespace(USBTimeoutError=_DummyUSBTimeoutError, USBError=_DummyUSBError),
            _DummyUSBTimeoutError(errno=60),
        ),
        (
            SimpleNamespace(USBTimeoutError=_DummyUSBTimeoutError, USBError=_DummyUSBError),
            _DummyUSBError(errno=110),
        ),
        (
            SimpleNamespace(USBTimeoutError=_DummyUSBTimeoutError, USBError=_DummyUSBError),
            _DummyUSBError(errno="60"),
        ),
        (
            SimpleNamespace(USBTimeoutError=_DummyUSBTimeoutError, USBError=_DummyUSBError),
            _DummyUSBError(errno=ctypes.c_int(60)),
        ),
        (
            SimpleNamespace(USBTimeoutError=_DummyUSBTimeoutError, USBError=_DummyUSBError),
            _DummyUSBError(errno=None, backend_error_code=_LIBUSB_TIMEOUT_CODE),
        ),
        (
            None,
            type("USBTimeoutError", (Exception,), {})("Timed out"),
        ),
        (
            None,
            Exception("Operation timed out"),
        ),
    ],
)
def test_is_timeout_error_normalises_usb_backend_timeouts(usb_core, exc):
    gateway = object.__new__(Gateway)
    gateway._usb_core = usb_core
    assert gateway._is_timeout_error(exc)


def test_is_timeout_error_rejects_non_timeout():
    gateway = object.__new__(Gateway)
    gateway._usb_core = SimpleNamespace(USBTimeoutError=_DummyUSBTimeoutError, USBError=_DummyUSBError)
    assert not gateway._is_timeout_error(Exception("Other failure"))
    assert not gateway._is_timeout_error(_DummyUSBError(errno=5, strerror="Input/output error"))
