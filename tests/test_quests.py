"""Tests for pure functions in the quest system (booster threshold reduction)."""

from unittest.mock import MagicMock

import pytest

from database.mongo import booster_quest_target
from features.config import SERVER_BOOSTER_ROLE_ID
from features.quests import _is_booster


# --- booster_quest_target ---


@pytest.mark.parametrize(
    "base,expected",
    [
        (80, 64),
        (160, 128),
        (240, 192),
        (100, 80),
        (500, 400),
        (750, 600),
        (1000, 800),
    ],
)
def test_booster_quest_target_matches_spec(base, expected):
    assert booster_quest_target(base) == expected


def test_booster_quest_target_never_below_one():
    assert booster_quest_target(1) == 1
    assert booster_quest_target(0) == 1


# --- _is_booster ---


def _member_with_roles(role_ids):
    member = MagicMock()
    member.get_role = lambda rid: MagicMock() if rid in role_ids else None
    return member


def test_is_booster_true_with_role():
    assert _is_booster(_member_with_roles({SERVER_BOOSTER_ROLE_ID})) is True


def test_is_booster_false_without_role():
    assert _is_booster(_member_with_roles(set())) is False


def test_is_booster_false_for_none_member():
    assert _is_booster(None) is False


def test_is_booster_false_for_user_without_get_role():
    user = object()  # discord.User in DMs has no get_role
    assert _is_booster(user) is False
