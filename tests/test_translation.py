"""Tests for pure functions in features/translation.py."""

from unittest.mock import MagicMock

from features.translation import Translation


def make_cog():
    return Translation(MagicMock())


# --- get_language_code ---


def test_get_language_code_by_full_name():
    assert make_cog().get_language_code("Spanish") == "es"


def test_get_language_code_by_code_directly():
    assert make_cog().get_language_code("es") == "es"


def test_get_language_code_case_insensitive_name():
    assert make_cog().get_language_code("ENGLISH") == "en"
    assert make_cog().get_language_code("english") == "en"


def test_get_language_code_case_insensitive_code():
    assert make_cog().get_language_code("ES") == "es"


def test_get_language_code_french():
    assert make_cog().get_language_code("French") == "fr"
    assert make_cog().get_language_code("fr") == "fr"


def test_get_language_code_portuguese():
    assert make_cog().get_language_code("Portuguese") == "pt"


def test_get_language_code_unknown_returns_none():
    assert make_cog().get_language_code("klingon") is None


def test_get_language_code_empty_string_returns_none():
    assert make_cog().get_language_code("") is None


def test_get_language_code_whitespace_only_returns_none():
    # Strips and lowercases, doesn't match anything
    assert make_cog().get_language_code("   ") is None


# --- language_autocomplete ---


async def test_language_autocomplete_filters_by_name(mock_interaction):
    cog = make_cog()
    results = await cog.language_autocomplete(mock_interaction, "span")
    names = [r.name for r in results]
    assert "Spanish" in names


async def test_language_autocomplete_empty_returns_up_to_25(mock_interaction):
    cog = make_cog()
    results = await cog.language_autocomplete(mock_interaction, "")
    assert len(results) <= 25


async def test_language_autocomplete_no_match_returns_empty(mock_interaction):
    cog = make_cog()
    results = await cog.language_autocomplete(mock_interaction, "zzzzzznonexistent")
    assert results == []
