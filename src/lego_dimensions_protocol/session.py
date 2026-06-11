"""NDJSON record/replay helpers for LEGO Dimensions sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, IO, Iterable, Iterator, Mapping, Sequence

SCHEMA_VERSION = "1"
KNOWN_RECORD_TYPES = {"session_started", "session_finished", "tag_event", "light_command", "packet", "warning", "error"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SessionRecord:
    record_type: str
    portal_id: str = "default"
    monotonic_offset_ms: int = 0
    timestamp: str = field(default_factory=_now)
    schema_version: str = SCHEMA_VERSION
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "monotonic_offset_ms": self.monotonic_offset_ms,
            "record_type": self.record_type,
            "portal_id": self.portal_id,
        }
        data.update(self.payload)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SessionRecord":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported session schema_version: {data.get('schema_version')!r}")
        missing = {"timestamp", "monotonic_offset_ms", "record_type", "portal_id"} - set(data)
        if missing:
            raise ValueError(f"Session record missing required fields: {', '.join(sorted(missing))}")
        payload = {k: v for k, v in data.items() if k not in {"schema_version", "timestamp", "monotonic_offset_ms", "record_type", "portal_id"}}
        return cls(record_type=str(data["record_type"]), portal_id=str(data["portal_id"]), monotonic_offset_ms=int(data["monotonic_offset_ms"]), timestamp=str(data["timestamp"]), payload=payload)


class SessionWriter:
    def __init__(self, target: str | Path | IO[str], *, portal_id: str = "default") -> None:
        self.portal_id = portal_id
        self._started = time.monotonic()
        self._owns_file = not hasattr(target, "write")
        self._file: IO[str] = open(Path(target), "a", encoding="utf-8") if self._owns_file else target  # type: ignore[assignment]

    def close(self) -> None:
        self._file.flush()
        if self._owns_file:
            self._file.close()

    def __enter__(self) -> "SessionWriter":
        self.write("session_started")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.write("session_finished", error=str(exc) if exc else None)
        self.close()

    def write(self, record_type: str, **payload: Any) -> SessionRecord:
        record = SessionRecord(record_type=record_type, portal_id=str(payload.pop("portal_id", self.portal_id)), monotonic_offset_ms=int((time.monotonic() - self._started) * 1000), payload={k: v for k, v in payload.items() if v is not None})
        self._file.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        self._file.flush()
        return record


def read_session(source: str | Path | IO[str], *, skip_unknown: bool = True) -> Iterator[SessionRecord]:
    owns_file = not hasattr(source, "read")
    fh: IO[str] = open(Path(source), "r", encoding="utf-8") if owns_file else source  # type: ignore[assignment]
    try:
        for line_number, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            record = SessionRecord.from_dict(json.loads(stripped))
            if record.record_type not in KNOWN_RECORD_TYPES:
                if skip_unknown:
                    continue
                raise ValueError(f"Unknown record_type on line {line_number}: {record.record_type}")
            yield record
    finally:
        if owns_file:
            fh.close()


def validate_single_portal(records: Iterable[SessionRecord]) -> list[SessionRecord]:
    collected = list(records)
    portal_ids = {record.portal_id for record in collected}
    if len(portal_ids) > 1:
        raise ValueError("Replay of multiple portal_id values is not supported yet.")
    return collected


def dry_run_actions(records: Iterable[SessionRecord]) -> list[str]:
    actions: list[str] = []
    for record in validate_single_portal(records):
        if record.record_type == "tag_event":
            actions.append(f"tag {record.payload.get('event_type')} uid={record.payload.get('uid')} pad={record.payload.get('pad')}")
        elif record.record_type == "light_command":
            actions.append(f"light {record.payload.get('command_name')} pad={record.payload.get('pad')} colour={record.payload.get('colour')}")
        elif record.record_type in {"warning", "error"}:
            actions.append(f"{record.record_type}: {record.payload.get('message')}")
    return actions


__all__ = ["KNOWN_RECORD_TYPES", "SCHEMA_VERSION", "SessionRecord", "SessionWriter", "dry_run_actions", "read_session", "validate_single_portal"]
