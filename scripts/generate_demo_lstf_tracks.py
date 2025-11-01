"""Generate demonstration LSTF tracks that showcase playback features."""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Dict, List, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


TICKS_PER_BEAT = 960
BASE_TEMPO_US_PER_BEAT = 500_000  # 120 BPM


def _varint(value: int) -> bytes:
    parts: List[int] = []
    remaining = value
    while True:
        byte = remaining & 0x7F
        remaining >>= 7
        if remaining:
            parts.append(byte | 0x80)
        else:
            parts.append(byte)
            break
    return bytes(parts)


def _chunk(tag: str, payload: bytes) -> bytes:
    return tag.encode("ascii") + struct.pack("<I", len(payload)) + payload


def _beats_to_ticks(beats: float) -> int:
    return int(round(beats * TICKS_PER_BEAT))


def _encode_colour(colour: Dict[str, Tuple[int, int, int] | int]) -> bytes:
    if "index" in colour:
        index = int(colour["index"])
        if not (0 <= index <= 31):
            raise ValueError("Palette index must be in range 0-31")
        return bytes([index & 0x1F])
    if "rgb" in colour:
        red, green, blue = colour["rgb"]
        for channel in (red, green, blue):
            if not (0 <= channel <= 255):
                raise ValueError("RGB channels must be 0-255")
        return bytes([0x20, red, green, blue])
    raise ValueError("Colour specification must include 'index' or 'rgb'")


@dataclass
class PadEvent:
    tick: int
    opcode: int
    payload: bytes


class PadBuilder:
    def __init__(self) -> None:
        self._events: List[PadEvent] = []

    def add_event(self, beat: float, opcode: int, payload: bytes) -> None:
        self._events.append(PadEvent(tick=_beats_to_ticks(beat), opcode=opcode, payload=payload))

    def set_default_transition(self, beat: float, transition_beats: float) -> None:
        transition_ticks = _beats_to_ticks(transition_beats)
        payload = struct.pack("<H", max(0, transition_ticks))
        self.add_event(beat, 0x14, payload)

    def switch_colour(
        self,
        beat: float,
        *,
        colour: Dict[str, Tuple[int, int, int] | int],
        transition_beats: float = 0.0,
        hold_beats: float = 0.0,
        use_default: bool = False,
    ) -> None:
        transition = 0xFFFF if use_default else _beats_to_ticks(transition_beats)
        hold = _beats_to_ticks(hold_beats)
        payload = struct.pack("<H", transition) + _encode_colour(colour) + struct.pack("<H", hold)
        self.add_event(beat, 0x10, payload)

    def fade_to_colour(
        self,
        beat: float,
        *,
        colour: Dict[str, Tuple[int, int, int] | int],
        ramp_beats: float,
        pulses: int,
        hold_beats: float,
    ) -> None:
        ramp_ticks = _beats_to_ticks(ramp_beats)
        hold_ticks = _beats_to_ticks(hold_beats)
        payload = (
            struct.pack("<H", ramp_ticks)
            + bytes([max(0, min(255, pulses))])
            + _encode_colour(colour)
            + struct.pack("<H", hold_ticks)
        )
        self.add_event(beat, 0x11, payload)

    def flash_colour(
        self,
        beat: float,
        *,
        colour: Dict[str, Tuple[int, int, int] | int],
        on_beats: float,
        off_beats: float,
        pulses: int,
        hold_beats: float,
    ) -> None:
        on_ticks = _beats_to_ticks(on_beats)
        off_ticks = _beats_to_ticks(off_beats)
        hold_ticks = _beats_to_ticks(hold_beats)
        payload = (
            struct.pack("<H", on_ticks)
            + struct.pack("<H", off_ticks)
            + bytes([max(0, min(255, pulses))])
            + _encode_colour(colour)
            + struct.pack("<H", hold_ticks)
        )
        self.add_event(beat, 0x12, payload)

    def blackout(self, beat: float, *, transition_beats: float, hold_beats: float) -> None:
        transition_ticks = _beats_to_ticks(transition_beats)
        hold_ticks = _beats_to_ticks(hold_beats)
        payload = struct.pack("<H", transition_ticks) + struct.pack("<H", hold_ticks)
        self.add_event(beat, 0x13, payload)

    def encode(self) -> bytes:
        payload = bytearray()
        current_tick = 0
        for event in sorted(self._events, key=lambda evt: evt.tick):
            delta = event.tick - current_tick
            if delta < 0:
                raise ValueError("Events must be added in non-decreasing time order")
            payload.extend(_varint(delta))
            payload.append(event.opcode)
            payload.extend(event.payload)
            current_tick = event.tick
        return bytes(payload)


def _encode_tempo_events(events: Sequence[Tuple[float, int]]) -> bytes:
    if not events:
        return b""
    payload = bytearray()
    current_tick = 0
    for beat, tempo in sorted(events, key=lambda item: item[0]):
        tick = _beats_to_ticks(beat)
        delta = tick - current_tick
        if delta < 0:
            raise ValueError("Tempo events must be non-decreasing")
        payload.extend(_varint(delta))
        payload.append(0x01)
        payload.extend(struct.pack("<I", tempo))
        current_tick = tick
    return bytes(payload)


def _build_head_chunk() -> bytes:
    payload = struct.pack(
        "<IHHIHH",
        0x4C535446,
        1,
        TICKS_PER_BEAT,
        BASE_TEMPO_US_PER_BEAT,
        4,
        1,
    )
    return _chunk("HEAD", payload)


def _build_program(
    pad_builders: Sequence[PadBuilder],
    *,
    tempo_events: Sequence[Tuple[float, int]] | None = None,
    palette_overrides: Sequence[Tuple[int, Tuple[int, int, int]]] | None = None,
) -> bytes:
    parts: List[bytes] = [_build_head_chunk()]

    if palette_overrides:
        override_payload = bytearray([len(palette_overrides)])
        for index, (r, g, b) in palette_overrides:
            override_payload.extend(bytes([index & 0xFF, r & 0xFF, g & 0xFF, b & 0xFF]))
        parts.append(_chunk("PAL0", bytes(override_payload)))

    tempo_payload = _encode_tempo_events(tempo_events or [])
    parts.append(_chunk("TEMP", tempo_payload))

    for pad_index, builder in enumerate(pad_builders):
        pad_payload = builder.encode()
        if not pad_payload:
            raise ValueError("Each demonstration track must include pad events")
        parts.append(_chunk(f"PAD{pad_index}", pad_payload))

    return b"".join(parts)


def _wrap_textual_payload(data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    lines = [encoded[i : i + 76] for i in range(0, len(encoded), 76)]
    return "\n".join([TEXTUAL_LSTF_HEADER, *lines, ""])


@dataclass(frozen=True)
class TrackSpec:
    name: str
    description: str
    builder: Callable[[], bytes]



def _aurora_glide() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    for pad in (centre, left, right):
        pad.set_default_transition(0.0, transition_beats=0.5)

    centre.switch_colour(0.0, colour={"index": 17}, hold_beats=2.0, use_default=True)
    centre.switch_colour(2.0, colour={"index": 19}, hold_beats=2.0, use_default=True)
    centre.switch_colour(4.0, colour={"index": 21}, hold_beats=2.0, use_default=True)
    centre.switch_colour(6.0, colour={"index": 23}, hold_beats=2.0, use_default=True)
    centre.switch_colour(8.0, colour={"index": 27}, hold_beats=2.0, use_default=True)

    left.switch_colour(1.0, colour={"index": 13}, hold_beats=2.0, use_default=True)
    left.switch_colour(3.0, colour={"index": 15}, hold_beats=2.0, use_default=True)
    left.switch_colour(5.0, colour={"index": 17}, hold_beats=2.0, use_default=True)
    left.switch_colour(7.0, colour={"index": 19}, hold_beats=2.0, use_default=True)
    left.switch_colour(9.0, colour={"index": 21}, hold_beats=2.0, use_default=True)

    right.switch_colour(2.0, colour={"index": 24}, hold_beats=2.0, use_default=True)
    right.switch_colour(4.0, colour={"index": 26}, hold_beats=2.0, use_default=True)
    right.switch_colour(6.0, colour={"index": 28}, hold_beats=2.0, use_default=True)
    right.switch_colour(8.0, colour={"index": 30}, hold_beats=2.0, use_default=True)
    right.switch_colour(10.0, colour={"index": 1}, hold_beats=2.0, use_default=True)

    return _build_program((centre, left, right))


def _rainbow_cycle() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    centre.fade_to_colour(0.0, colour={"rgb": (0, 255, 128)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    centre.fade_to_colour(2.0, colour={"rgb": (64, 0, 255)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    centre.fade_to_colour(4.0, colour={"rgb": (255, 64, 0)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    centre.fade_to_colour(6.0, colour={"rgb": (0, 128, 255)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    centre.fade_to_colour(8.0, colour={"rgb": (255, 0, 192)}, ramp_beats=1.5, pulses=3, hold_beats=3.0)

    left.fade_to_colour(1.0, colour={"rgb": (255, 200, 0)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    left.fade_to_colour(3.0, colour={"rgb": (0, 180, 255)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    left.fade_to_colour(5.0, colour={"rgb": (180, 0, 255)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    left.fade_to_colour(7.0, colour={"rgb": (0, 255, 200)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    left.fade_to_colour(9.0, colour={"rgb": (255, 120, 0)}, ramp_beats=1.5, pulses=3, hold_beats=3.0)

    right.fade_to_colour(0.5, colour={"rgb": (255, 32, 160)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    right.fade_to_colour(2.5, colour={"rgb": (0, 255, 255)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    right.fade_to_colour(4.5, colour={"rgb": (255, 255, 0)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    right.fade_to_colour(6.5, colour={"rgb": (0, 128, 255)}, ramp_beats=1.5, pulses=3, hold_beats=2.0)
    right.fade_to_colour(8.5, colour={"rgb": (255, 0, 255)}, ramp_beats=1.5, pulses=3, hold_beats=3.0)

    return _build_program((centre, left, right))


def _sync_pulse() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    centre.flash_colour(0.0, colour={"index": 1}, on_beats=0.25, off_beats=0.25, pulses=6, hold_beats=3.0)
    centre.flash_colour(3.0, colour={"index": 27}, on_beats=0.125, off_beats=0.125, pulses=10, hold_beats=3.0)
    centre.switch_colour(6.0, colour={"index": 0}, hold_beats=4.0)

    left.flash_colour(0.0, colour={"index": 4}, on_beats=0.25, off_beats=0.25, pulses=6, hold_beats=3.0)
    left.flash_colour(3.0, colour={"index": 9}, on_beats=0.125, off_beats=0.125, pulses=10, hold_beats=3.0)
    left.switch_colour(6.0, colour={"index": 0}, hold_beats=4.0)

    right.flash_colour(0.0, colour={"index": 17}, on_beats=0.25, off_beats=0.25, pulses=6, hold_beats=3.0)
    right.flash_colour(3.0, colour={"index": 24}, on_beats=0.125, off_beats=0.125, pulses=10, hold_beats=3.0)
    right.switch_colour(6.0, colour={"index": 0}, hold_beats=4.0)

    return _build_program((centre, left, right))


def _triple_chase() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    cycle_starts = (0.0, 3.0, 6.0, 9.0)
    highlight = 0.75

    for base in cycle_starts:
        centre.switch_colour(base, colour={"index": 4}, hold_beats=highlight)
        centre.switch_colour(base + highlight, colour={"index": 0}, hold_beats=0.25)
        left.switch_colour(base + 1.0, colour={"index": 6}, hold_beats=highlight)
        left.switch_colour(base + 1.0 + highlight, colour={"index": 0}, hold_beats=0.25)
        right.switch_colour(base + 2.0, colour={"index": 9}, hold_beats=highlight)
        right.switch_colour(base + 2.0 + highlight, colour={"index": 0}, hold_beats=0.25)

    centre.switch_colour(12.0, colour={"index": 2}, hold_beats=1.0)
    left.switch_colour(12.0, colour={"index": 12}, hold_beats=1.0)
    right.switch_colour(12.0, colour={"index": 24}, hold_beats=1.0)

    return _build_program((centre, left, right))


def _tempo_ramp() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    tempo_events = [(0.0, 750_000), (4.0, 500_000), (8.0, 350_000)]

    centre.flash_colour(0.0, colour={"index": 10}, on_beats=0.5, off_beats=0.5, pulses=6, hold_beats=4.0)
    centre.flash_colour(4.0, colour={"index": 14}, on_beats=0.5, off_beats=0.5, pulses=8, hold_beats=4.0)
    centre.flash_colour(8.0, colour={"index": 4}, on_beats=0.5, off_beats=0.5, pulses=10, hold_beats=4.0)
    centre.switch_colour(12.0, colour={"index": 0}, hold_beats=2.0)

    left.fade_to_colour(0.0, colour={"index": 17}, ramp_beats=2.0, pulses=2, hold_beats=4.0)
    left.fade_to_colour(4.0, colour={"index": 19}, ramp_beats=2.0, pulses=3, hold_beats=4.0)
    left.fade_to_colour(8.0, colour={"index": 21}, ramp_beats=2.0, pulses=4, hold_beats=4.0)
    left.blackout(12.0, transition_beats=1.0, hold_beats=2.0)

    right.switch_colour(0.0, colour={"index": 5}, hold_beats=4.0)
    right.switch_colour(4.0, colour={"index": 7}, hold_beats=4.0)
    right.switch_colour(8.0, colour={"index": 9}, hold_beats=4.0)
    right.blackout(12.0, transition_beats=0.5, hold_beats=2.0)

    return _build_program((centre, left, right), tempo_events=tempo_events)


def _countdown_burst() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    centre.flash_colour(0.0, colour={"index": 1}, on_beats=1.0, off_beats=1.0, pulses=3, hold_beats=4.0)
    centre.flash_colour(4.0, colour={"index": 27}, on_beats=0.5, off_beats=0.5, pulses=3, hold_beats=3.0)
    centre.flash_colour(7.0, colour={"index": 4}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)
    centre.switch_colour(9.0, colour={"index": 1}, hold_beats=2.0)

    left.flash_colour(0.0, colour={"index": 20}, on_beats=1.0, off_beats=1.0, pulses=3, hold_beats=4.0)
    left.flash_colour(4.0, colour={"index": 14}, on_beats=0.5, off_beats=0.5, pulses=3, hold_beats=3.0)
    left.flash_colour(7.0, colour={"index": 9}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)
    left.switch_colour(9.0, colour={"index": 10}, hold_beats=2.0)

    right.flash_colour(0.0, colour={"index": 4}, on_beats=1.0, off_beats=1.0, pulses=3, hold_beats=4.0)
    right.flash_colour(4.0, colour={"index": 6}, on_beats=0.5, off_beats=0.5, pulses=3, hold_beats=3.0)
    right.flash_colour(7.0, colour={"index": 27}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)
    right.switch_colour(9.0, colour={"index": 24}, hold_beats=2.0)

    return _build_program((centre, left, right))


def _strobe_warning() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    centre.flash_colour(0.0, colour={"index": 1}, on_beats=0.125, off_beats=0.125, pulses=20, hold_beats=6.0)
    centre.flash_colour(6.0, colour={"index": 4}, on_beats=0.0625, off_beats=0.0625, pulses=24, hold_beats=2.0)
    centre.blackout(8.0, transition_beats=0.5, hold_beats=2.0)

    left.flash_colour(0.0, colour={"index": 9}, on_beats=0.125, off_beats=0.125, pulses=20, hold_beats=6.0)
    left.flash_colour(6.0, colour={"index": 1}, on_beats=0.0625, off_beats=0.0625, pulses=24, hold_beats=2.0)
    left.blackout(8.0, transition_beats=0.5, hold_beats=2.0)

    right.flash_colour(0.0, colour={"index": 27}, on_beats=0.125, off_beats=0.125, pulses=20, hold_beats=6.0)
    right.flash_colour(6.0, colour={"index": 22}, on_beats=0.0625, off_beats=0.0625, pulses=24, hold_beats=2.0)
    right.blackout(8.0, transition_beats=0.5, hold_beats=2.0)

    return _build_program((centre, left, right))


def _twinkle_field() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    def add_twinkle(pad: PadBuilder, entries: Sequence[Tuple[float, int, float]]):
        for start, colour_index, duration in entries:
            pad.switch_colour(start, colour={"index": colour_index}, hold_beats=duration)
            pad.switch_colour(start + duration, colour={"index": 0}, hold_beats=0.25)

    add_twinkle(
        centre,
        (
            (0.5, 24, 0.3),
            (1.8, 10, 0.4),
            (3.2, 27, 0.3),
            (4.6, 21, 0.5),
            (6.5, 9, 0.4),
            (8.4, 14, 0.4),
            (10.2, 18, 0.5),
        ),
    )
    add_twinkle(
        left,
        (
            (0.7, 30, 0.3),
            (2.1, 12, 0.4),
            (3.9, 16, 0.4),
            (5.2, 28, 0.3),
            (6.8, 8, 0.4),
            (8.9, 26, 0.4),
            (10.8, 4, 0.5),
        ),
    )
    add_twinkle(
        right,
        (
            (0.9, 5, 0.3),
            (2.4, 19, 0.4),
            (4.0, 23, 0.3),
            (5.7, 15, 0.4),
            (7.2, 25, 0.4),
            (9.1, 17, 0.4),
            (11.0, 29, 0.5),
        ),
    )

    centre.switch_colour(12.0, colour={"index": 3}, hold_beats=1.0)
    left.switch_colour(12.0, colour={"index": 7}, hold_beats=1.0)
    right.switch_colour(12.0, colour={"index": 11}, hold_beats=1.0)

    return _build_program((centre, left, right))


def _wave_cascade() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    for pad in (centre, left, right):
        pad.set_default_transition(0.0, transition_beats=0.5)

    centre.fade_to_colour(0.0, colour={"index": 17}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    centre.fade_to_colour(3.0, colour={"index": 19}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    centre.fade_to_colour(6.0, colour={"index": 21}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    centre.fade_to_colour(9.0, colour={"index": 23}, ramp_beats=2.0, pulses=4, hold_beats=3.0)

    left.fade_to_colour(1.0, colour={"index": 10}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    left.fade_to_colour(4.0, colour={"index": 12}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    left.fade_to_colour(7.0, colour={"index": 14}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    left.fade_to_colour(10.0, colour={"index": 16}, ramp_beats=2.0, pulses=4, hold_beats=3.0)

    right.fade_to_colour(2.0, colour={"index": 24}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    right.fade_to_colour(5.0, colour={"index": 26}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    right.fade_to_colour(8.0, colour={"index": 28}, ramp_beats=2.0, pulses=4, hold_beats=3.0)
    right.fade_to_colour(11.0, colour={"index": 30}, ramp_beats=2.0, pulses=4, hold_beats=3.0)

    return _build_program((centre, left, right))


def _centre_stage() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    centre.fade_to_colour(0.0, colour={"index": 1}, ramp_beats=2.0, pulses=2, hold_beats=4.0)
    centre.fade_to_colour(4.0, colour={"index": 4}, ramp_beats=1.0, pulses=1, hold_beats=2.0)
    centre.fade_to_colour(6.0, colour={"index": 9}, ramp_beats=1.0, pulses=1, hold_beats=2.0)
    centre.fade_to_colour(8.0, colour={"index": 27}, ramp_beats=2.0, pulses=2, hold_beats=4.0)
    centre.blackout(12.0, transition_beats=0.5, hold_beats=2.0)

    left.switch_colour(0.0, colour={"index": 14}, transition_beats=0.5, hold_beats=12.0)
    left.flash_colour(3.0, colour={"index": 10}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)
    left.flash_colour(7.0, colour={"index": 12}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)

    right.switch_colour(0.0, colour={"index": 18}, transition_beats=0.5, hold_beats=12.0)
    right.flash_colour(3.5, colour={"index": 24}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)
    right.flash_colour(7.5, colour={"index": 26}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)

    return _build_program((centre, left, right))


def _ocean_swell() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    centre.fade_to_colour(0.0, colour={"index": 18}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    centre.fade_to_colour(3.0, colour={"index": 16}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    centre.fade_to_colour(6.0, colour={"index": 14}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    centre.blackout(9.0, transition_beats=1.0, hold_beats=2.0)
    centre.switch_colour(11.0, colour={"index": 0}, hold_beats=1.0)

    left.fade_to_colour(1.5, colour={"index": 19}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    left.fade_to_colour(4.5, colour={"index": 17}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    left.fade_to_colour(7.5, colour={"index": 15}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    left.blackout(10.5, transition_beats=1.0, hold_beats=2.0)

    right.fade_to_colour(3.0, colour={"index": 20}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    right.fade_to_colour(6.0, colour={"index": 22}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    right.fade_to_colour(9.0, colour={"index": 24}, ramp_beats=3.0, pulses=3, hold_beats=3.0)
    right.blackout(12.0, transition_beats=1.0, hold_beats=2.0)

    return _build_program((centre, left, right))


def _fireworks_finale() -> bytes:
    centre = PadBuilder()
    left = PadBuilder()
    right = PadBuilder()

    palette_overrides = [(31, (0xFF, 0xEE, 0x66)), (30, (0xFF, 0xAA, 0x00))]

    centre.flash_colour(0.0, colour={"index": 27}, on_beats=0.25, off_beats=0.25, pulses=4, hold_beats=2.0)
    centre.switch_colour(2.0, colour={"index": 31}, transition_beats=0.5, hold_beats=2.0)
    centre.flash_colour(4.0, colour={"index": 4}, on_beats=0.125, off_beats=0.125, pulses=8, hold_beats=3.0)
    centre.switch_colour(7.0, colour={"index": 1}, transition_beats=0.25, hold_beats=2.0)
    centre.flash_colour(9.0, colour={"index": 31}, on_beats=0.125, off_beats=0.125, pulses=6, hold_beats=2.0)
    centre.blackout(11.0, transition_beats=0.5, hold_beats=1.0)

    left.fade_to_colour(0.0, colour={"index": 24}, ramp_beats=1.5, pulses=2, hold_beats=2.0)
    left.flash_colour(2.5, colour={"index": 31}, on_beats=0.25, off_beats=0.25, pulses=6, hold_beats=2.0)
    left.fade_to_colour(5.0, colour={"index": 17}, ramp_beats=1.0, pulses=3, hold_beats=2.0)
    left.flash_colour(9.0, colour={"index": 31}, on_beats=0.125, off_beats=0.125, pulses=6, hold_beats=2.0)
    left.blackout(11.0, transition_beats=0.5, hold_beats=1.0)

    right.switch_colour(0.0, colour={"index": 6}, hold_beats=1.0)
    right.flash_colour(1.0, colour={"index": 27}, on_beats=0.25, off_beats=0.25, pulses=5, hold_beats=2.0)
    right.flash_colour(3.5, colour={"index": 22}, on_beats=0.25, off_beats=0.25, pulses=6, hold_beats=2.0)
    right.switch_colour(6.0, colour={"index": 30}, transition_beats=0.5, hold_beats=2.0)
    right.flash_colour(9.0, colour={"index": 1}, on_beats=0.125, off_beats=0.125, pulses=6, hold_beats=2.0)
    right.blackout(11.0, transition_beats=0.5, hold_beats=1.0)

    return _build_program((centre, left, right), palette_overrides=palette_overrides)


TRACKS: Tuple[TrackSpec, ...] = (
    TrackSpec("aurora_glide", "Cascading pad fades with default transitions.", _aurora_glide),
    TrackSpec("rainbow_cycle", "Multi-pad literal colour fades with overlapping ramps.", _rainbow_cycle),
    TrackSpec("sync_pulse", "Synchronous pulse patterns using flash commands.", _sync_pulse),
    TrackSpec("triple_chase", "Sequential pad chase with quick swaps to blackout.", _triple_chase),
    TrackSpec("tempo_ramp", "Tempo changes that accelerate flashes and fades.", _tempo_ramp),
    TrackSpec("countdown_burst", "Countdown pulses with shrinking intervals.", _countdown_burst),
    TrackSpec("strobe_warning", "High-intensity strobe showcase.", _strobe_warning),
    TrackSpec("twinkle_field", "Asynchronous twinkles with short dwell times.", _twinkle_field),
    TrackSpec("wave_cascade", "Layered wave fades using default transitions.", _wave_cascade),
    TrackSpec("centre_stage", "Centre spotlight with supporting side pulses.", _centre_stage),
    TrackSpec("ocean_swell", "Slow overlapping fades with blackout finales.", _ocean_swell),
    TrackSpec("fireworks_finale", "Palette overrides with spark bursts and finale strobe.", _fireworks_finale),
)


from lego_dimensions_protocol.lstf import TEXTUAL_LSTF_HEADER, load_lstf


def build_tracks(output_dir: Path) -> List[Tuple[str, float]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: List[Tuple[str, float]] = []

    for spec in TRACKS:
        data = spec.builder()
        path = output_dir / f"{spec.name}.lstf"
        path.write_text(_wrap_textual_payload(data), encoding="ascii")

        program = load_lstf(path)
        if len(program.pad_tracks) != 3:
            raise RuntimeError(f"{spec.name} does not contain exactly three pad tracks")
        durations = [track.duration for track in program.pad_tracks.values()]
        max_duration = max(durations)
        if not 5.0 <= max_duration <= 15.0:
            raise RuntimeError(
                f"{spec.name} duration {max_duration:.2f}s is outside the 5-15 second range"
            )
        summaries.append((spec.name, max_duration))

    return summaries


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = repo_root / "tracks"
    summaries = build_tracks(output_dir)
    for name, duration in summaries:
        print(f"Wrote {name}.lstf ({duration:.2f}s)")


if __name__ == "__main__":
    main()
