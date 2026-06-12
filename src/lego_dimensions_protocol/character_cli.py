"""Command-line friendly character catalog lookup helpers."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Iterable, Optional, Sequence

from .characters import CharacterInfo, get_character, iter_characters


class CharacterResolutionError(ValueError):
    """Raised when a character query cannot be resolved safely."""

    def __init__(self, message: str, candidates: Sequence[CharacterInfo] = ()) -> None:
        super().__init__(message)
        self.candidates = tuple(candidates)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def search_characters(query: str, catalog: Optional[Iterable[CharacterInfo]] = None) -> list[CharacterInfo]:
    """Return characters whose names or IDs match *query*.

    Matching is case-insensitive and includes exact numeric IDs, exact names, and
    partial name/world matches for discovery-oriented CLI output.
    """

    entries = sorted(catalog if catalog is not None else iter_characters(), key=lambda item: item.id)
    stripped = query.strip()
    if stripped.isdecimal():
        found = get_character(int(stripped))
        return [found] if found is not None else []
    needle = _normalise(stripped)
    return [
        entry
        for entry in entries
        if needle in _normalise(entry.name) or needle in _normalise(entry.world)
    ]


def resolve_character(value: int | str, catalog: Optional[Iterable[CharacterInfo]] = None) -> CharacterInfo:
    """Resolve *value* to exactly one character.

    The resolver accepts integer IDs, decimal strings, exact names, case-insensitive
    names, and unambiguous partial names. Ambiguous partial matches fail rather
    than guessing.
    """

    if isinstance(value, int) or str(value).strip().isdecimal():
        character_id = int(value)
        character = get_character(character_id)
        if character is None:
            raise CharacterResolutionError(f"Unknown character ID: {character_id}")
        return character

    entries = sorted(catalog if catalog is not None else iter_characters(), key=lambda item: item.id)
    needle = _normalise(str(value))

    exact = [entry for entry in entries if _normalise(entry.name) == needle]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise CharacterResolutionError(f"Character name is ambiguous: {value}", exact)

    partial = [entry for entry in entries if needle in _normalise(entry.name)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise CharacterResolutionError(f"Character name is ambiguous: {value}", partial)
    raise CharacterResolutionError(f"Unknown character: {value}")


def character_to_dict(character: CharacterInfo) -> dict[str, object]:
    return asdict(character)


def _print_characters(entries: Sequence[CharacterInfo], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps([character_to_dict(entry) for entry in entries], indent=2, sort_keys=True))
        return
    for entry in entries:
        print(f"{entry.id:03d}  {entry.name}  ({entry.world})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lego-dimensions-characters")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List known characters")
    list_parser.add_argument("--json", action="store_true", dest="json_after", help="Emit machine-readable JSON output")

    search = subparsers.add_parser("search", help="Search character names and worlds")
    search.add_argument("query")
    search.add_argument("--json", action="store_true", dest="json_after", help="Emit machine-readable JSON output")

    show = subparsers.add_parser("show", help="Show one character by ID or name")
    show.add_argument("character")
    show.add_argument("--json", action="store_true", dest="json_after", help="Emit machine-readable JSON output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    as_json = bool(args.json or getattr(args, "json_after", False))

    if args.command == "list":
        _print_characters(sorted(iter_characters(), key=lambda item: item.id), as_json=as_json)
        return 0
    if args.command == "search":
        matches = search_characters(args.query)
        _print_characters(matches, as_json=as_json)
        return 0 if matches else 1
    if args.command == "show":
        try:
            character = resolve_character(args.character)
        except CharacterResolutionError as exc:
            parser.exit(1, f"{exc}\n")
        if as_json:
            print(json.dumps(character_to_dict(character), indent=2, sort_keys=True))
        else:
            print(f"ID: {character.id}\nName: {character.name}\nWorld: {character.world}")
        return 0
    parser.print_help()
    return 2


__all__ = [
    "CharacterResolutionError",
    "character_to_dict",
    "main",
    "resolve_character",
    "search_characters",
]

if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
