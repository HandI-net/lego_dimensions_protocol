"""Backward compatible entry point that now relies on the packaged gateway API."""

from __future__ import annotations

import logging
from typing import Sequence

from lego_dimensions_protocol.demo import main as demo_main
from lego_dimensions_protocol.gateway import Gateway, Pad, PortalNotFoundError, RGBColor

__all__ = ["Gateway", "Pad", "PortalNotFoundError", "RGBColor", "main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the interactive demo CLI."""

    logging.basicConfig(level=logging.INFO)
    return demo_main(argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
