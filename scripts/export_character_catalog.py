#!/usr/bin/env python3
"""Export the LEGO Dimensions character catalog in a JSON friendly format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable, Sequence

# Ensure local sources are importable when the package isn't installed.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol import characters


def _default_catalog() -> Iterable[characters.CharacterInfo]:
    return sorted(characters.iter_characters(), key=lambda info: info.id)


def build_payload(catalog: Iterable[characters.CharacterInfo]) -> dict:
    """Return a JSON serialisable payload for *catalog*."""

    return {
        "characters": [
            {
                "id": entry.id,
                "name": entry.name,
                "world": entry.world,
            }
            for entry in catalog
        ]
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the vendor character catalog in JSON format."
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="Optional file path to write. Defaults to stdout.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Number of spaces to indent JSON output (default: 2).",
    )
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="Preserve the vendor ordering instead of sorting by character id.",
    )
    args = parser.parse_args(argv)

    catalog = characters.iter_characters() if args.no_sort else _default_catalog()
    payload = build_payload(catalog)
    json_text = json.dumps(payload, indent=args.indent, sort_keys=False)

    if args.output is None:
        print(json_text)
    else:
        args.output.write_text(json_text + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":  # pragma: no cover - manual usage
    raise SystemExit(main())
