from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.characters import CharacterInfo
from lego_dimensions_protocol.editor import TagWritePlan
from lego_dimensions_protocol.gateway import Pad
from lego_dimensions_protocol.rfid import TagEvent, TagEventType
from lego_dimensions_protocol.studio import TagStudio


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def switch_pad(self, pad, colour):  # pragma: no cover - exercised indirectly
        self.calls.append(("switch", Pad(pad), tuple(colour)))

    def flash_pad(self, pad, *, on_length, off_length, pulse_count, colour):
        self.calls.append(
            (
                "flash",
                Pad(pad),
                on_length,
                off_length,
                pulse_count,
                tuple(colour),
            )
        )

    def fade_pad(self, pad, *, pulse_time, pulse_count, colour):
        self.calls.append(("fade", Pad(pad), pulse_time, pulse_count, tuple(colour)))


class FakeTracker:
    def __init__(self, gateway: FakeGateway, events: list[TagEvent]) -> None:
        self.gateway = gateway
        self._events = events
        self.poll_timeout = 0
        self.closed = False

    def poll_once(self):
        if self._events:
            return self._events.pop(0)
        return None

    def close(self):
        self.closed = True


class FakeEditor:
    def __init__(self) -> None:
        self.plan_calls: list[tuple[str, Pad, int]] = []
        self.applied: list[tuple[TagWritePlan, bool]] = []
        self._plan: TagWritePlan | None = None

    def build_character_plan(self, uid, *, pad, character_id):
        self.plan_calls.append((uid, pad, character_id))
        uid_bytes = tuple(int(uid[index : index + 2], 16) for index in range(0, len(uid), 2))
        self._plan = TagWritePlan(
            uid=uid_bytes,
            pad=pad,
            pad_index=1,
            character_id=character_id,
            password=(1, 2, 3, 4),
            character_pages={0x24: (1, 1, 1, 1), 0x25: (2, 2, 2, 2)},
        )
        return self._plan

    def apply_plan(self, plan, *, dry_run):
        self.applied.append((plan, dry_run))
        return [[0x55]]

    def describe_plan(self, plan):  # pragma: no cover - formatting only
        return "plan"

    def close(self):  # pragma: no cover - interface parity
        pass


def _tag_event(uid: str, pad: Pad, *, character: CharacterInfo | None = None) -> TagEvent:
    return TagEvent(
        uid=uid,
        pad=pad,
        type=TagEventType.ADDED,
        character_id=None if character is None else character.id,
        character=character,
    )


def test_clone_uses_source_character_for_plan():
    gateway = FakeGateway()
    editor = FakeEditor()
    source_info = CharacterInfo(id=0x1234, name="Batman", world="DC")
    events = [
        _tag_event("01020304050607", Pad.LEFT, character=source_info),
        _tag_event("0a0b0c0d0e0f10", Pad.RIGHT),
    ]
    tracker = FakeTracker(gateway, events)

    studio = TagStudio(tracker=tracker, editor=editor)
    studio.clone(source_pad=Pad.LEFT, target_pad=Pad.RIGHT, apply=True)
    studio.close()

    assert editor.plan_calls == [("0a0b0c0d0e0f10", Pad.RIGHT, 0x1234)]
    assert editor.applied[0][1] is False
    actions = [action[0] for action in gateway.calls]
    assert "fade" in actions  # progress lights during the write
    assert tracker.closed is False  # external tracker is not closed by TagStudio


def test_write_character_supports_dry_run():
    gateway = FakeGateway()
    editor = FakeEditor()
    events = [_tag_event("11121314151617", Pad.CENTRE)]
    tracker = FakeTracker(gateway, events)

    studio = TagStudio(tracker=tracker, editor=editor)
    studio.write_character(0x2222, pad=Pad.CENTRE, apply=False)
    studio.close()

    assert editor.plan_calls == [("11121314151617", Pad.CENTRE, 0x2222)]
    assert editor.applied[0][1] is True
    assert any(action[0] == "flash" for action in gateway.calls)
