from __future__ import annotations

import io
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import lego_dimensions_protocol.pad_app as pad_app


def test_resolve_prefers_inline_commands_list():
    with ExitStack() as stack:
        commands, interactive = pad_app._resolve_command_source(
            "fade((1,2,3),20,10)", ["wait(100)", "set(7,(0,0,0))"], stack=stack
        )

        assert list(commands) == ["fade((1,2,3),20,10)", "wait(100)", "set(7,(0,0,0))"]
        assert interactive is False


def test_resolve_reads_commands_from_file(tmp_path):
    command_file = tmp_path / "commands.txt"
    command_file.write_text("set(1,(1,2,3))\nwait(50)\n", encoding="utf-8")

    with ExitStack() as stack:
        commands, interactive = pad_app._resolve_command_source(str(command_file), [], stack=stack)

        assert [line.rstrip("\n") for line in commands] == ["set(1,(1,2,3))", "wait(50)"]
        assert interactive is False


def test_resolve_treats_unknown_path_as_inline_command(tmp_path):
    with ExitStack() as stack:
        commands, interactive = pad_app._resolve_command_source(
            "flash(3,(0,0,255),10,10,5)", [], stack=stack
        )

        assert list(commands) == ["flash(3,(0,0,255),10,10,5)"]
        assert interactive is False


def test_resolve_uses_stdin(monkeypatch):
    fake_stdin = io.StringIO("set(1,(9,9,9))\n")
    monkeypatch.setattr(pad_app, "sys", SimpleNamespace(stdin=fake_stdin))

    with ExitStack() as stack:
        commands, interactive = pad_app._resolve_command_source("-", [], stack=stack)

    assert [line.rstrip("\n") for line in commands] == ["set(1,(9,9,9))"]
    assert interactive is False
