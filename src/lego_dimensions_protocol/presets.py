"""Reusable light-show presets for LEGO Dimensions portals."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Iterable, Optional, Sequence

from .gateway import Gateway, Pad, RGBColor


@dataclass(frozen=True)
class PresetStep:
    operation: str
    pad: Pad = Pad.ALL
    colour: tuple[int, int, int] = (0, 0, 0)
    duration: float = 0.0
    pulse_time: int = 8
    pulse_count: int = 1
    on_length: int = 8
    off_length: int = 8


@dataclass(frozen=True)
class LightPreset:
    name: str
    description: str
    steps: tuple[PresetStep, ...]
    loop: bool = False


class PresetNotFoundError(ValueError):
    """Raised when a named light preset does not exist."""


def _step(operation: str, colour: Sequence[int], *, pad: Pad = Pad.ALL, duration: float = 0.15, **kwargs: int) -> PresetStep:
    return PresetStep(operation=operation, pad=pad, colour=RGBColor.from_iterable(colour).as_tuple(), duration=duration, **kwargs)


_BUILTINS: dict[str, LightPreset] = {
    "blank": LightPreset("blank", "Turn all pad lights off.", (_step("set", (0, 0, 0), duration=0),)),
    "identify": LightPreset(
        "identify",
        "Flash all pads in a distinctive white/blue pattern.",
        (
            _step("flash", (32, 32, 32), on_length=5, off_length=5, pulse_count=3, duration=0.4),
            _step("flash", (0, 0, 96), on_length=8, off_length=4, pulse_count=2, duration=0.4),
        ),
    ),
    "rainbow": LightPreset(
        "rainbow",
        "Cycle through conservative rainbow colours.",
        tuple(_step("set", colour) for colour in ((96, 0, 0), (96, 48, 0), (96, 96, 0), (0, 96, 0), (0, 0, 96), (48, 0, 96))),
        loop=True,
    ),
    "pulse": LightPreset("pulse", "Pulse a soft purple light.", (_step("fade", (64, 0, 96), pulse_time=18, pulse_count=4, duration=1.2),), loop=True),
    "police": LightPreset(
        "police",
        "Alternate low-intensity red and blue flashes.",
        (_step("flash", (96, 0, 0), pad=Pad.LEFT, pulse_count=2, duration=0.35), _step("flash", (0, 0, 96), pad=Pad.RIGHT, pulse_count=2, duration=0.35)),
        loop=True,
    ),
}


def list_presets() -> list[LightPreset]:
    return [_BUILTINS[name] for name in sorted(_BUILTINS)]


def get_preset(name: str) -> LightPreset:
    key = name.casefold().strip()
    try:
        return _BUILTINS[key]
    except KeyError as exc:
        available = ", ".join(sorted(_BUILTINS))
        raise PresetNotFoundError(f"Unknown preset '{name}'. Available presets: {available}") from exc


def parse_colour(value: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError("Colours must be formatted as r,g,b")
    return RGBColor.from_iterable([int(part, 0) for part in parts]).as_tuple()


class PresetRunner:
    def __init__(self, gateway: Gateway, *, sleeper: Callable[[float], None] = time.sleep, cleanup: bool = True) -> None:
        self.gateway = gateway
        self.sleeper = sleeper
        self.cleanup = cleanup

    def run(self, preset: LightPreset, *, duration: float | None = None, colour: Sequence[int] | None = None) -> None:
        started = time.monotonic()
        try:
            while True:
                for step in preset.steps:
                    self._apply(step, colour=colour)
                    if step.duration:
                        self.sleeper(step.duration)
                    if duration is not None and time.monotonic() - started >= duration:
                        return
                if not preset.loop or duration is None:
                    return
        finally:
            if self.cleanup:
                self.gateway.blank_pads()

    def _apply(self, step: PresetStep, *, colour: Sequence[int] | None) -> None:
        actual_colour = RGBColor.from_iterable(colour).as_tuple() if colour is not None else step.colour
        if step.operation == "set":
            self.gateway.switch_pad(step.pad, actual_colour)
        elif step.operation == "fade":
            self.gateway.fade_pad(step.pad, pulse_time=step.pulse_time, pulse_count=step.pulse_count, colour=actual_colour)
        elif step.operation == "flash":
            self.gateway.flash_pad(step.pad, on_length=step.on_length, off_length=step.off_length, pulse_count=step.pulse_count, colour=actual_colour)
        else:  # pragma: no cover - guarded by built-in definitions
            raise ValueError(f"Unsupported preset operation: {step.operation}")


def run_preset(gateway: Gateway, name: str, *, duration: float | None = None, colour: Sequence[int] | None = None, portal_id: str = "default") -> None:
    if portal_id != "default":
        raise ValueError("Only portal_id='default' is supported until multi-portal support is implemented.")
    PresetRunner(gateway).run(get_preset(name), duration=duration, colour=colour)


def preview_preset(name: str, *, colour: Sequence[int] | None = None) -> list[dict[str, object]]:
    preset = get_preset(name)
    return [
        {
            "operation": step.operation,
            "pad": step.pad.name.lower(),
            "colour": tuple(colour) if colour is not None else step.colour,
            "duration": step.duration,
        }
        for step in preset.steps
    ]


__all__ = ["LightPreset", "PresetNotFoundError", "PresetRunner", "PresetStep", "get_preset", "list_presets", "parse_colour", "preview_preset", "run_preset"]
