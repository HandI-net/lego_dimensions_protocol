import pytest

from lego_dimensions_protocol.character_cli import CharacterResolutionError, resolve_character, search_characters


def test_resolve_character_by_id() -> None:
    assert resolve_character("3").name.lower() == "wyldstyle"


def test_resolve_character_by_case_insensitive_name() -> None:
    assert resolve_character("wYlDsTyLe").id == 3


def test_resolve_unambiguous_partial_name() -> None:
    assert resolve_character("gandalf").name.lower().startswith("gandalf")


def test_ambiguous_partial_name_fails_with_candidates() -> None:
    with pytest.raises(CharacterResolutionError) as exc_info:
        resolve_character("bat")
    assert exc_info.value.candidates


def test_search_characters_matches_world_or_name() -> None:
    matches = search_characters("portal")
    assert matches

