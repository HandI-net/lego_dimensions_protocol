from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock, Thread
from typing import IO, Iterable, Optional, Sequence

from .gateway import Gateway, Pad, RGBColor
from .rfid import TagEvent, TagTracker, TagTrackerError

LOGGER = logging.getLogger(__name__)


class PadOperation(str, Enum):
    SET = "set"
    FADE = "fade"
    FLASH = "flash"


@dataclass(frozen=True)
class PadAction:
    mask: int
    operation: PadOperation
    colour: tuple[int, int, int]
    pulse_time: int | None = None
    pulse_count: int | None = None
    on_length: int | None = None
    off_length: int | None = None


@dataclass(frozen=True)
class WaitInstruction:
    milliseconds: int


@dataclass(frozen=True)
class QuitInstruction:
    pass


_PAD_BITS: Sequence[tuple[int, Pad]] = (
    (1, Pad.CENTRE),
    (2, Pad.LEFT),
    (4, Pad.RIGHT),
)


class _PromptPrinter:
    def __init__(self, *, interactive: bool) -> None:
        self._interactive = interactive
        self._lock = Lock()

    def line(self, message: str) -> None:
        with self._lock:
            sys.stdout.write(f"{message}\n")
            if self._interactive:
                sys.stdout.write("> ")
            sys.stdout.flush()

    def prompt(self) -> None:
        if not self._interactive:
            return
        with self._lock:
            sys.stdout.write("> ")
            sys.stdout.flush()


def parse_instruction(text: str) -> PadAction | WaitInstruction | QuitInstruction:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Empty command; specify a pad mask and instruction")

    if stripped.lower() in {"q", "quit", "exit"}:
        return QuitInstruction()

    command_name, args_text = _split_command(stripped)

    if command_name == "wait":
        parsed = _parse_argument_list(args_text)
        if len(parsed) != 1:
            raise ValueError("wait expects a single millisecond duration")
        milliseconds = _parse_wait_time(parsed[0])
        return WaitInstruction(milliseconds=milliseconds)

    if command_name == PadOperation.SET.value:
        mask, parsed_colour = _parse_argument_list(args_text, expect_mask=True)
        if len(parsed_colour) == 1:
            colour_value = parsed_colour[0]
        elif len(parsed_colour) == 3:
            colour_value = parsed_colour
        else:
            raise ValueError("set expects a single RGB colour argument")
        colour = _parse_colour(colour_value)
        return PadAction(mask=mask, operation=PadOperation.SET, colour=colour)

    if command_name in {PadOperation.FADE.value, PadOperation.FLASH.value}:
        mask, parsed_args = _parse_argument_list(args_text, expect_mask=True)
    else:
        parsed_args = ()
        mask = None

    if command_name == PadOperation.FADE.value:
        if len(parsed_args) != 3:
            raise ValueError("fade expects colour, pulse_time, and pulse_count arguments")
        colour, pulse_time, pulse_count = parsed_args
        return PadAction(
            mask=mask,
            operation=PadOperation.FADE,
            colour=_parse_colour(colour),
            pulse_time=_parse_byte(pulse_time, "pulse_time"),
            pulse_count=_parse_byte(pulse_count, "pulse_count"),
        )

    if command_name == PadOperation.FLASH.value:
        if len(parsed_args) != 4:
            raise ValueError("flash expects colour, on_time, off_time, and count arguments")
        colour, on_time, off_time, pulse_count = parsed_args
        return PadAction(
            mask=mask,
            operation=PadOperation.FLASH,
            colour=_parse_colour(colour),
            on_length=_parse_byte(on_time, "on_time"),
            off_length=_parse_byte(off_time, "off_time"),
            pulse_count=_parse_byte(pulse_count, "pulse_count"),
        )

    raise ValueError(f"Unknown command '{command_name}'. Supported commands: set, fade, flash, wait, q")


def _split_command(command_text: str) -> tuple[str, str]:
    if not command_text.endswith(")"):
        raise ValueError("Commands must be of the form name(args)")
    open_paren = command_text.find("(")
    if open_paren == -1:
        raise ValueError("Commands must include parentheses with arguments")
    name = command_text[:open_paren].strip().lower()
    args = command_text[open_paren + 1 : -1]
    if not name:
        raise ValueError("Command name cannot be empty")
    return name, args


def _parse_argument_list(args_text: str, *, expect_mask: bool = False) -> tuple:
    try:
        parsed = ast.literal_eval(args_text)
    except (ValueError, SyntaxError) as exc:  # pragma: no cover - defensive parsing
        raise ValueError(f"Unable to parse arguments: {args_text}") from exc
    if not isinstance(parsed, tuple):
        parsed = (parsed,)
    if expect_mask:
        if not parsed:
            raise ValueError("Pad commands must include a pad bitmap as the first argument")
        mask = _parse_mask(parsed[0])
        return mask, tuple(parsed[1:])
    return parsed


def _parse_colour(value: object) -> tuple[int, int, int]:
    try:
        colour = RGBColor.from_iterable(value)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - validated by RGBColor
        raise ValueError("Colours must be an RGB tuple like (r, g, b)") from exc
    return colour.as_tuple()


def _parse_mask(value: object) -> int:
    try:
        mask = int(value, 0) if isinstance(value, str) else int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Pad bitmap must be an integer") from exc
    if mask <= 0 or mask > 0b111:
        raise ValueError("Pad bitmap must select at least one pad using bits 1, 2, and 4")
    return mask


def _parse_byte(value: object, name: str) -> int:
    integer = int(value)
    if not 0 <= integer <= 0xFF:
        raise ValueError(f"{name} must fit in a byte (0-255)")
    return integer


def _parse_wait_time(value: object) -> int:
    milliseconds = int(value)
    if milliseconds < 0:
        raise ValueError("wait duration must be non-negative")
    if milliseconds > 3_600_000:
        raise ValueError("wait duration must be 3,600,000ms (1 hour) or less")
    return milliseconds


def _pads_from_mask(mask: int) -> list[Pad]:
    pads: list[Pad] = []
    for bit, pad in _PAD_BITS:
        if mask & bit:
            pads.append(pad)
    return pads


def _apply_set(pads: Sequence[Pad], *, colour: Sequence[int], gateway: Gateway) -> None:
    if len(pads) == 3:
        gateway.switch_pad(Pad.ALL, colour)
        return
    for pad in pads:
        gateway.switch_pad(pad, colour)


def _apply_fade(
    pads: Sequence[Pad],
    *,
    colour: Sequence[int],
    pulse_time: int,
    pulse_count: int,
    gateway: Gateway,
) -> None:
    if len(pads) == 3:
        gateway.fade_pad(Pad.ALL, pulse_time=pulse_time, pulse_count=pulse_count, colour=colour)
        return
    for pad in pads:
        gateway.fade_pad(pad, pulse_time=pulse_time, pulse_count=pulse_count, colour=colour)


def _apply_flash(
    pads: Sequence[Pad],
    *,
    colour: Sequence[int],
    on_length: int,
    off_length: int,
    pulse_count: int,
    gateway: Gateway,
) -> None:
    if len(pads) == 3:
        gateway.flash_pad(
            Pad.ALL,
            on_length=on_length,
            off_length=off_length,
            pulse_count=pulse_count,
            colour=colour,
        )
        return
    for pad in pads:
        gateway.flash_pad(
            pad,
            on_length=on_length,
            off_length=off_length,
            pulse_count=pulse_count,
            colour=colour,
        )


def apply_pad_action(action: PadAction, gateway: Gateway) -> None:
    pads = _pads_from_mask(action.mask)
    if not pads:
        raise ValueError("No pads selected by mask")

    if action.operation is PadOperation.SET:
        _apply_set(pads, colour=action.colour, gateway=gateway)
    elif action.operation is PadOperation.FADE:
        if action.pulse_time is None or action.pulse_count is None:
            raise ValueError("fade commands require pulse_time and pulse_count")
        _apply_fade(
            pads,
            colour=action.colour,
            pulse_time=action.pulse_time,
            pulse_count=action.pulse_count,
            gateway=gateway,
        )
    elif action.operation is PadOperation.FLASH:
        if action.on_length is None or action.off_length is None or action.pulse_count is None:
            raise ValueError("flash commands require on_time, off_time, and count")
        _apply_flash(
            pads,
            colour=action.colour,
            on_length=action.on_length,
            off_length=action.off_length,
            pulse_count=action.pulse_count,
            gateway=gateway,
        )
    else:  # pragma: no cover - exhaustive guard
        raise ValueError(f"Unsupported operation: {action.operation}")


def _event_printer(printer: _PromptPrinter, gateway: Gateway, stop_event: Event) -> None:
    tracker = TagTracker(gateway=gateway, auto_start=True)
    try:
        while not stop_event.is_set():
            try:
                for event in tracker.iter_events():
                    if stop_event.is_set():
                        break
                    printer.line(_serialise_event(event))
            except TagTrackerError as exc:
                if stop_event.is_set():
                    break
                printer.line(_serialise_status("tracker_error", str(exc)))
                tracker.stop()
                time.sleep(1.0)
                tracker = TagTracker(gateway=gateway, auto_start=True)
    finally:
        tracker.stop()


def _serialise_event(event: TagEvent) -> str:
    payload = {
        "type": "tag",
        "event": event.type.value,
        "pad": event.pad.name.lower() if event.pad is not None else None,
        "uid": event.uid,
    }
    return json.dumps(payload, separators=(",", ":"))


def _serialise_status(kind: str, message: str) -> str:
    return json.dumps({"type": "status", "status": kind, "message": message}, separators=(",", ":"))


def _run_loop(commands: Iterable[str], printer: _PromptPrinter, gateway: Gateway) -> None:
    for line in commands:
        stripped = line.strip()
        if not stripped:
            printer.prompt()
            continue
        try:
            instruction = parse_instruction(stripped)
            if isinstance(instruction, QuitInstruction):
                return
            if isinstance(instruction, WaitInstruction):
                time.sleep(instruction.milliseconds / 1000.0)
            else:
                apply_pad_action(instruction, gateway)
        except Exception as exc:  # pragma: no cover - CLI guard
            LOGGER.error("%s", exc)
        printer.prompt()


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Streaming CLI for controlling LEGO Dimensions pads")
    parser.add_argument(
        "command_source",
        nargs="?",
        default="-",
        help="File containing commands. Defaults to stdin when omitted or '-'",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    source: IO[str]
    if args.command_source == "-":
        source = sys.stdin
    else:
        source = open(args.command_source, "r", encoding="utf-8")

    interactive = source.isatty()
    printer = _PromptPrinter(interactive=interactive)

    with Gateway() as gateway:
        stop_event = Event()
        event_thread = Thread(
            target=_event_printer, args=(printer, gateway, stop_event), name="PadCLIEvents", daemon=True
        )
        event_thread.start()
        try:
            printer.prompt()
            _run_loop(source, printer, gateway)
        finally:
            stop_event.set()
            event_thread.join(timeout=2.0)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
