"""Interactive RFID light show demonstration for the LEGO Dimensions portal."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event, Thread
from typing import Iterable, List, Sequence

from .gateway import Gateway, Pad, RGBColor
from .rfid import TagEventType, TagTracker

LOGGER = logging.getLogger(__name__)


class LightEffect(Enum):
    """Different lighting commands that can be executed during a show."""

    SWITCH = "switch"
    FADE = "fade"
    FLASH = "flash"
    GROUP_FADE = "group_fade"


@dataclass(frozen=True)
class LightAction:
    """Single lighting instruction used by the RFID light show."""

    pad: Pad
    colour: RGBColor
    duration: float
    effect: LightEffect = LightEffect.SWITCH
    pulse_time: int | None = None
    pulse_count: int | None = None
    on_length: int | None = None
    off_length: int | None = None

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("Durations must be positive when constructing a light action.")
        if self.effect is LightEffect.FADE or self.effect is LightEffect.GROUP_FADE:
            if self.pulse_time is None or self.pulse_count is None:
                raise ValueError("Fade actions require pulse_time and pulse_count values.")
        if self.effect is LightEffect.FLASH:
            if (
                self.on_length is None
                or self.off_length is None
                or self.pulse_count is None
            ):
                raise ValueError("Flash actions require on_length, off_length and pulse_count values.")


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
# ``fade_pads`` expects its entries ordered as centre, left, then right. Keep a separate
# mapping for that hardware-specific ordering so group fades stay confined to the pad that
# triggered them.
_PAD_TO_GROUP_INDEX: dict[Pad, int] = {
    Pad.CENTRE: 0,
    Pad.LEFT: 1,
    Pad.RIGHT: 2,
}


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


def _derive_actions_from_uid(uid: str, pad: Pad) -> List[LightAction]:
    """Create a deterministic light sequence derived from the RFID UID string."""

    if not uid:
        return [LightAction(pad=pad, colour=RGBColor(255, 255, 255), duration=0.45)]

    actions: List[LightAction] = []
    bytes_in_uid = [int(uid[i : i + 2], 16) for i in range(0, len(uid), 2)]
    if not bytes_in_uid:
        bytes_in_uid = [0]

    for index, value in enumerate(bytes_in_uid):
        palette_index = (value + index) % len(_PALETTE)
        colour = _PALETTE[palette_index]
        effect_selector = (value + index) % 4

        if effect_selector == 0:
            on_duration = 0.3 + (value % 4) * 0.05
            actions.append(LightAction(pad=pad, colour=colour, duration=on_duration))
        elif effect_selector == 1:
            pulse_time = 6 + (value % 15)
            pulse_count = 2 + (index % 4)
            actions.append(
                LightAction(
                    pad=pad,
                    colour=colour,
                    effect=LightEffect.FADE,
                    pulse_time=pulse_time,
                    pulse_count=pulse_count,
                    duration=0.45 + 0.05 * pulse_count,
                )
            )
        elif effect_selector == 2:
            on_length = 4 + (value % 8)
            off_length = 6 + ((value + index) % 10)
            pulse_count = 2 + (value % 3)
            actions.append(
                LightAction(
                    pad=pad,
                    colour=colour,
                    effect=LightEffect.FLASH,
                    on_length=on_length,
                    off_length=off_length,
                    pulse_count=pulse_count,
                    duration=0.4 + 0.03 * pulse_count,
                )
            )
        else:
            fade_time = 12 + (value % 20)
            pulse_count = 1 + (index % 5)
            actions.append(
                LightAction(
                    pad=pad,
                    colour=colour,
                    effect=LightEffect.GROUP_FADE,
                    pulse_time=fade_time,
                    pulse_count=pulse_count,
                    duration=0.5 + 0.05 * pulse_count,
                )
            )
            actions.append(LightAction(pad=pad, colour=RGBColor(0, 0, 0), duration=0.12))

    while actions and actions[-1].effect is LightEffect.SWITCH and actions[-1].colour == RGBColor(0, 0, 0):
        actions.pop()

    if not actions:
        actions.append(LightAction(pad=pad, colour=RGBColor(255, 255, 255), duration=0.45))

    return actions


class _ActiveShow:
    """Background worker that plays a repeating sequence of pad actions."""

    def __init__(
        self,
        uid: str,
        pad: Pad,
        gateway: Gateway,
        actions: Sequence[LightAction],
    ) -> None:
        self.uid = uid
        self.pad = pad
        self._gateway = gateway
        self._actions = list(actions) or [
            LightAction(pad=pad, colour=RGBColor(255, 255, 255), duration=0.5)
        ]
        self._stop_event = Event()
        self._thread = Thread(target=self._run, name=f"RFIDLightShow[{uid}]", daemon=True)

    def start(self) -> None:
        LOGGER.debug("Starting light show for %s on %s", self.uid, self.pad)
        self._stop_event.clear()
        self._thread.start()

    def stop(self) -> None:
        LOGGER.debug("Stopping light show for %s on %s", self.uid, self.pad)
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        for action in self._actions:
            if self._stop_event.is_set():
                break
            if action.effect is LightEffect.SWITCH:
                self._gateway.switch_pad(action.pad, action.colour)
            elif action.effect is LightEffect.FADE:
                self._gateway.fade_pad(
                    action.pad,
                    pulse_time=action.pulse_time or 1,
                    pulse_count=action.pulse_count or 1,
                    colour=action.colour,
                )
            elif action.effect is LightEffect.FLASH:
                self._gateway.flash_pad(
                    action.pad,
                    on_length=action.on_length or 1,
                    off_length=action.off_length or 1,
                    pulse_count=action.pulse_count or 1,
                    colour=action.colour,
                )
            elif action.effect is LightEffect.GROUP_FADE:
                pad_index = _PAD_TO_GROUP_INDEX.get(action.pad)
                if pad_index is None:
                    LOGGER.debug("Skipping group fade for unsupported pad %s", action.pad)
                    continue
                pad_entries: list[tuple[int, int, RGBColor] | None] = [None, None, None]
                pad_entries[pad_index] = (
                    action.pulse_time or 1,
                    action.pulse_count or 1,
                    action.colour,
                )
                self._gateway.fade_pads(pad_entries)
            else:  # pragma: no cover - defensive against future enum values
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
        active_shows: dict[Pad, _ActiveShow] = {}
        tag_locations: dict[str, Pad] = {}
        pad_tag_sets: dict[Pad, set[str]] = {}
        try:
            for event in tracker.iter_events():
                if event.type is TagEventType.ADDED:
                    if event.pad is None:
                        LOGGER.debug("Ignoring tag %s with unknown pad", event.uid)
                        continue
                    if event.character is not None:
                        LOGGER.info(
                            "Tag %s detected on %s: %s (ID %s, %s)",
                            event.uid,
                            event.pad,
                            event.character.name,
                            event.character.id,
                            event.character.world,
                        )
                    elif event.character_id is not None:
                        LOGGER.info(
                            "Tag %s detected on %s: character ID %s (no metadata)",
                            event.uid,
                            event.pad,
                            event.character_id,
                        )
                    else:
                        LOGGER.info(
                            "Tag %s detected on %s: no character data available",
                            event.uid,
                            event.pad,
                        )

                    previous_pad = tag_locations.get(event.uid)
                    if previous_pad is not None and previous_pad != event.pad:
                        previous_tags = pad_tag_sets.get(previous_pad)
                        if previous_tags is not None:
                            previous_tags.discard(event.uid)

                    tag_locations[event.uid] = event.pad
                    pad_tags = pad_tag_sets.setdefault(event.pad, set())
                    pad_tags.add(event.uid)

                    existing_show = active_shows.pop(event.pad, None)
                    if existing_show is not None:
                        existing_show.stop()

                    gateway.switch_pad(event.pad, RGBColor(0, 0, 0))
                    actions = _derive_actions_from_uid(event.uid, event.pad)
                    active_show = _ActiveShow(event.uid, event.pad, gateway, actions)
                    active_shows[event.pad] = active_show
                    active_show.start()
                elif event.type is TagEventType.REMOVED:
                    pad = tag_locations.pop(event.uid, None)
                    if pad is None:
                        for candidate_pad, tags in pad_tag_sets.items():
                            if event.uid in tags:
                                pad = candidate_pad
                                break
                    if pad is None:
                        LOGGER.info("Tag %s removed from unknown pad", event.uid)
                    else:
                        LOGGER.info("Tag %s removed from %s", event.uid, pad)
                    if pad is None:
                        LOGGER.debug("No pad tracked for removed tag %s", event.uid)
                        continue
                    remaining_on_pad = 0
                    pad_tags = pad_tag_sets.get(pad)
                    if pad_tags is not None:
                        pad_tags.discard(event.uid)
                        remaining_on_pad = len(pad_tags)
                        if remaining_on_pad == 0:
                            pad_tag_sets.pop(pad, None)

                    show = active_shows.get(pad)
                    if show is not None and show.uid == event.uid:
                        show.stop()
                        active_shows.pop(pad, None)

                    if remaining_on_pad == 0:
                        gateway.switch_pad(pad, RGBColor(0, 0, 0))
        except KeyboardInterrupt:
            LOGGER.info("Stopping RFID demo")
        finally:
            for show in active_shows.values():
                show.stop()
            tracker.stop()
            tracker.close()
            for pad in _PAD_SEQUENCE:
                gateway.switch_pad(pad, RGBColor(0, 0, 0))


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
    "LightEffect",
    "LightAction",
    "run_rfid_demo",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
