import json
from io import StringIO

from lego_dimensions_protocol.capture import CaptureWriter


def test_capture_writer_emits_ndjson_packet() -> None:
    out = StringIO()
    writer = CaptureWriter(out, portal_id="portal-a")
    writer.packet("write", [0x55, 0x00])
    line = out.getvalue().strip()
    payload = json.loads(line)
    assert payload["schema_version"] == "1"
    assert payload["record_type"] == "packet"
    assert payload["portal_id"] == "portal-a"
    assert payload["direction"] == "write"
    assert payload["payload_hex"] == "5500"


def test_capture_writer_redacts_uid() -> None:
    out = StringIO()
    writer = CaptureWriter(out, redact=True)
    writer.tag_event(uid="abcdef", pad="centre", event_type="added")
    payload = json.loads(out.getvalue())
    assert payload["uid"] == "<redacted>"

