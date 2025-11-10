"""High-level helpers for interacting with LEGO Dimensions RFID tags."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import time
from threading import Event, Lock, Thread, current_thread
from typing import TYPE_CHECKING, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from .gateway import Gateway, Pad
from . import characters
from .crypto import decrypt_character_pages

if TYPE_CHECKING:  # pragma: no cover - typing helper only
    from .characters import CharacterInfo

LOGGER = logging.getLogger(__name__)


class TagTrackerError(RuntimeError):
    """Raised when the tag tracker can no longer communicate with the portal."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        if cause is not None:
            try:  # pragma: no cover - attribute assignment guard
                self.__cause__ = cause
            except Exception:  # pragma: no cover - extremely defensive
                pass

_PAD_REQUEST_INDEX: Dict[Pad, int] = {
    Pad.LEFT: 0,
    Pad.CENTRE: 1,
    Pad.RIGHT: 2,
}

_PAGE_RESPONSE_COMMAND = 0x19
_PAGE_REQUEST_CODE = 0xD2
_TAG_EVENT_COMMAND = 0x56
_PAGE_READ_FLAG = 0x23
_CHARACTER_PAGES: Tuple[int, int] = (0x24, 0x25)
_UID_LENGTH = 7
_PAGE_RESPONSE_PAD_INDEX = 5


def _format_page_payload(values: Sequence[int]) -> str:
    return " ".join(f"{int(value) & 0xFF:02x}" for value in values)


def _format_character_pages(pages: Dict[int, Sequence[int]]) -> str:
    if not pages:
        return "<no pages>"
    return ", ".join(
        f"0x{page:02X}=\"{_format_page_payload(payload)}\""
        for page, payload in sorted(pages.items())
    )


def _page_to_int(payload: Sequence[int]) -> int:
    value = 0
    for byte in payload:
        value = (value << 8) | (int(byte) & 0xFF)
    return value & 0xFFFFFFFF


def _pad_to_request_index(pad: Pad) -> Optional[int]:
    try:
        return _PAD_REQUEST_INDEX[pad]
    except KeyError:
        return None


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
    character_id: Optional[int] = None
    character: Optional["CharacterInfo"] = None

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
        self._state_lock = Lock()
        self._pending_exception: Optional[BaseException] = None

        self._pending_packets: List[Tuple[int, ...]] = []
        self._page_cache: Dict[int, Dict[int, Tuple[int, int, int, int]]] = {}
        self._seen_uids: set[str] = set()

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
        with self._state_lock:
            self._pending_exception = None
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
        while True:
            pending = self._get_pending_exception()
            if pending is not None:
                raise pending
            if self._stop_event.is_set():
                return
            event = self.poll_once()
            if event is not None:
                yield event

    def poll_once(self) -> Optional[TagEvent]:
        pending = self._get_pending_exception()
        if pending is not None:
            raise pending
        packet = self._get_packet(self.poll_timeout)
        if packet is None:
            return self._record_timeout()

        self._timeout_streak = 0

        event = self._handle_packet(packet)
        if event is None:
            return None

        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # pragma: no cover - listener isolation
                LOGGER.exception("Error while handling tag event for %s", event.uid)

        return event

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except TagTrackerError:
                return
            except Exception as exc:  # pragma: no cover - defensive worker guard
                if self._stop_event.is_set():
                    return
                self._record_exception(exc)
                return

    def _record_timeout(self) -> None:
        if self._timeout_streak == 0:
            LOGGER.debug(
                "RFID poll timed out after %sms; waiting for tag activity",
                self.poll_timeout,
            )
        self._timeout_streak += 1
        return None

    def _get_packet(self, timeout: int) -> Optional[Tuple[int, ...]]:
        if self._pending_packets:
            return self._pending_packets.pop(0)
        return self._read_gateway_packet(timeout)

    def _read_gateway_packet(self, timeout: int) -> Optional[Tuple[int, ...]]:
        try:
            return self._gateway.read_packet(timeout=timeout)
        except Exception as exc:  # pragma: no cover - USB backend specific
            timeout_checker = getattr(self._gateway, "is_timeout_error", None)
            if callable(timeout_checker) and timeout_checker(exc):
                return None
            if self._stop_event.is_set():
                return None
            tracker_exc = self._record_exception(exc)
            raise tracker_exc

    def _record_exception(self, exc: BaseException) -> TagTrackerError:
        if self._stop_event.is_set():
            return exc if isinstance(exc, TagTrackerError) else TagTrackerError(
                "Portal communication failed", cause=exc
            )
        first = False
        with self._state_lock:
            if isinstance(exc, TagTrackerError):
                tracker_exc = exc
            else:
                tracker_exc = TagTrackerError(
                    "Portal communication failed while reading from the toy pad.",
                    cause=exc,
                )
            if self._pending_exception is None:
                self._pending_exception = tracker_exc
                first = True
        if first:
            LOGGER.error(
                "Tag tracker encountered a fatal gateway error; shutting down: %s",
                tracker_exc.cause or tracker_exc,
            )
            LOGGER.debug(
                "Fatal gateway exception details", exc_info=True
            )
        self._stop_event.set()
        return tracker_exc

    def _get_pending_exception(self) -> Optional[BaseException]:
        with self._state_lock:
            pending = self._pending_exception

        if pending is None:
            return None

        worker = self._thread
        if (
            worker is not None
            and worker.is_alive()
            and worker is not current_thread()
        ):
            self._stop_event.set()
            worker.join()
        if worker is not current_thread():
            self._thread = None

        return pending

    def _handle_packet(self, packet: Tuple[int, ...]) -> Optional[TagEvent]:
        if not packet:
            return None

        if packet[0] == 0x55 and len(packet) > 2 and packet[2] == 0x01:
            self._cache_page_response(packet)
            return None

        if packet[0] != _TAG_EVENT_COMMAND or len(packet) < 6 + _UID_LENGTH:
            return None

        pad_code = packet[2]
        try:
            pad = Pad(pad_code)
        except ValueError:
            LOGGER.debug("Unknown pad code in RFID packet: %s", pad_code)
            pad = None

        removed = bool(packet[5])
        uid_bytes = tuple(int(value) & 0xFF for value in packet[6 : 6 + _UID_LENGTH])
        uid = _format_uid(uid_bytes)
        event_type = TagEventType.REMOVED if removed else TagEventType.ADDED

        character_id: Optional[int] = None
        character_info: Optional["CharacterInfo"] = None

        if not removed and pad is not None:
            character_id, character_info = self._resolve_character(uid_bytes, pad)

        with self._lock:
            if removed:
                self._tag_locations.pop(uid, None)
                request_index = _pad_to_request_index(pad) if pad is not None else None
                if request_index is not None:
                    self._page_cache.pop(request_index, None)
            else:
                self._tag_locations[uid] = pad

        event = TagEvent(
            uid=uid,
            pad=None if removed else pad,
            type=event_type,
            character_id=character_id,
            character=character_info,
        )

        if not event.removed and event.character is not None:
            with self._lock:
                if uid not in self._seen_uids:
                    self._seen_uids.add(uid)
                    LOGGER.info(
                        "Detected %s (ID %s, %s) on %s [uid %s]",
                        event.character.name,
                        event.character_id,
                        event.character.world,
                        event.pad,
                        event.uid,
                    )

        return event

    def _cache_page_response(self, packet: Tuple[int, ...]) -> None:
        if len(packet) <= _PAGE_RESPONSE_PAD_INDEX:
            return

        pad_index = packet[_PAGE_RESPONSE_PAD_INDEX]
        pages: Dict[int, Tuple[int, int, int, int]] = {}
        for index in range(2, len(packet) - 4):
            page = packet[index]
            if page not in _CHARACTER_PAGES:
                continue
            chunk = tuple(int(value) & 0xFF for value in packet[index + 1 : index + 5])
            if len(chunk) == 4:
                pages[page] = chunk  # type: ignore[assignment]

        if not pages:
            return

        with self._lock:
            cache = self._page_cache.setdefault(pad_index, {})
            cache.update(pages)

    def _resolve_character(
        self,
        uid_bytes: Tuple[int, ...],
        pad: Pad,
    ) -> Tuple[Optional[int], Optional["CharacterInfo"]]:
        pad_index = _pad_to_request_index(pad)
        if pad_index is None:
            return None, None

        uid_hex = _format_uid(uid_bytes)
        pages = self._get_cached_pages(pad_index)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "Pad %s initial cached character pages for tag %s: %s",
                pad,
                uid_hex,
                _format_character_pages(pages),
            )
        missing = [page for page in _CHARACTER_PAGES if page not in pages]
        if missing:
            LOGGER.debug(
                "Requesting missing character pages %s for tag %s on pad %s",
                ", ".join(f"0x{page:02X}" for page in missing),
                uid_hex,
                pad,
            )
            self._request_pages(pad_index, missing)
            pages = self._get_cached_pages(pad_index)
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(
                    "Pad %s refreshed cached character pages for tag %s: %s",
                    pad,
                    uid_hex,
                    _format_character_pages(pages),
                )

        if any(page not in pages for page in _CHARACTER_PAGES):
            LOGGER.debug(
                "Tag %s is missing required character pages after refresh; cached=%s",
                uid_hex,
                _format_character_pages(pages),
            )
            return None, None

        page_payloads = [pages[index] for index in _CHARACTER_PAGES]
        page_bytes = tuple(_format_page_payload(payload) for payload in page_payloads)
        page_words = tuple(_page_to_int(payload) for payload in page_payloads)
        LOGGER.debug(
            "Character page payloads for tag %s on pad %s: 0x%02X=[%s], 0x%02X=[%s]",
            uid_hex,
            pad,
            _CHARACTER_PAGES[0],
            page_bytes[0],
            _CHARACTER_PAGES[1],
            page_bytes[1],
        )

        try:
            character_id = decrypt_character_pages(
                uid_bytes,
                page_payloads[0],
                page_payloads[1],
            )
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Failed to decrypt character payload for %s", pad)
            return None, None

        LOGGER.debug(
            "Decrypted character payload for tag %s: 0x%08X (pages 0x%02X=0x%08X, 0x%02X=0x%08X)",
            uid_hex,
            character_id,
            _CHARACTER_PAGES[0],
            page_words[0],
            _CHARACTER_PAGES[1],
            page_words[1],
        )

        if not character_id:
            LOGGER.debug(
                "Tag %s produced an empty character identifier after decryption; raw words were 0x%08X/0x%08X",
                uid_hex,
                page_words[0],
                page_words[1],
            )
            return None, None

        character_info = characters.get_character(character_id)
        if character_info is None:
            LOGGER.debug(
                "Unknown character id %s (0x%08X) for uid %s",
                character_id,
                character_id,
                uid_hex,
            )
            return character_id, None

        if character_info.id != character_id:
            LOGGER.warning(
                "Character lookup mismatch for uid %s: catalog id %s does not match decrypted id %s",
                uid_hex,
                character_info.id,
                character_id,
            )

        LOGGER.debug(
            "Resolved tag %s to %s (ID %s, %s)",
            uid_hex,
            character_info.name,
            character_id,
            character_info.world,
        )
        return character_id, character_info

    def _get_cached_pages(self, pad_index: int) -> Dict[int, Tuple[int, int, int, int]]:
        with self._lock:
            cached = self._page_cache.get(pad_index)
            return dict(cached) if cached is not None else {}

    def _request_pages(self, pad_index: int, pages: Sequence[int]) -> None:
        for page in pages:
            self._send_page_request(pad_index, page)

    def _send_page_request(self, pad_index: int, page: int) -> None:
        command = [0x55, 0x04, _PAGE_REQUEST_CODE, page, pad_index, _PAGE_READ_FLAG]
        self._gateway.send_command(command)
        deadline = time.monotonic() + max(self.poll_timeout, 10) / 1000.0

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            timeout_ms = max(int(remaining * 1000), 1)
            packet = self._read_gateway_packet(timeout_ms)
            if packet is None:
                continue
            if packet[0] == 0x55 and len(packet) > 2 and packet[2] == 0x01:
                self._cache_page_response(packet)
                if page in self._get_cached_pages(pad_index):
                    return
                continue
            self._pending_packets.append(packet)
        LOGGER.debug("Timed out waiting for page %s on pad index %s", page, pad_index)


def watch_pads(tag_colours: Optional[Dict[str, Sequence[int]]] = None) -> None:
    tag_colours = tag_colours or {}

    def _handle_event(event: TagEvent) -> None:
        if event.removed:
            LOGGER.info("Tag %s removed from the portal", event.uid)
            return
        if event.character is not None:
            LOGGER.info(
                "Tag %s placed on pad %s: %s (ID %s, %s)",
                event.uid,
                event.pad,
                event.character.name,
                event.character_id,
                event.character.world,
            )
        else:
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
    "TagTrackerError",
    "watch_pads",
]
