"""Minimal record/replay command line entry points."""

from __future__ import annotations

import argparse
import time
from typing import Optional, Sequence

from .rfid import TagTracker
from .session import SessionWriter, dry_run_actions, read_session


def record_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="lego-dimensions-record")
    parser.add_argument("path")
    parser.add_argument("--duration", type=float, default=None, help="Seconds to record before exiting")
    args = parser.parse_args(argv)
    deadline = None if args.duration is None else time.monotonic() + args.duration
    with SessionWriter(args.path) as writer, TagTracker(auto_start=False) as tracker:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            event = tracker.poll_once()
            if event is None:
                continue
            writer.write(
                "tag_event",
                uid=event.uid,
                pad=event.pad.name.lower() if event.pad else None,
                event_type=event.type.value,
                character_id=event.character_id,
                character_name=event.character.name if event.character else None,
            )
    return 0


def replay_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="lego-dimensions-replay")
    parser.add_argument("path")
    parser.add_argument("--speed", type=float, default=1.0, help="Reserved timing scale for future hardware replay")
    parser.add_argument("--dry-run", action="store_true", help="Print intended actions without touching hardware")
    args = parser.parse_args(argv)
    if args.speed <= 0:
        parser.error("--speed must be greater than zero")
    if not args.dry_run:
        parser.error("Hardware replay is not implemented yet; use --dry-run")
    for action in dry_run_actions(read_session(args.path)):
        print(action)
    return 0


__all__ = ["record_main", "replay_main"]

if __name__ == "__main__":  # pragma: no cover - helper message for direct module execution
    raise SystemExit("Use lego-dimensions-record or lego-dimensions-replay entry points.")
