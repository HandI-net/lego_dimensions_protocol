from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.crypto import generate_password_bytes
from lego_dimensions_protocol.editor import TagEditor, _ensure_uid
from lego_dimensions_protocol.gateway import Pad


class DummyGateway:
    def __init__(self) -> None:
        self.commands: list[list[int]] = []

    def send_command(self, command):  # pragma: no cover - interface shim
        self.commands.append(list(command))


_UID = "049a746a0b4080"


def test_tag_editor_plan_contains_expected_pages():
    editor = TagEditor(gateway=DummyGateway())
    plan = editor.build_character_plan(_UID, pad=Pad.LEFT, character_id=0x1234)
    assert plan.uid_hex == _UID
    assert plan.pad == Pad.LEFT
    assert plan.character_pages[0x24] != plan.character_pages[0x25]
    assert plan.password == generate_password_bytes(_ensure_uid(_UID))


def test_tag_editor_apply_plan_returns_commands_without_writing():
    gateway = DummyGateway()
    editor = TagEditor(gateway=gateway)
    plan = editor.build_character_plan(_UID, pad=Pad.RIGHT, character_id=0x4321)
    commands = editor.apply_plan(plan, dry_run=True)
    assert len(commands) == 4
    assert gateway.commands == []


def test_tag_editor_apply_plan_writes_commands():
    gateway = DummyGateway()
    editor = TagEditor(gateway=gateway)
    plan = editor.build_character_plan(_UID, pad=Pad.CENTRE, character_id=0x5555)
    editor.apply_plan(plan, dry_run=False)
    assert gateway.commands  # ensure commands were issued
