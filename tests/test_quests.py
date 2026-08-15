"""Tests for the quest system: booster threshold reduction and crash-safe
reward payout (rewarded flag, retry gate, and startup reconcile)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import database.mongo as mongo
from database.mongo import booster_quest_target, update_quest_progress
from features.config import SERVER_BOOSTER_ROLE_ID
from features.quests import Quests, _is_booster


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


# --- update_quest_progress retry gate ---


def _fake_db_with_quest(quest_entry):
    """Patches mongo.db so update_quest_progress reads back the given quest slot.
    Returns (db_mock, update_one) so callers can assert writes."""
    db = MagicMock()
    db.user_quests.find_one = AsyncMock(
        return_value={"_id": "u1", "daily_message": quest_entry}
    )
    db.user_quests.update_one = AsyncMock()
    return db, db.user_quests.update_one


async def test_progress_gate_retries_completed_but_unrewarded(monkeypatch):
    # Crash left the quest completed with the reward never paid -> re-signal payout.
    quest = {"progress": 80, "target_count": 80, "completed": True, "rewarded": False}
    db, update_one = _fake_db_with_quest(quest)
    monkeypatch.setattr(mongo, "db", db)

    completed, q_data = await update_quest_progress("u1", "daily_message")

    assert completed is True
    assert q_data is quest
    update_one.assert_not_awaited()  # no progress mutation on a completed quest


async def test_progress_gate_skips_completed_and_rewarded(monkeypatch):
    quest = {"progress": 80, "target_count": 80, "completed": True, "rewarded": True}
    db, _ = _fake_db_with_quest(quest)
    monkeypatch.setattr(mongo, "db", db)

    completed, q_data = await update_quest_progress("u1", "daily_message")

    assert completed is False
    assert q_data is None


async def test_progress_gate_skips_legacy_completed_without_rewarded_field(monkeypatch):
    # Pre-existing completed quest predating the rewarded field: absent == paid.
    quest = {"progress": 80, "target_count": 80, "completed": True}
    db, _ = _fake_db_with_quest(quest)
    monkeypatch.setattr(mongo, "db", db)

    completed, q_data = await update_quest_progress("u1", "daily_message")

    assert completed is False
    assert q_data is None


async def test_progress_completion_sets_completed_and_returns_quest(monkeypatch):
    # Reaching target flags completed (leaving rewarded:False) and returns the quest.
    quest = {"progress": 79, "target_count": 80, "completed": False, "rewarded": False}
    db, update_one = _fake_db_with_quest(quest)
    monkeypatch.setattr(mongo, "db", db)

    completed, q_data = await update_quest_progress("u1", "daily_message")

    assert completed is True
    assert q_data is quest
    args, _ = update_one.call_args
    assert args[1]["$set"]["daily_message.completed"] is True


# --- process_quest_update payout ordering ---


def _make_quests_cog():
    cog = Quests.__new__(Quests)  # skip __init__ so the reconcile loop doesn't start
    cog.bot = MagicMock()
    return cog


async def test_completion_pays_reward_before_flagging_rewarded(monkeypatch):
    cog = _make_quests_cog()
    q_data = {
        "name": "Daily Chatter",
        "description": "Send 80 messages today.",
        "reward_tokens": 50,
        "reward_exp": 100,
    }
    monkeypatch.setattr(
        "features.quests.get_active_quest", AsyncMock(return_value=q_data)
    )
    # Complete the first slot only, so the reward path runs exactly once.
    monkeypatch.setattr(
        "features.quests.update_quest_progress",
        AsyncMock(side_effect=[(True, q_data), (False, None)]),
    )
    order = MagicMock()
    order.pay = AsyncMock()
    order.flag = AsyncMock()
    monkeypatch.setattr("features.quests.add_quest_reward", order.pay)
    monkeypatch.setattr("features.quests.mark_quest_rewarded", order.flag)

    channel = MagicMock()
    channel.send = AsyncMock()
    await cog.process_quest_update("u1", channel, "message")

    order.pay.assert_awaited_once_with("u1", 50, 100)
    order.flag.assert_awaited_once_with("u1", "daily_message")
    # Reward must be paid BEFORE the rewarded flag is set (at-least-once ordering).
    assert order.mock_calls.index(
        ("pay", ("u1", 50, 100), {})
    ) < order.mock_calls.index(("flag", ("u1", "daily_message"), {}))


# --- reconcile_quest_rewards ---


async def test_reconcile_pays_and_flags_every_unrewarded_quest(monkeypatch):
    cog = _make_quests_cog()
    rows = [
        ("u1", "daily_message", {"reward_tokens": 50, "reward_exp": 100}),
        ("u2", "weekly_message", {"reward_tokens": 225, "reward_exp": 1000}),
    ]
    monkeypatch.setattr(
        "features.quests.get_unrewarded_completed_quests", AsyncMock(return_value=rows)
    )
    pay = AsyncMock()
    flag = AsyncMock()
    monkeypatch.setattr("features.quests.add_quest_reward", pay)
    monkeypatch.setattr("features.quests.mark_quest_rewarded", flag)

    await cog.reconcile_quest_rewards()

    assert pay.await_count == 2
    pay.assert_any_await("u1", 50, 100)
    pay.assert_any_await("u2", 225, 1000)
    flag.assert_any_await("u1", "daily_message")
    flag.assert_any_await("u2", "weekly_message")


async def test_reconcile_noop_when_nothing_pending(monkeypatch):
    cog = _make_quests_cog()
    monkeypatch.setattr(
        "features.quests.get_unrewarded_completed_quests", AsyncMock(return_value=[])
    )
    pay = AsyncMock()
    flag = AsyncMock()
    monkeypatch.setattr("features.quests.add_quest_reward", pay)
    monkeypatch.setattr("features.quests.mark_quest_rewarded", flag)

    await cog.reconcile_quest_rewards()

    pay.assert_not_awaited()
    flag.assert_not_awaited()
