"""Interactive RFID light show demonstration for the LEGO Dimensions portal."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import Iterable, List, Sequence

from .gateway import Gateway, Pad, RGBColor
from .rfid import TagEventType, TagTracker

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LightAction:
    """Single lighting instruction used by the RFID light show."""

    pad: Pad
    colour: RGBColor
    duration: float

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("Durations must be positive when constructing a light action.")


_PALETTE: Sequence[RGBColor] = (
    RGBColor(255, 0, 0),
    RGBColor(255, 64, 0),
    RGBColor(255, 128, 0),
    RGBColor(255, 192, 0),
    RGBColor(255, 255, 0),
    RGBColor(128, 255, 0),
    RGBColor(0, 255, 0),
    RGBColor(0, 255, 128),
    RGBColor(0, 255, 255),
    RGBColor(0, 128, 255),
    RGBColor(0, 0, 255),
    RGBColor(128, 0, 255),
    RGBColor(192, 0, 255),
    RGBColor(255, 0, 255),
    RGBColor(255, 0, 128),
    RGBColor(255, 255, 255),
)

_PAD_SEQUENCE: Sequence[Pad] = (Pad.LEFT, Pad.CENTRE, Pad.RIGHT)


def _initial_cycle(gateway: Gateway, *, pause: float = 0.35) -> None:
    """Blank the pads, then briefly show the base colours on each position."""

    LOGGER.info("Cycling pads to indicate the demo is ready")
    gateway.blank_pads()
    start_cycle: Sequence[tuple[Pad, RGBColor]] = (
        (Pad.LEFT, RGBColor(255, 0, 0)),
        (Pad.CENTRE, RGBColor(0, 255, 0)),
        (Pad.RIGHT, RGBColor(0, 0, 255)),
        (Pad.ALL, RGBColor(255, 255, 255)),
    )
    for pad, colour in start_cycle:
        gateway.switch_pad(pad, colour)
        time.sleep(pause)
    gateway.blank_pads()


def _derive_actions_from_uid(uid: str) -> List[LightAction]:
    """Create a deterministic light sequence derived from the RFID UID string."""

    if not uid:
        return [LightAction(Pad.ALL, RGBColor(255, 255, 255), 0.4)]

    actions: List[LightAction] = []
    bytes_in_uid = [int(uid[i : i + 2], 16) for i in range(0, len(uid), 2)]
    if not bytes_in_uid:
        bytes_in_uid = [0]

    for index, value in enumerate(bytes_in_uid):
        pad = _PAD_SEQUENCE[(value + index) % len(_PAD_SEQUENCE)]
        colour = _PALETTE[value % len(_PALETTE)]
        on_duration = 0.25 + (value % 5) * 0.05
        off_duration = 0.12 + ((value // len(_PAD_SEQUENCE)) % 4) * 0.04
        actions.append(LightAction(pad=pad, colour=colour, duration=on_duration))
        actions.append(LightAction(pad=pad, colour=RGBColor(0, 0, 0), duration=off_duration))

    return actions


class _ActiveShow:
    """Background worker that plays a repeating sequence of pad actions."""

    def __init__(self, uid: str, gateway: Gateway, actions: Sequence[LightAction]) -> None:
        self.uid = uid
        self._gateway = gateway
        self._actions = list(actions) or [
            LightAction(Pad.ALL, RGBColor(255, 255, 255), 0.5)
        ]
        self._stop_event = Event()
        self._thread = Thread(target=self._run, name=f"RFIDLightShow[{uid}]", daemon=True)

    def start(self) -> None:
        LOGGER.debug("Starting light show for %s", self.uid)
        self._stop_event.clear()
        self._thread.start()

    def stop(self) -> None:
        LOGGER.debug("Stopping light show for %s", self.uid)
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            for action in self._actions:
                if self._stop_event.is_set():
                    break
                self._gateway.switch_pad(action.pad, action.colour)
                time.sleep(action.duration)


def run_rfid_demo(
    *,
    vendor_id: int | None = None,
    product_ids: Iterable[int] | None = None,
    poll_timeout: int = 50,
) -> None:
    """Run the RFID interactive demo until interrupted."""

    gateway_kwargs: dict[str, object] = {}
    if vendor_id is not None:
        gateway_kwargs["vendor_id"] = vendor_id
    if product_ids is not None:
        gateway_kwargs["product_ids"] = tuple(product_ids)

    with Gateway(**gateway_kwargs) as gateway:
        _initial_cycle(gateway)

        tracker = TagTracker(gateway, poll_timeout=poll_timeout, auto_start=False)
        active_show: _ActiveShow | None = None
        try:
            for event in tracker.iter_events():
                if event.type is TagEventType.ADDED:
                    LOGGER.info("Tag %s detected on %s", event.uid, event.pad)
                    if active_show is not None:
                        active_show.stop()
                    gateway.blank_pads()
                    actions = _derive_actions_from_uid(event.uid)
                    active_show = _ActiveShow(event.uid, gateway, actions)
                    active_show.start()
                elif event.type is TagEventType.REMOVED:
                    LOGGER.info("Tag %s removed", event.uid)
                    if active_show is not None and active_show.uid == event.uid:
                        active_show.stop()
                        active_show = None
                        gateway.blank_pads()
        except KeyboardInterrupt:
            LOGGER.info("Stopping RFID demo")
        finally:
            if active_show is not None:
                active_show.stop()
            tracker.stop()
            tracker.close()
            gateway.blank_pads()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vendor-id",
        type=lambda value: int(value, 0),
        default=None,
        help="Override the USB vendor id (e.g. 0x0E6F).",
    )
    parser.add_argument(
        "--product-id",
        dest="product_ids",
        type=lambda value: int(value, 0),
        action="append",
        default=None,
        help="Restrict detection to specific USB product identifiers.",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=50,
        help="Milliseconds to wait for RFID events before checking for shutdown.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (e.g. INFO, DEBUG).",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    run_rfid_demo(
        vendor_id=args.vendor_id,
        product_ids=args.product_ids,
        poll_timeout=args.poll_timeout,
    )
    return 0


__all__ = [
    "LightAction",
    "run_rfid_demo",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
