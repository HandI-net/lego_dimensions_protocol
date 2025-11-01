"""Command line helpers that showcase the :mod:`lego_dimensions_protocol` API."""

from __future__ import annotations

import argparse
import logging
import time
from typing import Iterable, Sequence

from .gateway import (
    DEFAULT_VENDOR_ID,
    Gateway,
    Pad,
    RGBColor,
)

LOGGER = logging.getLogger(__name__)


def _pause(gateway: Gateway, duration: float) -> None:
    time.sleep(duration)
    gateway.blank_pads()
    time.sleep(1.0)


def demo_switch_pads_skip(gateway: Gateway, *, pause: float) -> None:
    """Demonstrate skipping pads when switching colours."""

    LOGGER.info("Demonstrating flash_pad followed by switch_pads with skips")
    gateway.flash_pad(
        Pad.ALL,
        on_length=10,
        off_length=20,
        pulse_count=100,
        colour=RGBColor(255, 0, 0),
    )
    time.sleep(pause)
    gateway.switch_pads(
        (
            RGBColor(255, 0, 0),
            RGBColor(0, 255, 0),
            None,
        )
    )


def test_flash_pads(gateway: Gateway, *, pause: float) -> None:
    """Cycle through flash demonstrations."""

    LOGGER.info("Testing flash_pads with three independent pads")
    gateway.flash_pads(
        (
            (5, 10, 15, RGBColor(255, 0, 0)),
            (20, 25, 30, RGBColor(0, 255, 0)),
            (35, 40, 45, RGBColor(0, 0, 255)),
        )
    )
    _pause(gateway, pause)

    LOGGER.info("Testing flash_pads with skipped pads")
    gateway.flash_pads(
        (
            (5, 10, 15, RGBColor(255, 0, 255)),
            None,
            (5, 40, 10, RGBColor(255, 255, 0)),
        )
    )


def test_fade_pads(gateway: Gateway, *, pause: float) -> None:
    """Cycle through fade demonstrations."""

    LOGGER.info("Testing fade_pads with three pads")
    gateway.fade_pads(
        (
            (10, 20, RGBColor(255, 0, 0)),
            (20, 10, RGBColor(0, 255, 0)),
            (15, 15, RGBColor(0, 0, 255)),
        )
    )
    _pause(gateway, pause)

    LOGGER.info("Testing fade_pads with skipped pads")
    gateway.fade_pads(
        (
            None,
            (20, 10, RGBColor(0, 255, 255)),
            (15, 15, RGBColor(255, 255, 255)),
        )
    )


def run_demo(
    *,
    tests: Sequence[str] = ("switch", "fade", "flash"),
    pause: float = 2.0,
    initialise: bool = True,
    vendor_id: int | None = None,
    product_ids: Iterable[int] | None = None,
) -> None:
    """Execute one or more demonstration sequences."""

    resolved_vendor = vendor_id if vendor_id is not None else DEFAULT_VENDOR_ID
    with Gateway(
        vendor_id=resolved_vendor,
        product_ids=tuple(product_ids) if product_ids is not None else None,
        initialize=initialise,
    ) as gateway:
        for name in tests:
            if name == "switch":
                demo_switch_pads_skip(gateway, pause=pause)
                _pause(gateway, pause)
            elif name == "fade":
                test_fade_pads(gateway, pause=pause)
                _pause(gateway, pause)
            elif name == "flash":
                test_flash_pads(gateway, pause=pause)
                _pause(gateway, pause)
            else:
                LOGGER.warning("Unknown demo '%s'", name)
        gateway.blank_pads()


TEST_OPTIONS = {"switch", "fade", "flash", "all"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tests",
        nargs="+",
        choices=sorted(TEST_OPTIONS),
        default=["all"],
        help="Demo sequences to execute. Default runs all demos.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=2.0,
        help="Seconds to wait between demo steps (default: 2.0)",
    )
    parser.add_argument(
        "--no-init",
        action="store_true",
        help="Do not send the startup sequence automatically.",
    )
    parser.add_argument(
        "--vendor-id",
        type=lambda value: int(value, 0),
        default=None,
        help="Override the USB vendor id (e.g. 0x0E6F).",
    )
    parser.add_argument(
        "--product-id",
        dest="product_ids",
        type=lambda value: int(value, 0),
        action="append",
        default=None,
        help="Restrict detection to specific USB product identifiers.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (e.g. INFO, DEBUG).",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    tests = args.tests
    if "all" in tests:
        tests = ["switch", "fade", "flash"]

    run_demo(
        tests=tests,
        pause=args.pause,
        initialise=not args.no_init,
        vendor_id=args.vendor_id,
        product_ids=args.product_ids,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
