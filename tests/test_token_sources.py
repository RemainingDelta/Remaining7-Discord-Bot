"""Tests for per-user token source tracking (#606).

Cases are derived from the issue's Acceptance Criteria:
- the source of every token a user earns is recorded
- any user's total can be broken down by source as percentages
- chatting, daily and drops (plus the other earning paths) are tracked

Redemption refunds return tokens that were already counted under their real
source when first earned, so they must never add to a source counter.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import database.mongo as mongo
from features.config import BOOSTER_CHANNEL_ID, GENERAL_CHANNEL_ID
from features.economy import DropClaimButton, Economy, token_source_breakdown
from features.event import PayoutConfirmView, PollPayoutConfirmView


def _fake_db(existing=None):
    db = MagicMock()
    db.users.find_one = AsyncMock(return_value=existing)
    db.users.find_one_and_update = AsyncMock(return_value={"balance": 100})
    db.users.insert_one = AsyncMock()
    db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    return db


def _inc(db, method="update_one"):
    """The $inc document of the single write made to the users collection."""
    return getattr(db.users, method).await_args.args[1]["$inc"]


# --- increment_user_balance ---


@pytest.mark.asyncio
@pytest.mark.parametrize("source", mongo.TOKEN_SOURCES)
async def test_increment_with_source_records_it_alongside_balance(source):
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 30, source=source)

    assert _inc(db) == {"balance": 30, f"token_sources.{source}": 30}


@pytest.mark.asyncio
async def test_increment_without_source_moves_balance_only():
    # The refund path calls this with no source.
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 30)

    assert _inc(db) == {"balance": 30}


@pytest.mark.asyncio
async def test_negative_grant_does_not_reduce_earned_counter():
    # A negative drop deducts tokens but is not "earning" anything.
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", -100, source="drop")

    assert _inc(db) == {"balance": -100}


@pytest.mark.asyncio
async def test_zero_grant_does_not_create_a_counter():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 0, source="drop")

    assert _inc(db) == {"balance": 0}


@pytest.mark.asyncio
async def test_unknown_source_is_rejected_without_writing():
    db = _fake_db()
    with patch.object(mongo, "db", db), pytest.raises(ValueError, match="chatting"):
        await mongo.increment_user_balance("42", 5, source="chatting")

    db.users.update_one.assert_not_awaited()


# --- daily, quest and refund helpers ---


@pytest.mark.asyncio
async def test_daily_claim_records_daily_source_in_the_same_write():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.claim_daily_reward("42", 120, cutoff_ts=0.0, now_ts=1.0)

    assert _inc(db, "find_one_and_update") == {
        "balance": 120,
        "token_sources.daily": 120,
    }


@pytest.mark.asyncio
async def test_quest_reward_records_quest_source():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.add_quest_reward("42", tokens=50, exp=20)

    assert _inc(db) == {"balance": 50, "token_sources.quest": 50, "exp": 20}


@pytest.mark.asyncio
async def test_xp_only_quest_reward_records_no_source():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.add_quest_reward("42", tokens=0, exp=20)

    assert _inc(db) == {"exp": 20}


@pytest.mark.asyncio
async def test_queue_refund_does_not_count_as_earned():
    db = _fake_db(existing={"_id": "42", "brawlers": {"shelly": {}}})
    with patch.object(mongo, "db", db):
        await mongo.apply_queue_refund("42", "entry1", tokens=500)

    inc = _inc(db)
    assert inc == {"balance": 500}
    assert not any(k.startswith("token_sources") for k in inc)


# --- get_token_sources ---


@pytest.mark.asyncio
async def test_get_token_sources_returns_the_users_counters():
    db = _fake_db(existing={"_id": "42", "token_sources": {"chat": 10, "daily": 90}})
    with patch.object(mongo, "db", db):
        assert await mongo.get_token_sources("42") == {"chat": 10, "daily": 90}


@pytest.mark.asyncio
async def test_get_token_sources_is_empty_for_an_untracked_user():
    db = _fake_db(existing={"_id": "42", "balance": 300})
    with patch.object(mongo, "db", db):
        assert await mongo.get_token_sources("42") == {}


@pytest.mark.asyncio
async def test_get_token_sources_does_not_create_a_user_doc():
    # Looking someone up must not self-heal a brawl profile into existence.
    db = _fake_db(existing=None)
    with patch.object(mongo, "db", db):
        assert await mongo.get_token_sources("42") == {}

    db.users.insert_one.assert_not_awaited()


# --- token_source_breakdown ---


def test_breakdown_gives_percentage_of_total_largest_first():
    rows = token_source_breakdown({"chat": 150, "daily": 300, "drop": 50})

    assert rows == [("daily", 300, 60.0), ("chat", 150, 30.0), ("drop", 50, 10.0)]


def test_breakdown_percentages_sum_to_100():
    rows = token_source_breakdown({"chat": 1, "daily": 1, "drop": 1})

    assert sum(pct for _, _, pct in rows) == pytest.approx(100.0)


def test_breakdown_of_no_earnings_is_empty():
    assert token_source_breakdown({}) == []


def test_breakdown_skips_zero_sources():
    assert token_source_breakdown({"chat": 0, "daily": 40}) == [("daily", 40, 100.0)]


def test_breakdown_ignores_keys_that_are_not_sources():
    assert token_source_breakdown({"daily": 40, "bogus": 60}) == [("daily", 40, 100.0)]


# --- call sites tag the right source ---


def _drop_interaction(mock_interaction, channel_id):
    mock_interaction.user.roles = []
    mock_interaction.user.mention = "<@987654321>"
    mock_interaction.message = MagicMock()
    mock_interaction.message.id = 555
    mock_interaction.message.channel.id = channel_id
    mock_interaction.message.embeds = [discord.Embed()]
    mock_interaction.edit_original_response = AsyncMock()
    return mock_interaction


async def _claim(channel_id, mock_interaction):
    interaction = _drop_interaction(mock_interaction, channel_id)
    with (
        patch("features.economy.claim_drop", AsyncMock(return_value=True)),
        patch("features.economy.get_setting", AsyncMock(return_value="")),
        patch("features.economy.increment_user_balance", AsyncMock()) as inc,
    ):
        await DropClaimButton(20).callback(interaction)
    return inc


@pytest.mark.asyncio
async def test_drop_claimed_outside_booster_channel_is_a_drop(mock_interaction):
    inc = await _claim(GENERAL_CHANNEL_ID, mock_interaction)
    inc.assert_awaited_once_with("987654321", 20, source="drop")


@pytest.mark.asyncio
async def test_drop_claimed_in_booster_channel_is_a_booster_drop(mock_interaction):
    inc = await _claim(BOOSTER_CHANNEL_ID, mock_interaction)
    inc.assert_awaited_once_with("987654321", 20, source="booster_drop")


@pytest.mark.asyncio
async def test_chat_reward_is_tagged_chat(guild_message, monkeypatch):
    cog = Economy.__new__(Economy)
    cog.bot = MagicMock()
    increment = AsyncMock()
    monkeypatch.setattr("features.economy.get_user_data", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "features.economy.get_setting",
        AsyncMock(side_effect=lambda key, default=None: default),
    )
    monkeypatch.setattr("features.economy.set_setting", AsyncMock())
    monkeypatch.setattr("features.economy.increment_user_balance", increment)
    monkeypatch.setattr(
        "features.economy.get_leveling_data", AsyncMock(return_value=(1, 0))
    )
    monkeypatch.setattr("features.economy.update_leveling_data", AsyncMock())

    await cog.on_message(guild_message(GENERAL_CHANNEL_ID))

    assert increment.await_args.kwargs == {"source": "chat"}


@pytest.mark.asyncio
async def test_admin_give_tokens_is_tagged_admin(mock_interaction, monkeypatch):
    cog = Economy.__new__(Economy)
    cog.bot = MagicMock()
    cog.has_permission = AsyncMock(return_value=True)
    increment = AsyncMock()
    monkeypatch.setattr("features.economy.increment_user_balance", increment)
    target = MagicMock(id=42, mention="<@42>")

    await Economy.give.callback(cog, mock_interaction, target, "tokens", 75)

    increment.assert_awaited_once_with("42", 75, source="admin")


def _confirm_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.user = MagicMock(id="admin")
    interaction.message = MagicMock()
    interaction.message.embeds = [discord.Embed(title="Confirm?")]
    interaction.edit_original_response = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_event_payout_is_tagged_event(monkeypatch):
    increment = AsyncMock()
    monkeypatch.setattr(
        "features.event.claim_reward_payout", AsyncMock(return_value=True)
    )
    monkeypatch.setattr("features.event.increment_user_balance", increment)
    monkeypatch.setattr("features.event.mark_reward_paid", AsyncMock())
    original = MagicMock(id=999, add_reaction=AsyncMock())
    view = PayoutConfirmView(original, [("42", "100")], MagicMock(id="admin"))

    await view.confirm.callback(_confirm_interaction())

    increment.assert_awaited_once_with("42", 100, source="event")


@pytest.mark.asyncio
async def test_poll_payout_is_tagged_poll(monkeypatch):
    increment = AsyncMock()
    monkeypatch.setattr(
        "features.event.is_poll_reward_processed", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        "features.event.claim_reward_payout", AsyncMock(return_value=True)
    )
    monkeypatch.setattr("features.event.increment_user_balance", increment)
    monkeypatch.setattr("features.event.mark_reward_paid", AsyncMock())
    monkeypatch.setattr("features.event.mark_poll_reward_processed", AsyncMock())
    original = MagicMock(id=999, add_reaction=AsyncMock())
    view = PollPayoutConfirmView(
        original, [MagicMock(id="u1")], 5, "Option A", MagicMock(id="admin")
    )

    await view.confirm.callback(_confirm_interaction())

    increment.assert_awaited_once_with("u1", 5, source="poll")


# --- /token-sources ---


@pytest.mark.asyncio
async def test_token_sources_command_defaults_to_the_caller(
    mock_interaction, monkeypatch
):
    cog = Economy.__new__(Economy)
    lookup = AsyncMock(return_value={"chat": 10})
    monkeypatch.setattr("features.economy.get_token_sources", lookup)
    mock_interaction.user.display_avatar = MagicMock(url="")

    await Economy.token_sources.callback(cog, mock_interaction, None)

    lookup.assert_awaited_once_with("987654321")


@pytest.mark.asyncio
async def test_token_sources_command_looks_up_the_named_user(
    mock_interaction, monkeypatch
):
    cog = Economy.__new__(Economy)
    lookup = AsyncMock(return_value={})
    monkeypatch.setattr("features.economy.get_token_sources", lookup)
    mock_interaction.user.display_avatar = MagicMock(url="")
    target = MagicMock(id=42, display_name="Someone")

    await Economy.token_sources.callback(cog, mock_interaction, target)

    lookup.assert_awaited_once_with("42")
