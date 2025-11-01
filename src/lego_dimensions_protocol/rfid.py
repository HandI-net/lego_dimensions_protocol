"""High-level helpers for interacting with LEGO Dimensions RFID tags."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from threading import Event, Lock, Thread
from typing import Callable, Dict, Iterator, List, Optional, Sequence

from .gateway import Gateway, Pad

LOGGER = logging.getLogger(__name__)


class TagEventType(str, Enum):
    """The type of event emitted by the :class:`TagTracker`."""

    ADDED = "added"
    REMOVED = "removed"

def _format_uid(uid_bytes: Sequence[int]) -> str:
    return "".join(f"{value:02x}" for value in uid_bytes)


@dataclass(frozen=True)
class TagEvent:
    """Represents a change detected on the toy pad."""

    uid: str
    pad: Optional[Pad]
    type: TagEventType

    @property
    def removed(self) -> bool:
        return self.type is TagEventType.REMOVED


class TagTracker:
    """Track tags as they are added to or removed from the toy pad."""

    def __init__(
        self,
        gateway: Optional[Gateway] = None,
        *,
        poll_timeout: int = 10,
        auto_start: bool = True,
    ) -> None:
        self._gateway = gateway or Gateway()
        self._owns_gateway = gateway is None
        self.poll_timeout = poll_timeout

        self._listeners: List[Callable[[TagEvent], None]] = []
        self._tag_locations: Dict[str, Optional[Pad]] = {}
        self._lock = Lock()

        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._timeout_streak = 0

        if auto_start:
            self.start()

    @property
    def gateway(self) -> Gateway:
        return self._gateway

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, name="TagTracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join()
        self._thread = None

    def close(self) -> None:
        self.stop()
        if self._owns_gateway:
            self._gateway.close()

    def __enter__(self) -> "TagTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def add_listener(self, listener: Callable[[TagEvent], None]) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[TagEvent], None]) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:  # pragma: no cover - defensive cleanup
            pass

    def list_tags(self) -> List[str]:
        with self._lock:
            return list(self._tag_locations.keys())

    def locate_tag(self, tag_uid: str) -> Optional[Pad]:
        with self._lock:
            return self._tag_locations.get(tag_uid)

    def iter_events(self) -> Iterator[TagEvent]:
        while not self._stop_event.is_set():
            event = self.poll_once()
            if event is not None:
                yield event

    def poll_once(self) -> Optional[TagEvent]:
        try:
            packet = self._gateway.read_packet(timeout=self.poll_timeout)
        except Exception as exc:  # pragma: no cover - USB backend specific
            timeout_checker = getattr(self._gateway, "is_timeout_error", None)
            if callable(timeout_checker) and timeout_checker(exc):
                return self._record_timeout()
            raise

        if packet is None:
            return self._record_timeout()

        self._timeout_streak = 0

        if len(packet) < 12:
            return None
        if packet[0] != 0x56:
            return None

        pad_code = packet[2]
        pad: Optional[Pad]
        try:
            pad = Pad(pad_code)
        except ValueError:
            LOGGER.debug("Unknown pad code in RFID packet: %s", pad_code)
            pad = None

        removed = bool(packet[5])
        uid = _format_uid(packet[6:12])
        event_type = TagEventType.REMOVED if removed else TagEventType.ADDED

        with self._lock:
            if removed:
                self._tag_locations.pop(uid, None)
            else:
                self._tag_locations[uid] = pad

        event = TagEvent(uid=uid, pad=None if removed else pad, type=event_type)

        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # pragma: no cover - listener isolation
                LOGGER.exception("Error while handling tag event for %s", event.uid)

        return event

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()

    def _record_timeout(self) -> None:
        if self._timeout_streak == 0:
            LOGGER.info(
                "RFID poll timed out after %sms; waiting for tag activity",
                self.poll_timeout,
            )
        self._timeout_streak += 1
        return None


def watch_pads(tag_colours: Optional[Dict[str, Sequence[int]]] = None) -> None:
    tag_colours = tag_colours or {}

    def _handle_event(event: TagEvent) -> None:
        if event.removed:
            LOGGER.info("Tag %s removed from the portal", event.uid)
            return
        LOGGER.info("Tag %s placed on pad %s", event.uid, event.pad)
        colour = tag_colours.get(event.uid)
        if colour and event.pad is not None:
            tracker.gateway.switch_pad(event.pad, colour)

    with TagTracker() as tracker:
        tracker.add_listener(_handle_event)
        try:
            for _ in tracker.iter_events():
                pass
        except KeyboardInterrupt:  # pragma: no cover - CLI helper
            LOGGER.info("Stopping tag watcher")


__all__ = [
    "TagEvent",
    "TagEventType",
    "TagTracker",
    "watch_pads",
]
