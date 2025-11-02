"""Runtime helpers for looping LSTF programs on the Dimensions portal."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from .gateway import Gateway, Pad
from .lstf import LSTFError, LSTFProgram, PadCommand, load_lstf

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PadLoopFactory:
    pad: Pad
    commands: List[PadCommand]
    duration: float

    def create(self, gateway: Gateway) -> "_PadLoop":
        return _PadLoop(gateway=gateway, pad=self.pad, commands=self.commands, duration=self.duration)


class _PadLoop:
    """Background worker that replays commands on a single pad."""

    def __init__(
        self,
        *,
        gateway: Gateway,
        pad: Pad,
        commands: Iterable[PadCommand],
        duration: float,
    ) -> None:
        self._gateway = gateway
        self.pad = pad
        self._commands = list(commands)
        self._duration = max(duration, 0.01)
        self._stop_event = threading.Event()
        self._thread_name = f"LSTFPadLoop[{pad.name}]"
        self._thread = threading.Thread(target=self._run, name=self._thread_name, daemon=True)

    def start(self) -> None:
        self._stop_event.clear()
        if self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=self._thread_name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        if not self._commands:
            return
        base_start = time.monotonic()
        next_cycle_start = base_start
        while not self._stop_event.is_set():
            for command in self._commands:
                target = next_cycle_start + command.time
                if not self._wait_until(target):
                    return
                self._execute(command)
                if self._stop_event.is_set():
                    return
            next_cycle_start += self._duration

    def _wait_until(self, when: float) -> bool:
        while True:
            remaining = when - time.monotonic()
            if remaining <= 0:
                return not self._stop_event.is_set()
            if self._stop_event.wait(min(remaining, 0.1)):
                return False

    def _execute(self, command: PadCommand) -> None:
        if command.action == "switch":
            colour = command.colour or (0, 0, 0)
            self._gateway.switch_pad(self.pad, colour)
        elif command.action == "fade":
            colour = command.colour or (0, 0, 0)
            pulse_time = max(1, command.pulse_time or 1)
            pulse_count = max(1, command.pulse_count or 1)
            self._gateway.fade_pad(
                self.pad,
                pulse_time=pulse_time,
                pulse_count=pulse_count,
                colour=colour,
            )
        elif command.action == "flash":
            colour = command.colour or (0, 0, 0)
            on_length = max(1, command.on_length or 1)
            off_length = max(1, command.off_length or 1)
            pulse_count = max(1, command.pulse_count or 1)
            self._gateway.flash_pad(
                self.pad,
                on_length=on_length,
                off_length=off_length,
                pulse_count=pulse_count,
                colour=colour,
            )
        else:
            LOGGER.debug("Unknown command %s for pad %s", command.action, self.pad)


class TrackHandle:
    """Manage active pad loops for a single LSTF program."""

    def __init__(self, gateway: Gateway, factories: Mapping[Pad, _PadLoopFactory]) -> None:
        self._gateway = gateway
        self._factories = dict(factories)
        self._loops: Dict[Pad, _PadLoop] = {}

    def start(self) -> None:
        for pad in list(self._loops):
            self._loops[pad].stop()
        self._loops.clear()
        for pad, factory in self._factories.items():
            loop = factory.create(self._gateway)
            self._loops[pad] = loop
            loop.start()

    def stop(self) -> None:
        for loop in list(self._loops.values()):
            loop.stop()
        self._loops.clear()

    def stop_pad(self, pad: Pad) -> None:
        loop = self._loops.pop(pad, None)
        if loop is not None:
            loop.stop()

    def resume_pad(self, pad: Pad) -> None:
        if pad in self._loops:
            return
        factory = self._factories.get(pad)
        if factory is None:
            return
        loop = factory.create(self._gateway)
        self._loops[pad] = loop
        loop.start()

    def pads(self) -> Iterable[Pad]:
        return self._factories.keys()


class TrackCache:
    """Cache for decoded LSTF programs keyed by resolved file path."""

    def __init__(self) -> None:
        self._programs: Dict[Path, LSTFProgram] = {}

    def get(self, path: Path) -> LSTFProgram:
        resolved = path.resolve()
        try:
            return self._programs[resolved]
        except KeyError:
            program = load_lstf(resolved)
            self._programs[resolved] = program
            return program


class LSTFManager:
    """High-level orchestration of active LSTF tracks on the portal."""

    def __init__(self, gateway: Gateway) -> None:
        self._gateway = gateway
        self._track_stack: List[TrackHandle] = []
        self._pad_overlays: Dict[Pad, TrackHandle] = {}

    def close(self) -> None:
        for handle in self._pad_overlays.values():
            handle.stop()
        self._pad_overlays.clear()
        while self._track_stack:
            handle = self._track_stack.pop()
            handle.stop()

    def activate_default(self, program: LSTFProgram) -> None:
        self._track_stack.clear()
        handle = self._create_handle(program)
        handle.start()
        self._track_stack.append(handle)

    def push_track(self, program: LSTFProgram) -> TrackHandle:
        handle = self._create_handle(program)
        if self._track_stack:
            self._track_stack[-1].stop()
        handle.start()
        self._track_stack.append(handle)
        return handle

    def replace_track(self, program: LSTFProgram) -> TrackHandle:
        while self._track_stack:
            self._track_stack.pop().stop()
        handle = self._create_handle(program)
        handle.start()
        self._track_stack.append(handle)
        return handle

    def pop_track(self, handle: TrackHandle) -> None:
        if not self._track_stack or self._track_stack[-1] is not handle:
            return
        removed = self._track_stack.pop()
        removed.stop()
        if self._track_stack:
            self._track_stack[-1].start()

    def apply_overlay(self, pad: Pad, program: LSTFProgram) -> TrackHandle:
        self.remove_overlay(pad)
        if self._track_stack:
            self._track_stack[-1].stop_pad(pad)
        handle = self._create_handle(program, pad_override=pad)
        handle.start()
        self._pad_overlays[pad] = handle
        return handle

    def remove_overlay(self, pad: Pad) -> None:
        handle = self._pad_overlays.pop(pad, None)
        if handle is not None:
            handle.stop()
        if self._track_stack:
            self._track_stack[-1].resume_pad(pad)

    def clear_overlays(self) -> None:
        for pad, handle in list(self._pad_overlays.items()):
            handle.stop()
            self._pad_overlays.pop(pad, None)
            if self._track_stack:
                self._track_stack[-1].resume_pad(pad)

    def _create_handle(self, program: LSTFProgram, pad_override: Optional[Pad] = None) -> TrackHandle:
        factories: Dict[Pad, _PadLoopFactory] = {}
        if program.is_generic:
            if pad_override is None:
                raise LSTFError("Generic LSTF programs require a pad override.")
            pad, track = next(iter(program.pad_tracks.items()))
            factories[pad_override] = _PadLoopFactory(
                pad=pad_override,
                commands=list(track.commands),
                duration=track.duration,
            )
        else:
            for pad, track in program.iter_tracks():
                factories[pad] = _PadLoopFactory(
                    pad=pad,
                    commands=list(track.commands),
                    duration=track.duration,
                )
        return TrackHandle(self._gateway, factories)


__all__ = ["LSTFManager", "TrackCache"]

