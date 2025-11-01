import struct
from pathlib import Path

import pytest

from lego_dimensions_protocol.gateway import Pad
from lego_dimensions_protocol.lstf import LSTFProgram, load_lstf


def _varint(value: int) -> bytes:
    parts = []
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


def _build_head_chunk() -> bytes:
    payload = struct.pack("<IHHIHH", 0x4C535446, 1, 960, 500_000, 4, 1)
    return _chunk("HEAD", payload)


def _build_pad_chunk(opcodes: bytes, pad_index: int = 0) -> bytes:
    return _chunk(f"PAD{pad_index}", opcodes)


def test_load_simple_switch_track(tmp_path: Path) -> None:
    payload = bytearray()
    payload.extend(_varint(0))  # delta
    payload.append(0x10)  # SwitchColour
    payload.extend(struct.pack("<H", 0))  # transition
    payload.append(0x01)  # palette index 1 (white)
    payload.extend(struct.pack("<H", 960))  # hold one beat

    data = b"".join((_build_head_chunk(), _chunk("TEMP", b""), _build_pad_chunk(bytes(payload))))

    track_path = tmp_path / "switch.lstf"
    track_path.write_bytes(data)

    program = load_lstf(track_path)
    assert isinstance(program, LSTFProgram)
    assert program.is_generic
    assert set(program.pad_tracks.keys()) == {Pad.CENTRE}

    centre_track = program.pad_tracks[Pad.CENTRE]
    assert pytest.approx(0.5, rel=1e-3) == centre_track.duration
    assert len(centre_track.commands) == 1
    command = centre_track.commands[0]
    assert command.action == "switch"
    assert command.colour == (0xFF, 0xFF, 0xFF)


def test_multi_pad_track_is_not_generic(tmp_path: Path) -> None:
    centre = bytearray()
    centre.extend(_varint(0))
    centre.append(0x10)
    centre.extend(struct.pack("<H", 0))
    centre.append(0x04)  # palette index 4 (deep red)
    centre.extend(struct.pack("<H", 480))

    left = bytearray()
    left.extend(_varint(0))
    left.append(0x10)
    left.extend(struct.pack("<H", 0))
    left.append(0x08)  # palette index 8
    left.extend(struct.pack("<H", 480))

    data = b"".join(
        (
            _build_head_chunk(),
            _chunk("TEMP", b""),
            _build_pad_chunk(bytes(centre), pad_index=0),
            _build_pad_chunk(bytes(left), pad_index=1),
        )
    )

    track_path = tmp_path / "multi.lstf"
    track_path.write_bytes(data)

    program = load_lstf(track_path)
    assert not program.is_generic
    assert set(program.pad_tracks.keys()) == {Pad.CENTRE, Pad.LEFT}

