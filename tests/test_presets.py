import pytest

from lego_dimensions_protocol.gateway import Pad
from lego_dimensions_protocol.presets import PresetRunner, get_preset, list_presets, parse_colour, preview_preset


class FakeGateway:
    def __init__(self) -> None:
        self.calls = []

    def switch_pad(self, pad, colour) -> None:
        self.calls.append(("switch", pad, tuple(colour)))

    def fade_pad(self, pad, *, pulse_time, pulse_count, colour) -> None:
        self.calls.append(("fade", pad, pulse_time, pulse_count, tuple(colour)))

    def flash_pad(self, pad, *, on_length, off_length, pulse_count, colour) -> None:
        self.calls.append(("flash", pad, on_length, off_length, pulse_count, tuple(colour)))

    def blank_pads(self) -> None:
        self.calls.append(("blank",))


def test_list_presets_contains_expected_names() -> None:
    names = {preset.name for preset in list_presets()}
    assert {"blank", "identify", "rainbow", "pulse", "police"} <= names


def test_runner_blanks_after_exception() -> None:
    class FailingGateway(FakeGateway):
        def switch_pad(self, pad, colour) -> None:
            raise RuntimeError("boom")

    gateway = FailingGateway()
    with pytest.raises(RuntimeError):
        PresetRunner(gateway).run(get_preset("blank"))
    assert gateway.calls == [("blank",)]


def test_runner_calls_gateway_methods() -> None:
    gateway = FakeGateway()
    PresetRunner(gateway, sleeper=lambda _: None).run(get_preset("identify"))
    assert gateway.calls[0][0] == "flash"
    assert gateway.calls[-1] == ("blank",)


def test_parse_colour() -> None:
    assert parse_colour("128,0,255") == (128, 0, 255)


def test_preview_uses_colour_override() -> None:
    preview = preview_preset("pulse", colour=(1, 2, 3))
    assert preview[0]["colour"] == (1, 2, 3)
