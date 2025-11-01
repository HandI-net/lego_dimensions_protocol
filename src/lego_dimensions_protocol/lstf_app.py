"""CLI application for driving the portal with LSTF playlists triggered by tags."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import characters
from .gateway import Pad
from .lstf_player import LSTFManager, TrackCache, TrackHandle
from .rfid import TagEvent, TagEventType, TagTracker

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigEntry:
    track: Path
    persist: bool
    character_id: Optional[int] = None
    uid: Optional[str] = None
    description: Optional[str] = None

    def matches(self, event: TagEvent) -> bool:
        if self.uid:
            if not event.uid:
                return False
            if event.uid.lower() != self.uid:
                return False
        if self.character_id is not None and event.character_id != self.character_id:
            return False
        return True


@dataclass(frozen=True)
class AppConfig:
    default_track: Path
    entries: List[ConfigEntry]


@dataclass
class _ActiveTag:
    handle: TrackHandle
    entry: ConfigEntry
    pad: Optional[Pad]
    generic: bool
    persist: bool


class LSTFApplication:
    def __init__(self, config: AppConfig, *, poll_timeout: int = 250) -> None:
        self._config = config
        self._poll_timeout = poll_timeout
        self._cache = TrackCache()
        self._active_tags: Dict[str, _ActiveTag] = {}

    def run(self) -> None:
        LOGGER.info("Starting LSTF tag player")
        with TagTracker(poll_timeout=self._poll_timeout) as tracker:
            manager = LSTFManager(tracker.gateway)
            try:
                self._start_default(manager)
            except Exception:
                manager.close()
                raise

            def listener(event: TagEvent) -> None:
                self._handle_event(event, manager)

            tracker.add_listener(listener)

            try:
                for _ in tracker.iter_events():
                    pass
            except KeyboardInterrupt:
                LOGGER.info("Stopping LSTF player")
            finally:
                tracker.remove_listener(listener)
                manager.close()

    def _start_default(self, manager: LSTFManager) -> None:
        default_program = self._cache.get(self._config.default_track)
        if default_program.is_generic:
            raise ValueError("Default LSTF track must provide per-pad data.")
        manager.activate_default(default_program)
        LOGGER.info("Loaded default track %s", self._config.default_track)

    def _handle_event(self, event: TagEvent, manager: LSTFManager) -> None:
        if event.type is TagEventType.ADDED:
            self._handle_added(event, manager)
        elif event.type is TagEventType.REMOVED:
            self._handle_removed(event, manager)

    def _handle_added(self, event: TagEvent, manager: LSTFManager) -> None:
        entry = self._find_entry(event)
        if entry is None:
            LOGGER.debug("No configured track for tag %s", event.uid)
            return
        try:
            program = self._cache.get(entry.track)
        except Exception:
            LOGGER.exception("Failed to load LSTF track %s", entry.track)
            return

        description = entry.description or self._format_event_description(event)
        LOGGER.info("Tag %s activated %s", event.uid, description or entry.track.name)

        uid_key = event.uid.lower()

        if program.is_generic:
            if event.pad is None:
                LOGGER.warning(
                    "Cannot apply generic track %s without a pad assignment", entry.track
                )
                return
            handle = manager.apply_overlay(event.pad, program)
            self._active_tags[uid_key] = _ActiveTag(
                handle=handle,
                entry=entry,
                pad=event.pad,
                generic=True,
                persist=entry.persist,
            )
        else:
            manager.clear_overlays()
            if entry.persist:
                handle = manager.replace_track(program)
            else:
                handle = manager.push_track(program)
            self._active_tags[uid_key] = _ActiveTag(
                handle=handle,
                entry=entry,
                pad=None,
                generic=False,
                persist=entry.persist,
            )

    def _handle_removed(self, event: TagEvent, manager: LSTFManager) -> None:
        active = self._active_tags.pop(event.uid.lower(), None)
        if active is None:
            return
        if active.persist:
            LOGGER.debug("Track for %s persists after removal", event.uid)
            return
        if active.generic and active.pad is not None:
            manager.remove_overlay(active.pad)
        else:
            manager.pop_track(active.handle)

    def _find_entry(self, event: TagEvent) -> Optional[ConfigEntry]:
        for entry in self._config.entries:
            if entry.matches(event):
                return entry
        return None

    @staticmethod
    def _format_event_description(event: TagEvent) -> Optional[str]:
        if event.character is not None:
            return f"{event.character.name} ({event.character.world})"
        if event.character_id is not None:
            character = characters.get_character(event.character_id)
            if character is not None:
                return f"{character.name} ({character.world})"
        return None


def _load_config(path: Path) -> AppConfig:
    contents = json.loads(path.read_text(encoding="utf-8"))
    try:
        default_track = contents["default_track"]
    except KeyError as exc:
        raise ValueError("Configuration file missing 'default_track' entry") from exc

    entries_data = contents.get("tags", [])
    if not isinstance(entries_data, list):
        raise ValueError("'tags' entry in configuration must be a list")

    base_path = path.parent
    default_path = _resolve_track_path(base_path, default_track)

    entries: List[ConfigEntry] = []
    for raw_entry in entries_data:
        if not isinstance(raw_entry, dict):
            raise ValueError("Each tag entry must be a mapping")
        track_value = raw_entry.get("track")
        if not track_value:
            raise ValueError("Tag entry missing 'track' path")
        track_path = _resolve_track_path(base_path, track_value)
        persist = bool(raw_entry.get("persist", False))
        character_id = _coerce_character_id(raw_entry)
        uid_value = raw_entry.get("uid")
        uid = uid_value.lower() if isinstance(uid_value, str) else None
        if character_id is None and uid is None:
            raise ValueError("Tag entry must define either 'character_id', 'character', or 'uid'")
        description = raw_entry.get("description")
        entries.append(
            ConfigEntry(
                track=track_path,
                persist=persist,
                character_id=character_id,
                uid=uid,
                description=description,
            )
        )

    return AppConfig(default_track=default_path, entries=entries)


def _resolve_track_path(base: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate


def _coerce_character_id(entry: Dict[str, object]) -> Optional[int]:
    if "character_id" in entry:
        try:
            return int(entry["character_id"])
        except (TypeError, ValueError):
            raise ValueError("character_id must be an integer") from None
    name = entry.get("character")
    if not isinstance(name, str):
        return None
    lookup = _character_lookup()
    try:
        return lookup[name.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown character name {name!r}") from exc


def _character_lookup() -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for info in characters.iter_characters():
        mapping[info.name.lower()] = info.id
    return mapping


def main(argv: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Path to the LSTF tag configuration file")
    parser.add_argument("--poll-timeout", type=int, default=250, help="RFID poll timeout in ms")
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR)",
    )
    args = parser.parse_args(argv)

    log_level = getattr(logging, str(args.log_level).upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = _load_config(args.config)
    app = LSTFApplication(config, poll_timeout=args.poll_timeout)
    app.run()


__all__ = ["LSTFApplication", "main"]

