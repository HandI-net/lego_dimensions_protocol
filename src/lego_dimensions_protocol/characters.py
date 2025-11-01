"""Utilities for looking up LEGO Dimensions character metadata."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Dict, Iterable, Optional

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_VENDOR_ROOT = _PACKAGE_ROOT.parent.parent / "vendor" / "ldnfctags" / "src"
_WORLD_HEADER = _VENDOR_ROOT / "legodimensions_ntag.h"
_CHARACTER_SOURCE = _VENDOR_ROOT / "legodimensions_characters.c"


@dataclass(frozen=True)
class CharacterInfo:
    """Human readable metadata for a Dimensions character."""

    id: int
    name: str
    world: str


_WORLD_PATTERN = re.compile(r"#define\s+(WORLD_[A-Z0-9_]+)\s+\"([^\"]+)\"")
_CHARACTER_PATTERN = re.compile(
    r"/\*\s*(\d{2})\s*\*/\s*\{\s*\"([^\"]*)\"\s*,\s*([A-Z0-9_]+)\s*\}"
)


@lru_cache(maxsize=1)
def _load_worlds() -> Dict[str, str]:
    worlds: Dict[str, str] = {"NTAG_UNKNOWN": "UNKNOWN"}
    try:
        contents = _WORLD_HEADER.read_text(encoding="utf-8")
    except FileNotFoundError:  # pragma: no cover - optional vendor drop
        return worlds
    for match in _WORLD_PATTERN.finditer(contents):
        key, value = match.groups()
        worlds[key] = value
    return worlds


@lru_cache(maxsize=1)
def _load_characters() -> Dict[int, CharacterInfo]:
    worlds = _load_worlds()
    characters: Dict[int, CharacterInfo] = {}
    try:
        contents = _CHARACTER_SOURCE.read_text(encoding="utf-8")
    except FileNotFoundError:  # pragma: no cover - optional vendor drop
        return characters

    for match in _CHARACTER_PATTERN.finditer(contents):
        identifier, name, world_key = match.groups()
        try:
            char_id = int(identifier)
        except ValueError:
            continue
        world = worlds.get(world_key, worlds.get("NTAG_UNKNOWN", "UNKNOWN"))
        characters[char_id] = CharacterInfo(id=char_id, name=name or "UNKNOWN", world=world)
    return characters


def get_character(character_id: int) -> Optional[CharacterInfo]:
    """Return metadata for *character_id* when available."""

    return _load_characters().get(int(character_id))


def iter_characters() -> Iterable[CharacterInfo]:
    """Yield known character entries from the vendor catalog."""

    return _load_characters().values()


__all__ = ["CharacterInfo", "get_character", "iter_characters"]
