import logging
from pathlib import Path

import pytest

from lego_dimensions_protocol import lstf_app
from lego_dimensions_protocol.lstf_app import AppConfig, PortalConnectionError, _load_config


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


def test_application_raises_portal_error_when_usb_fails(monkeypatch) -> None:
    class _DummyUSBError(Exception):
        pass

    class _FailingTracker:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise _DummyUSBError("Input/Output Error")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(lstf_app, "TagTracker", _FailingTracker)
    monkeypatch.setattr(lstf_app, "USB_ERROR_TYPES", (_DummyUSBError,))

    app = lstf_app.LSTFApplication(AppConfig(default_track=Path("tracks/rainbow_cycle.lstf"), entries=[]))

    with pytest.raises(PortalConnectionError) as excinfo:
        app.run()

    assert "Input/Output Error" in str(excinfo.value)


def test_main_exits_cleanly_on_portal_error(monkeypatch, caplog) -> None:
    class _DummyApplication:
        def run(self) -> None:
            raise PortalConnectionError("Portal offline for testing")

    def _dummy_factory(config: AppConfig, poll_timeout: int = 250):
        return _DummyApplication()

    monkeypatch.setattr(lstf_app, "LSTFApplication", _dummy_factory)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as excinfo:
            lstf_app.main(["tracks/rainbow_cycle.lstf"])

    assert excinfo.value.code == 1
    assert "Portal offline for testing" in caplog.text
