import json

from lego_dimensions_protocol.doctor import format_report, run_diagnostics
from lego_dimensions_protocol.gateway import Pad


class NoBackendError(Exception):
    pass


class FakeDevice:
    idVendor = 0x0E6F
    idProduct = 0x0241
    bus = 1
    address = 2
    iSerialNumber = 0
    iManufacturer = 0
    iProduct = 0


class FakeUsbCore:
    NoBackendError = NoBackendError

    def __init__(self, devices=None, exc=None) -> None:
        self.devices = devices or []
        self.exc = exc

    def find(self, **kwargs):
        if self.exc:
            raise self.exc
        if kwargs.get("find_all"):
            return list(self.devices)
        return self.devices[0] if self.devices else None


class FakeUsbUtil:
    def get_string(self, device, index):
        return None


class FakeGateway:
    def __init__(self, **kwargs) -> None:
        self.calls = []

    def switch_pad(self, pad, colour) -> None:
        self.calls.append(("switch", pad, tuple(colour)))

    def blank_pads(self) -> None:
        self.calls.append(("blank",))

    def read_packet(self, *, timeout):
        return None

    def close(self) -> None:
        self.calls.append(("close",))


def test_doctor_no_portal_fails_cleanly() -> None:
    report = run_diagnostics(usb_core=FakeUsbCore(), usb_util=FakeUsbUtil(), skip_light_test=True, skip_rfid_test=True)
    assert report.overall_status == "fail"
    assert any(check.name == "portal-discovery" for check in report.checks)
    json.loads(report.to_json())


def test_doctor_no_backend_fails_with_remediation() -> None:
    report = run_diagnostics(usb_core=FakeUsbCore(exc=NoBackendError()), usb_util=FakeUsbUtil())
    assert report.overall_status == "fail"
    backend = [check for check in report.checks if check.name == "usb-backend"][0]
    assert backend.remediation


def test_doctor_success_with_rfid_warning() -> None:
    report = run_diagnostics(usb_core=FakeUsbCore([FakeDevice()]), usb_util=FakeUsbUtil(), gateway_factory=FakeGateway)
    assert report.overall_status == "warn"
    assert report.portal_candidates[0].portal_id == "usb-1-2"
    assert "RFID" in format_report(report)


def test_doctor_rejects_future_portal_selection() -> None:
    report = run_diagnostics(portal="other", usb_core=FakeUsbCore(), usb_util=FakeUsbUtil())
    assert report.overall_status == "fail"
    assert any(check.name == "portal-selection" for check in report.checks)
