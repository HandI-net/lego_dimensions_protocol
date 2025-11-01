"""Interactive helpers for browsing and editing LEGO Dimensions tags."""

from __future__ import annotations

import argparse
import logging
from typing import Iterable, List, Optional, Sequence, Tuple

from . import characters
from .characters import CharacterInfo
from .editor import TagEditor, _ensure_uid
from .gateway import Pad
from .rfid import TagEvent, TagTracker

LOGGER = logging.getLogger(__name__)

_PAD_NAMES = {
    "left": Pad.LEFT,
    "centre": Pad.CENTRE,
    "center": Pad.CENTRE,
    "middle": Pad.CENTRE,
    "right": Pad.RIGHT,
}


def _format_table(rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for index, row in enumerate(rows):
        padded = [value.ljust(widths[pos]) for pos, value in enumerate(row)]
        lines.append(" | ".join(padded))
        if index == 0:
            lines.append("-+-".join("-" * width for width in widths))
    return "\n".join(lines)


class CharacterViewer:
    """Expose convenience helpers for catalog inspection and tag editing."""

    def __init__(self, catalog: Optional[Iterable[CharacterInfo]] = None) -> None:
        self._catalog = list(catalog) if catalog is not None else list(characters.iter_characters())

    def search(self, *, world: Optional[str] = None, query: Optional[str] = None) -> List[CharacterInfo]:
        results: List[CharacterInfo] = []
        for entry in self._catalog:
            if world and entry.world.lower() != world.lower():
                continue
            if query and query.lower() not in entry.name.lower():
                continue
            results.append(entry)
        return results

    def render(self, entries: Sequence[CharacterInfo]) -> str:
        rows = [("ID", "Name", "World")]
        for entry in sorted(entries, key=lambda item: item.id):
            rows.append((str(entry.id), entry.name, entry.world))
        return _format_table(rows)

    def watch(self) -> None:
        seen: set[str] = set()

        def _handle(event: TagEvent) -> None:
            if event.removed:
                LOGGER.info("Removed tag %s from %s", event.uid, event.pad)
                return
            if event.uid not in seen:
                seen.add(event.uid)
                if event.character is not None:
                    LOGGER.info(
                        "Detected %s (ID %s, %s) on %s [uid %s]",
                        event.character.name,
                        event.character_id,
                        event.character.world,
                        event.pad,
                        event.uid,
                    )
                else:
                    LOGGER.info("Detected tag %s on %s", event.uid, event.pad)
            else:
                LOGGER.debug("Tag %s updated on %s", event.uid, event.pad)

        with TagTracker() as tracker:
            tracker.add_listener(_handle)
            try:
                for _ in tracker.iter_events():
                    pass
            except KeyboardInterrupt:  # pragma: no cover - interactive helper
                LOGGER.info("Stopping character viewer")

    def edit(
        self,
        character_id: int,
        *,
        pad: Pad,
        uid: Optional[str] = None,
        apply: bool = False,
        poll_timeout: int = 1000,
    ) -> None:
        if uid is not None:
            uid_bytes = _ensure_uid(uid)
            tracker: Optional[TagTracker] = None
        else:
            tracker = TagTracker(poll_timeout=poll_timeout)
            uid_bytes = self._wait_for_pad(tracker, pad)

        gateway = tracker.gateway if tracker is not None else None
        with TagEditor(gateway=gateway) as editor:
            plan = editor.build_character_plan(uid_bytes, pad=pad, character_id=character_id)
            print(editor.describe_plan(plan))
            commands = editor.apply_plan(plan, dry_run=not apply)
            if apply:
                print("Tag updated successfully.")
            else:
                print("\nDry run; use --apply to send the following commands:")
                for command in commands:
                    print("  ", " ".join(f"{value:02x}" for value in command))

        if tracker is not None:
            tracker.close()

    def _wait_for_pad(self, tracker: TagTracker, pad: Pad) -> Tuple[int, ...]:
        try:
            for event in tracker.iter_events():
                if event.removed:
                    continue
                if event.pad is not pad:
                    continue
                if tracker.gateway:
                    LOGGER.info("Using gateway %s", tracker.gateway)
                uid = _ensure_uid(event.uid)
                if event.character is not None:
                    LOGGER.info(
                        "Preparing to retag %s (ID %s, %s)",
                        event.character.name,
                        event.character_id,
                        event.character.world,
                    )
                return uid
        finally:
            tracker.stop()
        raise RuntimeError("No tag detected on the requested pad.")


def _parse_pad(value: str) -> Pad:
    try:
        return _PAD_NAMES[value.lower()]
    except KeyError as exc:  # pragma: no cover - argument validation
        raise argparse.ArgumentTypeError(
            "Pad must be one of: left, centre, center, middle, right"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lego-character-viewer")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List known characters")
    list_parser.add_argument("--world", help="Filter by world", default=None)
    list_parser.add_argument("--search", help="Filter by name substring", default=None)

    subparsers.add_parser("watch", help="Watch the pad for characters")

    edit_parser = subparsers.add_parser("edit", help="Retag a figure on the pad")
    edit_parser.add_argument("character", type=int, help="Target character identifier")
    edit_parser.add_argument("--pad", type=_parse_pad, default=Pad.CENTRE, help="Pad location")
    edit_parser.add_argument("--uid", help="Explicit UID (hex)")
    edit_parser.add_argument("--apply", action="store_true", help="Send the write commands")
    edit_parser.add_argument(
        "--timeout",
        type=int,
        default=1000,
        help="Poll timeout in milliseconds while waiting for a tag",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    viewer = CharacterViewer()

    if args.command == "list":
        entries = viewer.search(world=args.world, query=args.search)
        print(viewer.render(entries))
    elif args.command == "watch":
        viewer.watch()
    elif args.command == "edit":
        viewer.edit(
            args.character,
            pad=args.pad,
            uid=args.uid,
            apply=args.apply,
            poll_timeout=args.timeout,
        )
    else:  # pragma: no cover - argument parsing guard
        parser.print_help()


__all__ = ["CharacterViewer", "main"]
