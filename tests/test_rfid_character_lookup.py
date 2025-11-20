"""Ensure tag tracking resolves characters using the shared catalog data."""

from __future__ import annotations

from typing import Sequence, Tuple

from lego_dimensions_protocol import characters, rfid
from lego_dimensions_protocol.gateway import Pad


class _StubGateway:
    """Minimal gateway stub that surfaces unexpected portal access in tests."""

    def read_packet(self, timeout: int) -> Tuple[int, ...]:  # pragma: no cover - defensive
        raise AssertionError("TagTracker attempted to read gateway packets during unit test")

    def send_command(self, command: Sequence[int]) -> None:  # pragma: no cover - defensive
        raise AssertionError("TagTracker attempted to send gateway commands during unit test")

    def close(self) -> None:  # pragma: no cover - defensive
        return


_BATMAN_UID = (0x04, 0x9A, 0x74, 0x6A, 0x0B, 0x40, 0x80)
_BATMAN_PAGE24 = (0x7A, 0x26, 0xA5, 0x33)
_BATMAN_PAGE25 = (0x86, 0x53, 0xEB, 0x64)
_BATMAN_ID = 0x00000001


def _make_tag_packet(uid: Tuple[int, ...]) -> Tuple[int, ...]:
    padding = (0x00, 0x00)
    return (
        0x56,
        0x00,
        Pad.LEFT.value,
        0x00,
        0x00,
        0x00,
        *uid,
        *padding,
    )


def _make_page_response_packet(pad: Pad) -> Tuple[int, ...]:
    return (
        0x55,
        0x13,
        0x01,
        pad.value,
        0x24,
        *_BATMAN_PAGE24,
        0x25,
        *_BATMAN_PAGE25,
    )


def test_handle_packet_includes_character_metadata() -> None:
    """_handle_packet should populate TagEvent with decrypted character data."""

    tracker = rfid.TagTracker(_StubGateway(), auto_start=False)
    pad_index = rfid._pad_to_request_index(Pad.LEFT)
    assert pad_index is not None
    tracker._page_cache[pad_index] = {  # type: ignore[attr-defined]
        0x24: _BATMAN_PAGE24,
        0x25: _BATMAN_PAGE25,
    }

    try:
        packet = _make_tag_packet(_BATMAN_UID)
        event = tracker._handle_packet(packet)
        assert event is not None
        assert event.character_id == _BATMAN_ID

        character = event.character
        assert character is not None
        assert character.id == _BATMAN_ID
        assert characters.get_character(_BATMAN_ID) == character
    finally:
        tracker.close()


def test_pad_request_index_matches_portal_pad_values() -> None:
    """Ensure page requests target the same pad identifiers emitted by the portal."""

    assert rfid._pad_to_request_index(Pad.CENTRE) == Pad.CENTRE.value
    assert rfid._pad_to_request_index(Pad.LEFT) == Pad.LEFT.value
    assert rfid._pad_to_request_index(Pad.RIGHT) == Pad.RIGHT.value


def test_page_response_populates_cache_and_resolves_character() -> None:
    """Processing a page response should fill the cache and resolve characters."""

    tracker = rfid.TagTracker(_StubGateway(), auto_start=False)
    pad_index = rfid._pad_to_request_index(Pad.LEFT)
    assert pad_index is not None

    try:
        tracker._pending_page_reads[pad_index] = {0x24, 0x25}  # type: ignore[attr-defined]

        packet = _make_page_response_packet(Pad.LEFT)
        tracker._handle_packet(packet)

        cache = tracker._page_cache[pad_index]  # type: ignore[attr-defined]
        assert cache[0x24] == _BATMAN_PAGE24
        assert cache[0x25] == _BATMAN_PAGE25
        assert pad_index not in tracker._pending_page_reads  # type: ignore[attr-defined]

        character_id, character = tracker._resolve_character(_BATMAN_UID, Pad.LEFT)
        assert character_id == _BATMAN_ID
        assert character is not None
        assert character.id == _BATMAN_ID
    finally:
        tracker.close()
