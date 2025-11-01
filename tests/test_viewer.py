from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lego_dimensions_protocol.characters import CharacterInfo
from lego_dimensions_protocol.viewer import CharacterViewer


def test_character_viewer_render_formats_table():
    catalog = [
        CharacterInfo(id=1, name="Batman", world="DC"),
        CharacterInfo(id=2, name="Wyldstyle", world="LEGO Movie"),
    ]
    viewer = CharacterViewer(catalog)
    table = viewer.render(viewer.search())
    assert "ID | Name" in table
    assert "Batman" in table
    assert "Wyldstyle" in table


def test_character_viewer_search_filters_results():
    catalog = [
        CharacterInfo(id=1, name="Batman", world="DC"),
        CharacterInfo(id=2, name="Wyldstyle", world="LEGO Movie"),
    ]
    viewer = CharacterViewer(catalog)
    results = viewer.search(world="DC")
    assert len(results) == 1
    assert results[0].name == "Batman"
