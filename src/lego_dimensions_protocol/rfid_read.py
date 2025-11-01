"""Command line utility for reading a single RFID tag from the LEGO portal."""

from __future__ import annotations

import argparse
import logging
from typing import Iterable, Sequence

from .gateway import Gateway
from .rfid import TagEventType, TagTracker

LOGGER = logging.getLogger(__name__)


def read_single_tag(
    *,
    vendor_id: int | None = None,
    product_ids: Iterable[int] | None = None,
    poll_timeout: int = 500,
) -> int:
    """Read a single RFID tag event and print the UID to stdout.

    The function initialises the LEGO Dimensions portal, waits for a single RFID
    event, and prints the detected UID when a tag is present.  When no tag is
    detected within the configured timeout a message is emitted and a non-zero
    exit status is returned.
    """

    gateway_kwargs: dict[str, object] = {}
    if vendor_id is not None:
        gateway_kwargs["vendor_id"] = vendor_id
    if product_ids is not None:
        gateway_kwargs["product_ids"] = tuple(product_ids)

    event = None

    with Gateway(**gateway_kwargs) as gateway:
        tracker = TagTracker(gateway, poll_timeout=poll_timeout, auto_start=False)
        try:
            event = tracker.poll_once()
        finally:
            tracker.close()

    if event is None:
        message = f"No RFID tag detected (timeout after {poll_timeout}ms)"
        print(message)
        LOGGER.debug(message)
        return 1

    if event.type is TagEventType.ADDED:
        print(event.uid)
        return 0

    message = f"RFID tag {event.uid} reported as removed"
    print(message)
    LOGGER.debug(message)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--poll-timeout",
        type=int,
        default=500,
        help="Milliseconds to wait for an RFID event before giving up.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (e.g. INFO, DEBUG).",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    return read_single_tag(
        vendor_id=args.vendor_id,
        product_ids=args.product_ids,
        poll_timeout=args.poll_timeout,
    )


__all__ = ["read_single_tag", "main"]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
