from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lego_dimensions_protocol import characters
import export_character_catalog


def test_character_catalog_contains_known_entry():
    info = characters.get_character(3)
    assert info is not None
    assert info.name.lower() == "wyldstyle"
    assert "lego" in info.world.lower()


def test_character_iteration_matches_lookup():
    catalog = {entry.id: entry for entry in characters.iter_characters()}
    for character_id in (1, 20, 56):
        entry = characters.get_character(character_id)
        if entry is None:
            continue
        assert catalog[character_id] == entry


def test_export_character_catalog_payload_contains_known_entry():
    payload = export_character_catalog.build_payload(characters.iter_characters())
    entries = {entry["id"]: entry for entry in payload["characters"]}
    info = characters.get_character(3)
    assert info is not None
    assert info.id in entries
    exported = entries[info.id]
    assert exported["name"] == info.name
    assert exported["world"] == info.world
