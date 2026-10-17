"""Tests for the server-wide R7 token economy log (#607).

Cases are derived from the issue's Acceptance Criteria:
- token generation from daily rewards, drops, chatting and events is logged
- a command can display the aggregated source data

The log is one `token_stats` doc per UTC day, bumped alongside every earning
grant. Refunds and deductions are not generation, so they are never logged.
"""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import database.mongo as mongo
from features.economy import Economy


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fake_db(stat_docs=()):
    db = MagicMock()
    db.users.find_one = AsyncMock(return_value={"_id": "42", "brawlers": {"s": {}}})
    db.users.find_one_and_update = AsyncMock(return_value={"balance": 100})
    db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    db.token_stats.update_one = AsyncMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=list(stat_docs))
    db.token_stats.find = MagicMock(return_value=cursor)
    return db


# --- logging each generation path ---


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["chat", "drop", "booster_drop", "event", "poll"])
async def test_earning_grant_is_logged_to_todays_bucket(source):
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 25, source=source)

    db.token_stats.update_one.assert_awaited_once_with(
        {"_id": _today()}, {"$inc": {source: 25}}, upsert=True
    )


@pytest.mark.asyncio
async def test_daily_claim_is_logged():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.claim_daily_reward("42", 120, cutoff_ts=0.0, now_ts=1.0)

    db.token_stats.update_one.assert_awaited_once_with(
        {"_id": _today()}, {"$inc": {"daily": 120}}, upsert=True
    )


@pytest.mark.asyncio
async def test_lost_daily_claim_is_not_logged():
    # The cooldown predicate lost, so no tokens were generated.
    db = _fake_db()
    db.users.find_one_and_update = AsyncMock(return_value=None)
    with patch.object(mongo, "db", db):
        await mongo.claim_daily_reward("42", 120, cutoff_ts=0.0, now_ts=1.0)

    db.token_stats.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_quest_reward_is_logged():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.add_quest_reward("42", tokens=50, exp=20)

    db.token_stats.update_one.assert_awaited_once_with(
        {"_id": _today()}, {"$inc": {"quest": 50}}, upsert=True
    )


@pytest.mark.asyncio
async def test_grant_without_source_is_not_logged():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 25)

    db.token_stats.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_deduction_is_not_logged():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", -100, source="drop")

    db.token_stats.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_refund_is_not_logged():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.apply_queue_refund("42", "entry1", tokens=500)

    db.token_stats.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_stats_write_does_not_fail_the_payout():
    db = _fake_db()
    db.token_stats.update_one = AsyncMock(side_effect=RuntimeError("mongo down"))
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 25, source="chat")

    db.users.update_one.assert_awaited_once()


# --- get_token_stats ---


@pytest.mark.asyncio
async def test_stats_window_starts_days_minus_one_before_today():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.get_token_stats(30, today=date(2026, 10, 17))

    db.token_stats.find.assert_called_once_with({"_id": {"$gte": "2026-09-18"}})


@pytest.mark.asyncio
async def test_a_one_day_window_is_just_today():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.get_token_stats(1, today=date(2026, 10, 17))

    db.token_stats.find.assert_called_once_with({"_id": {"$gte": "2026-10-17"}})


@pytest.mark.asyncio
async def test_stats_sum_each_source_across_days():
    db = _fake_db(
        [
            {"_id": "2026-10-16", "daily": 100, "chat": 30},
            {"_id": "2026-10-17", "daily": 50, "drop": 20},
        ]
    )
    with patch.object(mongo, "db", db):
        totals = await mongo.get_token_stats(7, today=date(2026, 10, 17))

    assert totals == {"daily": 150, "chat": 30, "drop": 20}


@pytest.mark.asyncio
async def test_stats_without_a_database_are_empty():
    with patch.object(mongo, "db", None):
        assert await mongo.get_token_stats(30) == {}


# --- /economy-stats ---


@pytest.mark.asyncio
async def test_economy_stats_rejects_non_admins(mock_interaction, monkeypatch):
    cog = Economy.__new__(Economy)
    cog.has_permission = AsyncMock(return_value=False)
    stats = AsyncMock(return_value={})
    monkeypatch.setattr("features.economy.get_token_stats", stats)

    await Economy.economy_stats.callback(cog, mock_interaction, 30)

    stats.assert_not_awaited()


@pytest.mark.asyncio
async def test_economy_stats_reads_the_requested_window(mock_interaction, monkeypatch):
    cog = Economy.__new__(Economy)
    cog.has_permission = AsyncMock(return_value=True)
    stats = AsyncMock(return_value={"daily": 50, "drop": 30})
    monkeypatch.setattr("features.economy.get_token_stats", stats)

    await Economy.economy_stats.callback(cog, mock_interaction, 7)

    stats.assert_awaited_once_with(7)
