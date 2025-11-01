"""Interactive workflows for cloning and programming LEGO Dimensions tags."""

from __future__ import annotations

import argparse
import logging
from typing import List, Optional, Sequence, Tuple

from . import characters
from .characters import CharacterInfo
from .editor import TagEditor, TagWritePlan
from .gateway import Pad
from .rfid import TagEvent, TagTracker

LOGGER = logging.getLogger(__name__)

_PAD_ALIASES = {
    "left": Pad.LEFT,
    "centre": Pad.CENTRE,
    "center": Pad.CENTRE,
    "middle": Pad.CENTRE,
    "right": Pad.RIGHT,
}

_SOURCE_WAIT_COLOUR: Tuple[int, int, int] = (0, 0, 96)
_TARGET_WAIT_COLOUR: Tuple[int, int, int] = (128, 96, 0)
_WRITE_PROGRESS_COLOUR: Tuple[int, int, int] = (32, 0, 160)
_SUCCESS_COLOUR: Tuple[int, int, int] = (0, 160, 0)
_DRY_RUN_COLOUR: Tuple[int, int, int] = (0, 96, 160)


def _parse_pad(value: str) -> Pad:
    try:
        return _PAD_ALIASES[value.lower()]
    except KeyError as exc:  # pragma: no cover - argument validation guard
        raise argparse.ArgumentTypeError(
            "Pad must be one of: left, centre, center, middle, right"
        ) from exc


def _format_character(character_id: int, info: Optional[CharacterInfo]) -> str:
    if info is None:
        return f"character ID {character_id}"
    return f"{info.name} (ID {character_id}, {info.world})"


class TagStudio:
    """High level workflows for cloning and writing LEGO Dimensions tags."""

    def __init__(
        self,
        tracker: Optional[TagTracker] = None,
        editor: Optional[TagEditor] = None,
        *,
        poll_timeout: int = 250,
    ) -> None:
        self._owns_tracker = tracker is None
        if tracker is None:
            tracker = TagTracker(poll_timeout=poll_timeout, auto_start=False)
        else:
            tracker.poll_timeout = poll_timeout
        self._tracker = tracker
        self._gateway = tracker.gateway
        self._owns_editor = editor is None
        self._editor = editor or TagEditor(gateway=self._gateway)

    def close(self) -> None:
        if self._owns_editor:
            self._editor.close()
        if self._owns_tracker:
            self._tracker.close()

    def __enter__(self) -> "TagStudio":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def clone(
        self,
        *,
        source_pad: Pad,
        target_pad: Pad,
        apply: bool = False,
    ) -> None:
        """Clone the character payload from one tag onto another."""

        print(f"Waiting for the source tag on the {source_pad.name.lower()} pad…")
        source_event = self._wait_for_pad(
            source_pad,
            wait_colour=_SOURCE_WAIT_COLOUR,
            success_colour=_SUCCESS_COLOUR,
            require_character=True,
        )

        assert source_event.character_id is not None  # for type checkers
        character_info = source_event.character or characters.get_character(
            source_event.character_id
        )
        print(
            "Source ready:",
            _format_character(source_event.character_id, character_info),
            f"(UID {source_event.uid})",
        )
        print("Remove the source tag and place the destination tag when ready.")

        print(f"Waiting for the destination tag on the {target_pad.name.lower()} pad…")
        target_event = self._wait_for_pad(
            target_pad,
            wait_colour=_TARGET_WAIT_COLOUR,
            success_colour=_SUCCESS_COLOUR,
            require_character=False,
        )

        plan = self._editor.build_character_plan(
            target_event.uid,
            pad=target_pad,
            character_id=source_event.character_id,
        )
        self._print_plan(plan)

        try:
            self._apply_plan(plan, pad=target_pad, apply=apply)
        finally:
            self._blank_pads(source_pad, target_pad)

    def write_character(
        self,
        character_id: int,
        *,
        pad: Pad,
        apply: bool = False,
    ) -> None:
        """Program a tag on *pad* with the requested character identifier."""

        character_info = characters.get_character(character_id)
        print(
            "Preparing to write",
            _format_character(character_id, character_info),
            f"to the {pad.name.lower()} pad.",
        )

        target_event = self._wait_for_pad(
            pad,
            wait_colour=_TARGET_WAIT_COLOUR,
            success_colour=_SUCCESS_COLOUR,
            require_character=False,
        )

        if target_event.character is not None and target_event.character_id is not None:
            LOGGER.info(
                "Overwriting %s on %s",
                _format_character(target_event.character_id, target_event.character),
                pad.name.lower(),
            )
        else:
            LOGGER.info("Detected UID %s on %s", target_event.uid, pad.name.lower())

        plan = self._editor.build_character_plan(
            target_event.uid,
            pad=pad,
            character_id=character_id,
        )
        self._print_plan(plan)

        try:
            self._apply_plan(plan, pad=pad, apply=apply)
        finally:
            self._blank_pads(pad)

    def _wait_for_pad(
        self,
        pad: Pad,
        *,
        wait_colour: Sequence[int],
        success_colour: Sequence[int],
        require_character: bool,
    ) -> TagEvent:
        wait_colour_tuple = tuple(int(value) & 0xFF for value in wait_colour)
        success_colour_tuple = tuple(int(value) & 0xFF for value in success_colour)
        self._gateway.switch_pad(pad, wait_colour_tuple)

        while True:
            event = self._tracker.poll_once()
            if event is None:
                continue
            if event.removed or event.pad is None:
                continue
            if event.pad is not pad:
                continue
            if require_character and event.character_id is None:
                LOGGER.warning("Tag %s did not expose character data yet; waiting", event.uid)
                continue

            self._gateway.flash_pad(
                pad,
                on_length=8,
                off_length=6,
                pulse_count=3,
                colour=success_colour_tuple,
            )
            self._gateway.switch_pad(pad, success_colour_tuple)
            return event

    def _apply_plan(self, plan: TagWritePlan, *, pad: Pad, apply: bool) -> List[List[int]]:
        if apply:
            print("Writing tag…")
            self._gateway.fade_pad(
                pad,
                pulse_time=18,
                pulse_count=10,
                colour=_WRITE_PROGRESS_COLOUR,
            )
            commands = self._editor.apply_plan(plan, dry_run=False)
            self._gateway.flash_pad(
                pad,
                on_length=10,
                off_length=6,
                pulse_count=4,
                colour=_SUCCESS_COLOUR,
            )
            print("Tag updated successfully.")
        else:
            commands = self._editor.apply_plan(plan, dry_run=True)
            print("Dry run; use --apply to send the following commands:")
            for command in commands:
                print("  ", " ".join(f"{value:02x}" for value in command))
            self._gateway.flash_pad(
                pad,
                on_length=8,
                off_length=6,
                pulse_count=5,
                colour=_DRY_RUN_COLOUR,
            )

        self._gateway.switch_pad(pad, (0, 0, 0))
        return commands

    def _print_plan(self, plan: TagWritePlan) -> None:
        description = self._editor.describe_plan(plan)
        print("")
        print(description)
        print("")

    def _blank_pads(self, *pads: Pad) -> None:
        for pad in pads:
            self._gateway.switch_pad(pad, (0, 0, 0))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lego-tag-studio")
    subparsers = parser.add_subparsers(dest="command")

    clone_parser = subparsers.add_parser("clone", help="Clone one figure onto another tag")
    clone_parser.add_argument(
        "--source-pad",
        type=_parse_pad,
        default=Pad.LEFT,
        help="Pad that holds the source tag",
    )
    clone_parser.add_argument(
        "--target-pad",
        type=_parse_pad,
        default=Pad.RIGHT,
        help="Pad that will receive the clone",
    )
    clone_parser.add_argument(
        "--apply",
        action="store_true",
        help="Send the write commands to the destination tag",
    )
    clone_parser.add_argument(
        "--timeout",
        type=int,
        default=250,
        help="Poll timeout in milliseconds while waiting for tags",
    )

    write_parser = subparsers.add_parser(
        "write", help="Write a catalogued character to a tag"
    )
    write_parser.add_argument(
        "character",
        type=int,
        help="Character identifier to encode on the destination tag",
    )
    write_parser.add_argument(
        "--pad",
        type=_parse_pad,
        default=Pad.CENTRE,
        help="Pad that holds the destination tag",
    )
    write_parser.add_argument(
        "--apply",
        action="store_true",
        help="Send the write commands to the destination tag",
    )
    write_parser.add_argument(
        "--timeout",
        type=int,
        default=250,
        help="Poll timeout in milliseconds while waiting for tags",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:  # pragma: no cover - argument guard
        parser.print_help()
        return

    poll_timeout = getattr(args, "timeout", 250)

    with TagStudio(poll_timeout=poll_timeout) as studio:
        if args.command == "clone":
            studio.clone(
                source_pad=args.source_pad,
                target_pad=args.target_pad,
                apply=args.apply,
            )
        elif args.command == "write":
            studio.write_character(
                args.character,
                pad=args.pad,
                apply=args.apply,
            )
        else:  # pragma: no cover - defensive guard
            parser.print_help()


__all__ = ["TagStudio", "main"]
