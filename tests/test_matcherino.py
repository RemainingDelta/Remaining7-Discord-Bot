"""Tests for pure functions in features/tourney/matcherino.py."""

import features.tourney.matcherino as matcherino
from features.tourney.matcherino import (
    _normalize_for_compare,
    _team_name_matches,
    clear_bracket_teams_cache,
)


# --- _normalize_for_compare ---


def test_normalize_empty_string():
    assert _normalize_for_compare("") == ""


def test_normalize_none():
    assert _normalize_for_compare(None) == ""


def test_normalize_non_string():
    assert _normalize_for_compare(123) == ""


def test_normalize_strips_and_lowercases():
    assert _normalize_for_compare("  Fire Boys  ") == "fire boys"


def test_normalize_collapses_inner_whitespace():
    assert _normalize_for_compare("Fire  Boys") == "fire boys"


def test_normalize_already_clean():
    assert _normalize_for_compare("alpha") == "alpha"


# --- _team_name_matches ---


def test_exact_match_returns_true():
    matches, ratio, name = _team_name_matches("Fire Boys", "Fire Boys", "Team Blue")
    assert matches is True
    assert ratio == 1.0
    assert name == "Fire Boys"


def test_minor_typo_passes_threshold():
    # "FireBoys" vs "Fire Boys" — one word vs two
    matches, ratio, _ = _team_name_matches("FireBoys", "Fire Boys", "Team Blue")
    assert matches is True


def test_clearly_different_teams_no_match():
    matches, ratio, _ = _team_name_matches("Xyz Random", "Alpha Squad", "Beta Force")
    assert matches is False


def test_empty_topic_always_matches():
    # No topic team name to check → skip mismatch
    matches, ratio, name = _team_name_matches("", "Alpha", "Beta")
    assert matches is True
    assert name is None


def test_both_tbd_skips_check():
    matches, ratio, name = _team_name_matches("Any Team", "tbd", "bye")
    assert matches is True
    assert name is None


def test_picks_best_matching_team():
    # topic team is closer to team_b
    matches, ratio, name = _team_name_matches("Team Blue", "Alpha Squad", "Team Blue")
    assert matches is True
    assert name == "Team Blue"


def test_tbd_slot_not_chosen_as_match():
    # team_a is tbd, so team_b should be evaluated
    matches, ratio, name = _team_name_matches("Fire Boys", "tbd", "Fire Boys")
    assert matches is True
    assert name == "Fire Boys"


# --- clear_bracket_teams_cache ---


def test_clear_bracket_teams_cache_empties_dict():
    matcherino._bracket_teams_cache["12345"] = [{"name": "Team A", "entrant_id": 1}]
    clear_bracket_teams_cache()
    assert len(matcherino._bracket_teams_cache) == 0


def test_clear_bracket_teams_cache_idempotent():
    clear_bracket_teams_cache()
    clear_bracket_teams_cache()  # calling twice should not raise
    assert len(matcherino._bracket_teams_cache) == 0
