from __future__ import annotations

from pathlib import Path

import pytest

from lego_dimensions_protocol.lstf import TEXTUAL_LSTF_HEADER, load_lstf


TRACK_DIR = Path(__file__).resolve().parents[1] / "tracks"
EXPECTED_ACTIONS = {
    "aurora_glide": {"fade"},
    "rainbow_cycle": {"fade"},
    "sync_pulse": {"flash"},
    "triple_chase": {"switch"},
    "tempo_ramp": {"flash", "fade"},
    "countdown_burst": {"flash"},
    "strobe_warning": {"flash", "fade"},
    "twinkle_field": {"switch"},
    "wave_cascade": {"fade"},
    "centre_stage": {"fade", "flash"},
    "ocean_swell": {"fade"},
    "fireworks_finale": {"flash", "fade", "switch"},
}


@pytest.mark.parametrize("track_path", sorted(TRACK_DIR.glob("*.lstf"), key=lambda path: path.name))
def test_demo_track_properties(track_path: Path) -> None:
    raw = track_path.read_bytes()
    assert raw.startswith(TEXTUAL_LSTF_HEADER.encode("ascii"))

    program = load_lstf(track_path)
    assert len(program.pad_tracks) == 3, f"{track_path.name} should include three pad tracks"

    durations = [track.duration for track in program.pad_tracks.values()]
    max_duration = max(durations)
    assert 5.0 <= max_duration <= 15.0

    actions = {command.action for track in program.pad_tracks.values() for command in track.commands}
    expected = EXPECTED_ACTIONS[track_path.stem]
    assert actions & expected, f"{track_path.name} missing expected actions {expected}"

    for track in program.pad_tracks.values():
        assert len(track.commands) >= 2, f"{track_path.name} track should contain multiple commands"


def test_demo_track_count() -> None:
    tracks = sorted(TRACK_DIR.glob("*.lstf"))
    assert len(tracks) == len(EXPECTED_ACTIONS)
