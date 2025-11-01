"""Helpers for preparing and applying LEGO Dimensions tag edits."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .crypto import (
    encrypt_character_pages,
    generate_password_bytes,
)
from .gateway import Gateway, Pad
from .rfid import _pad_to_request_index

LOGGER = logging.getLogger(__name__)

_WRITE_COMMAND = 0xD4
_WRITE_FLAG = 0x01
_PASSWORD_PAGE = 0x2B
_CHARACTER_PAGES: Tuple[int, int] = (0x24, 0x25)
_CLEAR_PAGES: Tuple[int, ...] = (0x26,)


def _ensure_uid(uid: Sequence[int] | str) -> Tuple[int, ...]:
    if isinstance(uid, str):
        cleaned = "".join(ch for ch in uid if ch.isalnum())
        if len(cleaned) != 14:
            raise ValueError("A UID string must contain exactly 14 hexadecimal digits.")
        try:
            return tuple(int(cleaned[index : index + 2], 16) for index in range(0, 14, 2))
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError("UID strings must contain hexadecimal characters only.") from exc
    if len(uid) != 7:
        raise ValueError("A LEGO Dimensions UID must contain exactly seven bytes.")
    return tuple(int(value) & 0xFF for value in uid)


def _split_word(value: int) -> Tuple[int, int, int, int]:
    return (
        (value >> 24) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    )


def _format_bytes(values: Sequence[int]) -> str:
    return " ".join(f"{value:02x}" for value in values)


@dataclass(frozen=True)
class TagWritePlan:
    """Represents the NFC page updates required to retag a figure."""

    uid: Tuple[int, ...]
    pad: Pad
    pad_index: int
    character_id: int
    password: Tuple[int, int, int, int]
    character_pages: Dict[int, Tuple[int, int, int, int]]
    clear_pages: Tuple[int, ...] = _CLEAR_PAGES

    @property
    def uid_hex(self) -> str:
        return "".join(f"{value:02x}" for value in self.uid)

    def iter_page_payloads(self) -> Iterable[Tuple[int, Tuple[int, int, int, int]]]:
        yield (_PASSWORD_PAGE, self.password)
        for page in _CHARACTER_PAGES:
            payload = self.character_pages.get(page)
            if payload is not None:
                yield (page, payload)
        for page in self.clear_pages:
            yield (page, (0, 0, 0, 0))


class TagEditor:
    """Prepare and optionally write updated payloads for a tag on the pad."""

    def __init__(self, gateway: Optional[Gateway] = None) -> None:
        self._gateway = gateway or Gateway()
        self._owns_gateway = gateway is None

    @property
    def gateway(self) -> Gateway:
        return self._gateway

    def close(self) -> None:
        if self._owns_gateway:
            self._gateway.close()

    def __enter__(self) -> "TagEditor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def build_character_plan(
        self,
        uid: Sequence[int] | str,
        *,
        pad: Pad,
        character_id: int,
    ) -> TagWritePlan:
        uid_bytes = _ensure_uid(uid)
        pad_index = _pad_to_request_index(pad)
        if pad_index is None:
            raise ValueError("Writes can only target the left, centre, or right pad.")

        encrypted = encrypt_character_pages(uid_bytes, character_id)
        character_pages = {
            _CHARACTER_PAGES[0]: _split_word(encrypted[0]),
            _CHARACTER_PAGES[1]: _split_word(encrypted[1]),
        }
        password = generate_password_bytes(uid_bytes)

        return TagWritePlan(
            uid=uid_bytes,
            pad=pad,
            pad_index=pad_index,
            character_id=character_id,
            password=password,
            character_pages=character_pages,
        )

    def describe_plan(self, plan: TagWritePlan) -> str:
        lines = [
            f"UID: {plan.uid_hex}",
            f"Pad: {plan.pad.name}",
            f"Character ID: {plan.character_id}",
            f"Password page (0x{_PASSWORD_PAGE:02x}): {_format_bytes(plan.password)}",
        ]
        for page, payload in plan.character_pages.items():
            lines.append(f"Character page 0x{page:02x}: {_format_bytes(payload)}")
        for page in plan.clear_pages:
            lines.append(f"Clear page 0x{page:02x}: 00 00 00 00")
        return "\n".join(lines)

    def _build_write_command(
        self,
        pad_index: int,
        page: int,
        payload: Sequence[int],
    ) -> List[int]:
        page_bytes = [int(value) & 0xFF for value in payload]
        if len(page_bytes) != 4:
            raise ValueError("Tag pages must be written in four byte chunks.")
        payload_bytes = [page & 0xFF, pad_index & 0xFF, _WRITE_FLAG, *page_bytes, 0x00, 0x00]
        command = [0x55, len(payload_bytes) + 1, _WRITE_COMMAND, *payload_bytes]
        LOGGER.debug(
            "Prepared write command for page 0x%02x (pad index %s): %s",
            page,
            pad_index,
            _format_bytes(command),
        )
        return command

    def apply_plan(self, plan: TagWritePlan, *, dry_run: bool = True) -> List[List[int]]:
        commands = [
            self._build_write_command(plan.pad_index, page, payload)
            for page, payload in plan.iter_page_payloads()
        ]

        if dry_run:
            LOGGER.info("Dry run: planned %s tag writes", len(commands))
            for command in commands:
                LOGGER.info("Command: %s", _format_bytes(command))
            return commands

        for command in commands:
            self._gateway.send_command(command)
        LOGGER.info(
            "Retagged %s on %s with character %s",
            plan.uid_hex,
            plan.pad.name,
            plan.character_id,
        )
        return commands


__all__ = ["TagEditor", "TagWritePlan", "_ensure_uid"]
