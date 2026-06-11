"""Structured NDJSON capture helpers for diagnostics and protocol events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic
from typing import IO, Any, Mapping, Sequence

SCHEMA_VERSION = "1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex_payload(payload: Sequence[int] | bytes | bytearray) -> str:
    return "".join(f"{int(byte) & 0xFF:02x}" for byte in payload)


@dataclass(frozen=True)
class CaptureRecord:
    record_type: str
    portal_id: str = "default"
    timestamp: str = field(default_factory=_utc_now)
    monotonic_offset_ms: int = 0
    schema_version: str = SCHEMA_VERSION
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "monotonic_offset_ms": self.monotonic_offset_ms,
            "record_type": self.record_type,
            "portal_id": self.portal_id,
        }
        data.update(self.payload)
        return data


class CaptureWriter:
    """Write schema-versioned capture records as newline-delimited JSON."""

    def __init__(self, target: str | Path | IO[str], *, portal_id: str = "default", redact: bool = False) -> None:
        self.portal_id = portal_id
        self.redact = redact
        self._started = monotonic()
        self._owns_file = not hasattr(target, "write")
        self._file: IO[str]
        if self._owns_file:
            self._file = open(Path(target), "a", encoding="utf-8")
        else:
            self._file = target  # type: ignore[assignment]

    def close(self) -> None:
        self._file.flush()
        if self._owns_file:
            self._file.close()

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _offset_ms(self) -> int:
        return int((monotonic() - self._started) * 1000)

    def write(self, record_type: str, **payload: Any) -> CaptureRecord:
        if self.redact:
            for key in ("uid", "serial_number"):
                if key in payload and payload[key] is not None:
                    payload[key] = "<redacted>"
        record = CaptureRecord(
            record_type=record_type,
            portal_id=str(payload.pop("portal_id", self.portal_id)),
            monotonic_offset_ms=self._offset_ms(),
            payload=payload,
        )
        self._file.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        self._file.flush()
        return record

    def packet(self, direction: str, payload: Sequence[int] | bytes | bytearray, **extra: Any) -> CaptureRecord:
        return self.write("packet", direction=direction, payload_hex=_hex_payload(payload), **extra)

    def tag_event(self, *, uid: str, pad: str | None, event_type: str, character_id: int | None = None, character_name: str | None = None, **extra: Any) -> CaptureRecord:
        return self.write(
            "tag_event",
            uid=uid,
            pad=pad,
            event_type=event_type,
            character_id=character_id,
            character_name=character_name,
            **extra,
        )


__all__ = ["CaptureRecord", "CaptureWriter", "SCHEMA_VERSION"]
