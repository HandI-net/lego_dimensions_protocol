"""Hardware diagnostics for LEGO Dimensions USB portals."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import importlib
from importlib import metadata
import json
import platform as platform_module
import sys
import time
from typing import Any, Callable, Optional, Sequence

from .gateway import DEFAULT_PRODUCT_IDS, DEFAULT_VENDOR_ID, Gateway, Pad


def _package_version() -> str:
    try:
        return metadata.version("lego-dimensions-protocol")
    except metadata.PackageNotFoundError:
        return "0.1.0"


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    exception_type: str | None = None
    remediation: str | None = None


@dataclass(frozen=True)
class PortalCandidate:
    portal_id: str
    vendor_id: int | None = None
    product_id: int | None = None
    bus: int | None = None
    address: int | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    backend: str | None = None


@dataclass(frozen=True)
class DiagnosticReport:
    overall_status: str
    checks: list[DiagnosticCheck]
    package_version: str
    python_version: str
    platform: str
    portal_candidates: list[PortalCandidate]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _status(checks: Sequence[DiagnosticCheck]) -> str:
    if any(check.status == "fail" and check.severity == "error" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _parse_int(value: str) -> int:
    return int(value, 0)


def _safe_string(usb_util: Any, device: Any, index: Any) -> str | None:
    if not index:
        return None
    try:
        return usb_util.get_string(device, index)
    except Exception:
        return None


def _candidate_from_device(usb_util: Any, device: Any, index: int) -> PortalCandidate:
    return PortalCandidate(
        portal_id=f"usb-{getattr(device, 'bus', 'unknown')}-{getattr(device, 'address', index)}",
        vendor_id=getattr(device, "idVendor", None),
        product_id=getattr(device, "idProduct", None),
        bus=getattr(device, "bus", None),
        address=getattr(device, "address", None),
        serial_number=_safe_string(usb_util, device, getattr(device, "iSerialNumber", None)),
        manufacturer=_safe_string(usb_util, device, getattr(device, "iManufacturer", None)),
        product=_safe_string(usb_util, device, getattr(device, "iProduct", None)),
        backend=type(getattr(device, "_ctx", None)).__name__ if getattr(device, "_ctx", None) is not None else None,
    )


def run_diagnostics(
    *,
    vendor_id: int = DEFAULT_VENDOR_ID,
    product_ids: Sequence[int] = DEFAULT_PRODUCT_IDS,
    skip_light_test: bool = False,
    skip_rfid_test: bool = False,
    rfid_timeout: int = 1000,
    portal: str = "default",
    gateway_factory: Callable[..., Any] = Gateway,
    usb_core: Any | None = None,
    usb_util: Any | None = None,
) -> DiagnosticReport:
    """Collect a diagnostic report without requiring real hardware in tests."""

    checks: list[DiagnosticCheck] = [
        DiagnosticCheck(
            name="python",
            status="pass",
            severity="info",
            message=f"Python {platform_module.python_version()} is running.",
            details={"executable": sys.executable},
        )
    ]
    candidates: list[PortalCandidate] = []

    if portal != "default":
        checks.append(
            DiagnosticCheck(
                name="portal-selection",
                status="fail",
                severity="error",
                message="Only --portal default is supported in this release.",
                remediation="Use --portal default until multi-portal selection is implemented.",
            )
        )
        return DiagnosticReport(_status(checks), checks, _package_version(), sys.version.split()[0], platform_module.platform(), candidates)

    try:
        usb_core = usb_core or importlib.import_module("usb.core")
        usb_util = usb_util or importlib.import_module("usb.util")
    except ModuleNotFoundError as exc:
        checks.append(
            DiagnosticCheck(
                name="pyusb-import",
                status="fail",
                severity="error",
                message="PyUSB is not importable.",
                exception_type=exc.__class__.__name__,
                remediation="Install the package with PyUSB available, for example: python -m pip install pyusb",
            )
        )
        return DiagnosticReport(_status(checks), checks, _package_version(), sys.version.split()[0], platform_module.platform(), candidates)

    checks.append(DiagnosticCheck("pyusb-import", "pass", "info", "PyUSB modules are importable."))

    try:
        for product_id in product_ids:
            found = usb_core.find(idVendor=vendor_id, idProduct=product_id, find_all=True)
            for device in found or []:
                candidates.append(_candidate_from_device(usb_util, device, len(candidates)))
    except getattr(usb_core, "NoBackendError", Exception) as exc:
        checks.append(
            DiagnosticCheck(
                name="usb-backend",
                status="fail",
                severity="error",
                message="PyUSB could not find a usable libusb backend.",
                exception_type=exc.__class__.__name__,
                remediation="Install libusb for your platform and ensure Python can load it.",
            )
        )
        return DiagnosticReport(_status(checks), checks, _package_version(), sys.version.split()[0], platform_module.platform(), candidates)
    except Exception as exc:
        checks.append(
            DiagnosticCheck(
                name="portal-discovery",
                status="fail",
                severity="error",
                message="USB discovery failed before a portal could be tested.",
                exception_type=exc.__class__.__name__,
                details={"error": str(exc)},
            )
        )
        return DiagnosticReport(_status(checks), checks, _package_version(), sys.version.split()[0], platform_module.platform(), candidates)

    if candidates:
        checks.append(
            DiagnosticCheck(
                "portal-discovery",
                "pass",
                "info",
                f"Found {len(candidates)} LEGO Dimensions portal candidate(s).",
                details={"count": len(candidates)},
            )
        )
    else:
        checks.append(
            DiagnosticCheck(
                "portal-discovery",
                "fail",
                "error",
                "No LEGO Dimensions portal was found.",
                details={"vendor_id": f"0x{vendor_id:04x}", "product_ids": [f"0x{pid:04x}" for pid in product_ids]},
                remediation="Connect the portal, check USB permissions, then re-run lego-dimensions-doctor.",
            )
        )
        return DiagnosticReport(_status(checks), checks, _package_version(), sys.version.split()[0], platform_module.platform(), candidates)

    gateway: Any | None = None
    try:
        gateway = gateway_factory(vendor_id=vendor_id, product_ids=product_ids, initialize=False, wait_for_device=False)
        checks.append(DiagnosticCheck("gateway-connect", "pass", "info", "Gateway opened and claimed the portal interface."))

        if skip_light_test:
            checks.append(DiagnosticCheck("light-test", "skip", "info", "Light test skipped by user request."))
        else:
            try:
                gateway.switch_pad(Pad.ALL, (8, 8, 8))
                time.sleep(0.05)
                checks.append(DiagnosticCheck("light-test", "pass", "info", "Portal accepted a low-intensity light command."))
            finally:
                try:
                    gateway.blank_pads()
                except Exception as cleanup_exc:
                    checks.append(DiagnosticCheck("light-cleanup", "warn", "warning", "Attempted to blank pads after the light test, but cleanup failed.", exception_type=cleanup_exc.__class__.__name__))

        if skip_rfid_test:
            checks.append(DiagnosticCheck("rfid-read", "skip", "info", "RFID read test skipped by user request."))
        else:
            packet = gateway.read_packet(timeout=rfid_timeout)
            if packet is None:
                checks.append(DiagnosticCheck("rfid-read", "warn", "warning", "Read endpoint opened, but no RFID packet was observed before the timeout.", remediation="This is normal if no tag is on the portal."))
            else:
                checks.append(DiagnosticCheck("rfid-read", "pass", "info", "Read endpoint returned a packet.", details={"length": len(packet)}))
    except Exception as exc:
        checks.append(DiagnosticCheck("gateway-connect", "fail", "error", "Gateway connection or endpoint test failed.", exception_type=exc.__class__.__name__, details={"error": str(exc)}, remediation="Check permissions, libusb setup, and whether another process has claimed the portal."))
    finally:
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass

    return DiagnosticReport(_status(checks), checks, _package_version(), sys.version.split()[0], platform_module.platform(), candidates)


def format_report(report: DiagnosticReport, *, verbose: bool = False) -> str:
    lines = [f"LEGO Dimensions doctor: {report.overall_status.upper()}", f"Python: {report.python_version}", f"Package: {report.package_version}", f"Platform: {report.platform}", ""]
    for check in report.checks:
        marker = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}.get(check.status, check.status.upper())
        lines.append(f"[{marker}] {check.name}: {check.message}")
        if check.remediation:
            lines.append(f"       Try: {check.remediation}")
        if verbose and check.details:
            lines.append(f"       Details: {check.details}")
        if verbose and check.exception_type:
            lines.append(f"       Exception: {check.exception_type}")
    if report.portal_candidates:
        lines.append("")
        lines.append("Portal candidates:")
        for candidate in report.portal_candidates:
            lines.append(f"  - {candidate.portal_id}: vendor={candidate.vendor_id!r} product={candidate.product_id!r} bus={candidate.bus!r} address={candidate.address!r}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lego-dimensions-doctor")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable diagnostic JSON")
    parser.add_argument("--verbose", action="store_true", help="Include extra diagnostic detail")
    parser.add_argument("--vendor-id", type=_parse_int, default=DEFAULT_VENDOR_ID)
    parser.add_argument("--product-id", type=_parse_int, action="append", dest="product_ids")
    parser.add_argument("--skip-light-test", "--no-light-test", action="store_true")
    parser.add_argument("--skip-rfid-test", action="store_true")
    parser.add_argument("--rfid-timeout", type=int, default=1000, help="Milliseconds to wait for RFID packets")
    parser.add_argument("--portal", default="default", help="Reserved for future multi-portal targeting; currently only 'default'")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    product_ids = tuple(args.product_ids) if args.product_ids else DEFAULT_PRODUCT_IDS
    if args.rfid_timeout < 0:
        parser.error("--rfid-timeout must be non-negative")
    report = run_diagnostics(
        vendor_id=args.vendor_id,
        product_ids=product_ids,
        skip_light_test=args.skip_light_test,
        skip_rfid_test=args.skip_rfid_test,
        rfid_timeout=args.rfid_timeout,
        portal=args.portal,
    )
    print(report.to_json() if args.json else format_report(report, verbose=args.verbose))
    return 0 if report.overall_status in {"pass", "warn"} else 1


__all__ = ["DiagnosticCheck", "DiagnosticReport", "PortalCandidate", "format_report", "main", "run_diagnostics"]

if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
