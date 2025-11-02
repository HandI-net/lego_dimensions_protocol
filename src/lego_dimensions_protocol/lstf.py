"""Helpers for loading and working with Light Show Track Format (LSTF) files."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import logging
import struct
from bisect import bisect_right
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from .gateway import Pad

LOGGER = logging.getLogger(__name__)


class LSTFError(RuntimeError):
    """Raised when an LSTF file cannot be parsed."""


TEXTUAL_LSTF_HEADER = "LSTF-TEXT 1"
_TEXTUAL_PREFIX = "LSTF-TEXT"
_TEXTUAL_VERSION = "1"
_TEXTUAL_PREFIX_BYTES = _TEXTUAL_PREFIX.encode("ascii")


@dataclass(frozen=True)
class PadCommand:
    """Timed lighting instruction destined for a single pad."""

    time: float
    action: str
    colour: Optional[Tuple[int, int, int]] = None
    pulse_time: Optional[int] = None
    pulse_count: Optional[int] = None
    on_length: Optional[int] = None
    off_length: Optional[int] = None


@dataclass(frozen=True)
class PadTrack:
    """Sequence of :class:`PadCommand` objects for a specific pad."""

    commands: Tuple[PadCommand, ...]
    duration: float


@dataclass(frozen=True)
class LSTFProgram:
    """Parsed representation of an LSTF file."""

    pad_tracks: Mapping[Pad, PadTrack]

    @property
    def is_generic(self) -> bool:
        """Return ``True`` when the program only defines a single pad track."""

        return len(self.pad_tracks) == 1

    def iter_tracks(self) -> Iterator[Tuple[Pad, PadTrack]]:
        return self.pad_tracks.items()


_DEFAULT_PALETTE: Tuple[Tuple[int, int, int], ...] = (
    (0x00, 0x00, 0x00),
    (0xFF, 0xFF, 0xFF),
    (0xFF, 0xD8, 0xB0),
    (0xD6, 0xF0, 0xFF),
    (0xFF, 0x00, 0x00),
    (0xFF, 0x33, 0x00),
    (0xFF, 0x66, 0x00),
    (0xFF, 0x99, 0x00),
    (0xFF, 0xCC, 0x00),
    (0xFF, 0xFF, 0x00),
    (0xCC, 0xFF, 0x00),
    (0x99, 0xFF, 0x00),
    (0x66, 0xFF, 0x00),
    (0x33, 0xFF, 0x00),
    (0x00, 0xFF, 0x00),
    (0x00, 0xFF, 0x66),
    (0x00, 0xFF, 0xCC),
    (0x00, 0xFF, 0xFF),
    (0x00, 0xCC, 0xFF),
    (0x00, 0x99, 0xFF),
    (0x00, 0x66, 0xFF),
    (0x00, 0x33, 0xFF),
    (0x00, 0x00, 0xFF),
    (0x33, 0x00, 0xFF),
    (0x66, 0x00, 0xFF),
    (0x99, 0x00, 0xFF),
    (0xCC, 0x00, 0xFF),
    (0xFF, 0x00, 0xFF),
    (0xFF, 0x00, 0x99),
    (0xFF, 0x00, 0x66),
    (0xFF, 0x00, 0x33),
    (0xFF, 0x19, 0x19),
)


@dataclass
class _TempoSegment:
    start_tick: int
    seconds_per_tick: float
    start_time: float


class _TempoMap:
    def __init__(self, segments: Sequence[_TempoSegment]):
        self._segments = list(segments)
        if not self._segments:
            raise LSTFError("Tempo map must contain at least one segment.")
        self._starts = [segment.start_tick for segment in self._segments]

    def ticks_to_seconds(self, tick: int) -> float:
        if tick < 0:
            raise LSTFError("Tick positions cannot be negative.")
        index = bisect_right(self._starts, tick) - 1
        segment = self._segments[max(index, 0)]
        return segment.start_time + (tick - segment.start_tick) * segment.seconds_per_tick

    def duration_between(self, start_tick: int, end_tick: int) -> float:
        if end_tick < start_tick:
            raise LSTFError("End tick precedes start tick when computing duration.")
        return self.ticks_to_seconds(end_tick) - self.ticks_to_seconds(start_tick)


def load_lstf(path: str | Path) -> LSTFProgram:
    """Load *path* and return a parsed :class:`LSTFProgram`."""

    file_path = Path(path)
    raw = file_path.read_bytes()
    data = _normalise_lstf_bytes(raw, source=file_path)
    parser = _LSTFParser(data, source=file_path)
    return parser.parse()


def _normalise_lstf_bytes(data: bytes, *, source: Path | None = None) -> bytes:
    """Return binary LSTF payload from raw file *data*.

    Modern repositories store tracks in an ASCII transport wrapper to ensure
    they remain text-friendly for VCS systems.  The wrapper begins with a
    ``LSTF-TEXT`` header and base64 payload.  Older tracks may remain in their
    original binary form; both encodings are supported transparently.
    """

    if data.startswith(_TEXTUAL_PREFIX_BYTES):
        return _decode_textual_lstf(data, source=source)
    return data


def _decode_textual_lstf(data: bytes, *, source: Path | None = None) -> bytes:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise LSTFError("Text-encoded LSTF files must be ASCII.") from exc

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise LSTFError("Text-encoded LSTF file is empty.")

    header = lines[0].split()
    if len(header) != 2 or header[0] != _TEXTUAL_PREFIX:
        raise LSTFError("Missing LSTF-TEXT header in text-encoded file.")
    version = header[1]
    if version != _TEXTUAL_VERSION:
        raise LSTFError(f"Unsupported text LSTF version {version!r}.")

    encoded_chunks = [line for line in lines[1:] if not line.startswith("#")]
    if not encoded_chunks:
        raise LSTFError("Text-encoded LSTF file does not contain payload data.")

    payload = "".join(encoded_chunks)
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        location = f" ({source})" if source else ""
        raise LSTFError(f"Invalid base64 payload in text LSTF{location}.") from exc


class _LSTFParser:
    def __init__(self, data: bytes, *, source: Path | None = None) -> None:
        self._data = data
        self._source = source
        self._palette = list(_DEFAULT_PALETTE)

    def parse(self) -> LSTFProgram:
        header = None
        tempo_events: List[Tuple[int, int, int]] = []
        pad_chunks: Dict[int, List[bytes]] = {0: [], 1: [], 2: []}

        offset = 0
        data_length = len(self._data)
        while offset < data_length:
            if offset + 8 > data_length:
                raise LSTFError("Unexpected end of file while reading chunk header.")
            chunk_type = self._data[offset : offset + 4]
            try:
                chunk_name = chunk_type.decode("ascii")
            except UnicodeDecodeError as exc:
                raise LSTFError("Chunk type must be ASCII.") from exc
            payload_length = int.from_bytes(self._data[offset + 4 : offset + 8], "little")
            offset += 8
            if offset + payload_length > data_length:
                raise LSTFError(f"Chunk {chunk_name!r} exceeds file length.")
            payload = self._data[offset : offset + payload_length]
            offset += payload_length

            if chunk_name == "HEAD":
                header = self._parse_header(payload)
            elif chunk_name == "TEMP":
                tempo_events.extend(self._parse_tempo(payload))
            elif chunk_name == "PAL0":
                self._apply_palette_override(payload)
            elif chunk_name.startswith("PAD") and len(chunk_name) == 4:
                try:
                    pad_index = int(chunk_name[-1])
                except ValueError:
                    LOGGER.debug("Ignoring unknown pad chunk %s", chunk_name)
                    continue
                if pad_index in pad_chunks:
                    pad_chunks[pad_index].append(payload)
                else:
                    LOGGER.debug("Ignoring unsupported pad index %s", pad_index)
            else:
                LOGGER.debug("Skipping unrecognised LSTF chunk %s", chunk_name)

        if header is None:
            raise LSTFError("LSTF file missing HEAD chunk.")

        tempo_map = self._build_tempo_map(header, tempo_events)

        tracks: Dict[Pad, PadTrack] = {}
        pad_map = {0: Pad.CENTRE, 1: Pad.LEFT, 2: Pad.RIGHT}
        for pad_index, chunks in pad_chunks.items():
            if not chunks:
                continue
            pad = pad_map.get(pad_index)
            if pad is None:
                LOGGER.debug("Ignoring unsupported pad index %s", pad_index)
                continue
            commands, duration = self._parse_pad_chunks(chunks, tempo_map)
            if commands:
                tracks[pad] = PadTrack(commands=tuple(commands), duration=duration)

        if not tracks:
            raise LSTFError("LSTF file did not contain any pad tracks.")

        return LSTFProgram(pad_tracks=tracks)

    def _parse_header(self, payload: bytes) -> Tuple[int, int]:
        if len(payload) < 16:
            raise LSTFError("HEAD chunk must contain at least 16 bytes.")
        magic, version, ticks_per_beat, tempo, track_count, _flags = struct.unpack_from(
            "<IHHIHH", payload, 0
        )
        if magic != 0x4C535446:
            raise LSTFError("Invalid LSTF magic value.")
        if version != 1:
            raise LSTFError(f"Unsupported LSTF version {version}.")
        if ticks_per_beat <= 0:
            raise LSTFError("ticks_per_beat must be positive.")
        if tempo <= 0:
            raise LSTFError("Initial tempo must be positive.")
        if track_count <= 0:
            LOGGER.debug("HEAD chunk declared zero tracks; continuing regardless.")
        return ticks_per_beat, tempo

    def _parse_tempo(self, payload: bytes) -> List[Tuple[int, int, int]]:
        events: List[Tuple[int, int, int]] = []
        offset = 0
        current_tick = 0
        length = len(payload)
        while offset < length:
            delta, consumed = self._read_varint(payload, offset)
            offset += consumed
            current_tick += delta
            if offset >= length:
                raise LSTFError("Incomplete tempo event opcode.")
            opcode = payload[offset]
            offset += 1
            if opcode == 0x01:
                if offset + 4 > length:
                    raise LSTFError("Incomplete SetTempo payload.")
                tempo = int.from_bytes(payload[offset : offset + 4], "little")
                offset += 4
                events.append((current_tick, opcode, tempo))
            elif opcode == 0x02:
                if offset + 2 > length:
                    raise LSTFError("Incomplete SetTimebase payload.")
                timebase = int.from_bytes(payload[offset : offset + 2], "little")
                offset += 2
                events.append((current_tick, opcode, timebase))
            else:
                raise LSTFError(f"Unsupported tempo opcode {opcode:#04x}.")
        return events

    def _apply_palette_override(self, payload: bytes) -> None:
        if not payload:
            return
        count = payload[0]
        offset = 1
        for _ in range(count):
            if offset + 4 > len(payload):
                raise LSTFError("Incomplete palette override entry.")
            index = payload[offset]
            red, green, blue = payload[offset + 1 : offset + 4]
            offset += 4
            if 0 <= index < len(self._palette):
                self._palette[index] = (int(red), int(green), int(blue))

    def _build_tempo_map(
        self, header: Tuple[int, int], events: Sequence[Tuple[int, int, int]]
    ) -> _TempoMap:
        ticks_per_beat, tempo = header
        segments: List[_TempoSegment] = []
        seconds_per_tick = tempo / 1_000_000.0 / ticks_per_beat
        segments.append(_TempoSegment(start_tick=0, seconds_per_tick=seconds_per_tick, start_time=0.0))

        current_tick = 0
        current_ticks_per_beat = ticks_per_beat
        current_tempo = tempo

        for event_tick, opcode, value in sorted(events, key=lambda item: item[0]):
            if event_tick < current_tick:
                continue
            if opcode == 0x01:
                if value <= 0:
                    LOGGER.debug("Ignoring non-positive tempo change %s", value)
                    continue
                current_tempo = value
            elif opcode == 0x02:
                if value <= 0:
                    LOGGER.debug("Ignoring non-positive timebase change %s", value)
                    continue
                current_ticks_per_beat = value
            else:
                continue

            if event_tick == segments[-1].start_tick:
                segments[-1] = _TempoSegment(
                    start_tick=event_tick,
                    seconds_per_tick=current_tempo / 1_000_000.0 / current_ticks_per_beat,
                    start_time=segments[-1].start_time,
                )
            else:
                start_time = segments[-1].start_time + (
                    (event_tick - segments[-1].start_tick) * segments[-1].seconds_per_tick
                )
                segments.append(
                    _TempoSegment(
                        start_tick=event_tick,
                        seconds_per_tick=current_tempo / 1_000_000.0 / current_ticks_per_beat,
                        start_time=start_time,
                    )
                )
            current_tick = event_tick

        return _TempoMap(segments)

    def _parse_pad_chunks(
        self, chunks: Sequence[bytes], tempo: _TempoMap
    ) -> Tuple[List[PadCommand], float]:
        commands: List[PadCommand] = []
        duration = 0.0
        current_tick = 0
        default_transition: Optional[int] = None

        for chunk in chunks:
            offset = 0
            length = len(chunk)
            while offset < length:
                delta, consumed = self._read_varint(chunk, offset)
                offset += consumed
                current_tick += delta
                if offset >= length:
                    raise LSTFError("Missing pad opcode byte.")
                opcode = chunk[offset]
                offset += 1

                if opcode == 0x10:  # SwitchColour
                    transition_ticks = self._read_u16(chunk, offset)
                    offset += 2
                    if transition_ticks == 0xFFFF and default_transition is not None:
                        transition_ticks = default_transition
                    colour, consumed = self._parse_colour(chunk, offset)
                    offset += consumed
                    hold_ticks = self._read_u16(chunk, offset)
                    offset += 2

                    start_time = tempo.ticks_to_seconds(current_tick)
                    if transition_ticks:
                        transition_seconds = tempo.duration_between(
                            current_tick, current_tick + transition_ticks
                        )
                        pulse_time = _seconds_to_unit(transition_seconds)
                        command = PadCommand(
                            time=start_time,
                            action="fade",
                            colour=colour,
                            pulse_time=pulse_time,
                            pulse_count=1,
                        )
                    else:
                        command = PadCommand(time=start_time, action="switch", colour=colour)
                    commands.append(command)

                    if hold_ticks:
                        hold_end = tempo.ticks_to_seconds(current_tick + hold_ticks)
                        duration = max(duration, hold_end)
                    else:
                        duration = max(duration, start_time)

                elif opcode == 0x11:  # FadeToColour
                    ramp_ticks = self._read_u16(chunk, offset)
                    offset += 2
                    pulses = chunk[offset]
                    offset += 1
                    colour, consumed = self._parse_colour(chunk, offset)
                    offset += consumed
                    hold_ticks = self._read_u16(chunk, offset)
                    offset += 2

                    start_time = tempo.ticks_to_seconds(current_tick)
                    ramp_seconds = tempo.duration_between(current_tick, current_tick + ramp_ticks)
                    pulse_count = max(1, int(pulses) if pulses else 1)
                    pulse_time = _seconds_to_unit(ramp_seconds / pulse_count if pulse_count else 0.0)
                    commands.append(
                        PadCommand(
                            time=start_time,
                            action="fade",
                            colour=colour,
                            pulse_time=max(1, pulse_time),
                            pulse_count=pulse_count,
                        )
                    )

                    if hold_ticks:
                        hold_end = tempo.ticks_to_seconds(current_tick + hold_ticks)
                        duration = max(duration, hold_end)
                    else:
                        duration = max(duration, start_time)

                elif opcode == 0x12:  # FlashColour
                    on_ticks = self._read_u16(chunk, offset)
                    off_ticks = self._read_u16(chunk, offset + 2)
                    offset += 4
                    pulse_count = chunk[offset]
                    offset += 1
                    colour, consumed = self._parse_colour(chunk, offset)
                    offset += consumed
                    hold_ticks = self._read_u16(chunk, offset)
                    offset += 2

                    start_time = tempo.ticks_to_seconds(current_tick)
                    on_length = _seconds_to_unit(
                        tempo.duration_between(current_tick, current_tick + on_ticks)
                    )
                    off_length = _seconds_to_unit(
                        tempo.duration_between(current_tick, current_tick + off_ticks)
                    )
                    commands.append(
                        PadCommand(
                            time=start_time,
                            action="flash",
                            colour=colour,
                            on_length=max(1, on_length),
                            off_length=max(1, off_length),
                            pulse_count=max(1, int(pulse_count) if pulse_count else 1),
                        )
                    )

                    if hold_ticks:
                        hold_end = tempo.ticks_to_seconds(current_tick + hold_ticks)
                        duration = max(duration, hold_end)
                    else:
                        duration = max(duration, start_time)

                elif opcode == 0x13:  # Blackout
                    transition_ticks = self._read_u16(chunk, offset)
                    offset += 2
                    hold_ticks = self._read_u16(chunk, offset)
                    offset += 2
                    start_time = tempo.ticks_to_seconds(current_tick)
                    if transition_ticks:
                        transition_seconds = tempo.duration_between(
                            current_tick, current_tick + transition_ticks
                        )
                        commands.append(
                            PadCommand(
                                time=start_time,
                                action="fade",
                                colour=(0, 0, 0),
                                pulse_time=_seconds_to_unit(transition_seconds),
                                pulse_count=1,
                            )
                        )
                    else:
                        commands.append(
                            PadCommand(time=start_time, action="switch", colour=(0, 0, 0))
                        )
                    if hold_ticks:
                        hold_end = tempo.ticks_to_seconds(current_tick + hold_ticks)
                        duration = max(duration, hold_end)
                    else:
                        duration = max(duration, start_time)

                elif opcode == 0x14:  # SetDefaultTransition
                    default_transition = self._read_u16(chunk, offset)
                    offset += 2
                elif opcode == 0x1F:  # KeyframeState
                    offset += 1
                else:
                    raise LSTFError(f"Unsupported pad opcode {opcode:#04x} encountered.")

        commands.sort(key=lambda command: command.time)
        if duration <= 0.0 and commands:
            duration = commands[-1].time
        duration = max(duration, 0.01)
        return commands, duration

    @staticmethod
    def _read_varint(data: bytes, offset: int) -> Tuple[int, int]:
        value = 0
        shift = 0
        consumed = 0
        length = len(data)
        while True:
            if offset + consumed >= length:
                raise LSTFError("Malformed variable-length integer in LSTF payload.")
            byte = data[offset + consumed]
            consumed += 1
            value |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
            if shift > 28:
                raise LSTFError("Variable-length integer is too large.")
        return value, consumed

    @staticmethod
    def _read_u16(data: bytes, offset: int) -> int:
        if offset + 2 > len(data):
            raise LSTFError("Unexpected end of data when reading 16-bit value.")
        return struct.unpack_from("<H", data, offset)[0]

    def _parse_colour(self, data: bytes, offset: int) -> Tuple[Tuple[int, int, int], int]:
        if offset >= len(data):
            raise LSTFError("Missing colour specification byte.")
        mode = data[offset]
        literal = bool(mode & 0x20)
        index = mode & 0x1F
        if literal:
            if offset + 4 > len(data):
                raise LSTFError("Incomplete literal colour entry.")
            return (
                int(data[offset + 1]),
                int(data[offset + 2]),
                int(data[offset + 3]),
            ), 4
        if index >= len(self._palette):
            raise LSTFError(f"Palette index {index} out of range.")
        return self._palette[index], 1


def _seconds_to_unit(value: float) -> int:
    """Convert seconds to a 0-255 portal timing unit."""

    if value <= 0:
        return 0
    # Empirically each unit maps to roughly 10 ms on the portal. Clamp into the
    # valid byte range for robustness.
    scaled = int(round(value / 0.01))
    return max(1, min(255, scaled))


__all__ = [
    "LSTFProgram",
    "LSTFError",
    "PadCommand",
    "PadTrack",
    "load_lstf",
    "TEXTUAL_LSTF_HEADER",
]

