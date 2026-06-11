import json
from io import StringIO

import pytest

from lego_dimensions_protocol.session import SessionRecord, SessionWriter, dry_run_actions, read_session, validate_single_portal


def test_session_writer_and_reader_round_trip() -> None:
    out = StringIO()
    with SessionWriter(out) as writer:
        writer.write("tag_event", uid="abc", pad="centre", event_type="added")
    records = list(read_session(StringIO(out.getvalue())))
    assert records[0].record_type == "session_started"
    assert records[1].payload["uid"] == "abc"
    assert records[-1].record_type == "session_finished"


def test_unknown_future_records_are_skipped() -> None:
    line = json.dumps(SessionRecord(record_type="future_event").to_dict())
    assert list(read_session(StringIO(line + "\n"))) == []


def test_multi_portal_replay_fails_clearly() -> None:
    records = [SessionRecord("tag_event", portal_id="a"), SessionRecord("tag_event", portal_id="b")]
    with pytest.raises(ValueError, match="multiple portal_id"):
        validate_single_portal(records)


def test_dry_run_actions_include_tag_events() -> None:
    actions = dry_run_actions([SessionRecord("tag_event", payload={"uid": "abc", "pad": "left", "event_type": "added"})])
    assert actions == ["tag added uid=abc pad=left"]
