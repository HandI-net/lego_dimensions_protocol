"""Backward compatible entry point that now relies on the packaged gateway API."""

from __future__ import annotations

import logging
from typing import Sequence

from lego_dimensions_protocol.demo import main as demo_main
from lego_dimensions_protocol.gateway import Gateway, Pad, PortalNotFoundError, RGBColor
from lego_dimensions_protocol.morse import demo as morse_demo, send_character, send_text
from lego_dimensions_protocol.rfid import TagEvent, TagEventType, TagTracker, watch_pads

__all__ = [
    "Gateway",
    "Pad",
    "PortalNotFoundError",
    "RGBColor",
    "TagTracker",
    "TagEvent",
    "TagEventType",
    "watch_pads",
    "send_character",
    "send_text",
    "morse_demo",
    "main",
]


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the interactive demo CLI."""

    logging.basicConfig(level=logging.INFO)
    return demo_main(argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
