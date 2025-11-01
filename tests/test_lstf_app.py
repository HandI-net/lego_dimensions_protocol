from pathlib import Path

from lego_dimensions_protocol.lstf_app import AppConfig, _load_config


def test_load_config_from_json(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
            "default_track": "../tracks/rainbow_cycle.lstf",
            "tags": []
        }
        """
    )

    config = _load_config(config_path)

    assert isinstance(config, AppConfig)
    assert config.default_track == (config_path.parent / "../tracks/rainbow_cycle.lstf").resolve()
    assert config.entries == []


def test_load_config_from_lstf_track() -> None:
    track_path = Path("tracks/rainbow_cycle.lstf")

    config = _load_config(track_path)

    assert isinstance(config, AppConfig)
    assert config.default_track == track_path.resolve()
    assert config.entries == []
