"""Regression coverage for repository-provided LSTF tracks.

The demonstration `.lstf` files ship alongside the project documentation and
are produced by :mod:`scripts.generate_demo_lstf_tracks`.  These tests ensure
that every committed track still parses exactly as the generator intended so we
catch accidental edits to the assets or parser regressions that would prevent
them from loading correctly.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from lego_dimensions_protocol.lstf import LSTFProgram, PadCommand, load_lstf
from lego_dimensions_protocol.lstf import _LSTFParser  # type: ignore[attr-defined]

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKS_DIR = REPO_ROOT / "tracks"
_TRACK_MODULE = runpy.run_path(
    REPO_ROOT / "scripts" / "generate_demo_lstf_tracks.py", run_name="track_specs"
)
TRACK_SPECS = _TRACK_MODULE["TRACKS"]


def _parse_binary_program(data: bytes) -> LSTFProgram:
    """Parse a binary LSTF payload using the production parser."""

    parser = _LSTFParser(data)  # pylint: disable=protected-access
    return parser.parse()


def _assert_commands_equal(actual: PadCommand, expected: PadCommand) -> None:
    assert actual.action == expected.action
    assert actual.colour == expected.colour
    assert actual.pulse_count == expected.pulse_count
    assert actual.pulse_time == expected.pulse_time
    assert actual.on_length == expected.on_length
    assert actual.off_length == expected.off_length
    assert actual.time == pytest.approx(expected.time, rel=1e-6, abs=1e-9)


@pytest.mark.parametrize("spec", TRACK_SPECS, ids=lambda spec: spec.name)
def test_repository_tracks_match_generated_reference(spec) -> None:
    """Ensure every committed LSTF track parses and matches its generator output."""

    track_path = TRACKS_DIR / f"{spec.name}.lstf"
    assert track_path.exists(), f"Missing track file: {track_path}"

    generated_program = _parse_binary_program(spec.builder())
    committed_program = load_lstf(track_path)

    assert committed_program.pad_tracks.keys() == generated_program.pad_tracks.keys()

    for pad, expected_track in generated_program.iter_tracks():
        actual_track = committed_program.pad_tracks[pad]
        assert actual_track.duration == pytest.approx(
            expected_track.duration, rel=1e-6, abs=1e-6
        )
        assert len(actual_track.commands) == len(expected_track.commands)
        for actual, expected in zip(actual_track.commands, expected_track.commands):
            _assert_commands_equal(actual, expected)

