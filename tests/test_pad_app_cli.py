import pytest

from lego_dimensions_protocol.gateway import Pad
from lego_dimensions_protocol.pad_app import (
    PadAction,
    PadOperation,
    apply_pad_action,
    parse_instruction,
)


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Pad, dict[str, object]]] = []

    def switch_pad(self, pad: Pad, colour) -> None:
        self.calls.append(("switch_pad", pad, {"colour": tuple(colour)}))

    def fade_pad(self, pad: Pad, *, pulse_time: int, pulse_count: int, colour) -> None:
        self.calls.append(
            (
                "fade_pad",
                pad,
                {"pulse_time": pulse_time, "pulse_count": pulse_count, "colour": tuple(colour)},
            )
        )

    def flash_pad(
        self,
        pad: Pad,
        *,
        on_length: int,
        off_length: int,
        pulse_count: int,
        colour,
    ) -> None:
        self.calls.append(
            (
                "flash_pad",
                pad,
                {
                    "on_length": on_length,
                    "off_length": off_length,
                    "pulse_count": pulse_count,
                    "colour": tuple(colour),
                },
            )
        )


def test_parse_set_command() -> None:
    instruction = parse_instruction("set(1, (1, 2, 3))")
    assert isinstance(instruction, PadAction)
    assert instruction.mask == 1
    assert instruction.operation is PadOperation.SET
    assert instruction.colour == (1, 2, 3)


def test_parse_wait_command() -> None:
    instruction = parse_instruction("wait(1500)")
    assert instruction.milliseconds == 1500


def test_parse_invalid_mask() -> None:
    with pytest.raises(ValueError):
        parse_instruction("set(0, (1, 2, 3))")


def test_parse_fade_command() -> None:
    instruction = parse_instruction("fade(2, (1, 2, 3), 4, 5)")
    assert isinstance(instruction, PadAction)
    assert instruction.mask == 2
    assert instruction.operation is PadOperation.FADE
    assert instruction.colour == (1, 2, 3)
    assert instruction.pulse_time == 4
    assert instruction.pulse_count == 5


def test_parse_flash_command() -> None:
    instruction = parse_instruction("flash(3, (255, 0, 0), 10, 10, 5)")
    assert isinstance(instruction, PadAction)
    assert instruction.mask == 3
    assert instruction.operation is PadOperation.FLASH
    assert instruction.colour == (255, 0, 0)
    assert instruction.on_length == 10
    assert instruction.off_length == 10
    assert instruction.pulse_count == 5


def test_old_prefixed_mask_format_rejected() -> None:
    with pytest.raises(ValueError):
        parse_instruction("1 set((1, 2, 3))")


def test_apply_action_two_pads_sends_two_calls() -> None:
    gateway = _FakeGateway()
    action = PadAction(
        mask=0b011,
        operation=PadOperation.FADE,
        colour=(10, 20, 30),
        pulse_time=40,
        pulse_count=2,
    )
    apply_pad_action(action, gateway)

    assert gateway.calls == [
        (
            "fade_pad",
            Pad.CENTRE,
            {"pulse_time": 40, "pulse_count": 2, "colour": (10, 20, 30)},
        ),
        (
            "fade_pad",
            Pad.LEFT,
            {"pulse_time": 40, "pulse_count": 2, "colour": (10, 20, 30)},
        ),
    ]


def test_apply_all_pads_uses_all_selector() -> None:
    gateway = _FakeGateway()
    action = PadAction(
        mask=0b111,
        operation=PadOperation.FLASH,
        colour=(1, 1, 1),
        on_length=5,
        off_length=6,
        pulse_count=7,
    )
    apply_pad_action(action, gateway)

    assert gateway.calls == [
        (
            "flash_pad",
            Pad.ALL,
            {"on_length": 5, "off_length": 6, "pulse_count": 7, "colour": (1, 1, 1)},
        )
    ]
