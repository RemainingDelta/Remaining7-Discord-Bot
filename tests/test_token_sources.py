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
from features.config import (
    ADMIN_ROLE_ID,
    BOOSTER_CHANNEL_ID,
    GENERAL_CHANNEL_ID,
    MODERATOR_ROLE_ID,
    SERVER_BOOSTER_ROLE_ID,
    TRIAL_MODERATOR_ROLE_ID,
)
from features.economy import (
    DropClaimButton,
    Economy,
    create_redemption_ticket,
    token_source_breakdown,
)
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


# --- /token-sources (Mod/Admin only, private reply) ---


def _as_staff(interaction, *role_ids):
    interaction.user.roles = [MagicMock(id=rid) for rid in role_ids]
    interaction.user.display_avatar = MagicMock(url="")
    return interaction


async def _run_command(interaction, monkeypatch, target=None, counts=None):
    lookup = AsyncMock(return_value=counts or {})
    monkeypatch.setattr("features.economy.get_token_sources", lookup)
    await Economy.token_sources.callback(Economy.__new__(Economy), interaction, target)
    return lookup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_id", [MODERATOR_ROLE_ID, ADMIN_ROLE_ID], ids=["moderator", "admin"]
)
async def test_staff_can_use_token_sources(mock_interaction, monkeypatch, role_id):
    interaction = _as_staff(mock_interaction, role_id)

    lookup = await _run_command(interaction, monkeypatch, counts={"chat": 10})

    lookup.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_ids",
    [(), (TRIAL_MODERATOR_ROLE_ID,), (SERVER_BOOSTER_ROLE_ID,)],
    ids=["member", "trial_moderator", "booster"],
)
async def test_non_staff_are_denied_token_sources(
    mock_interaction, monkeypatch, role_ids
):
    interaction = _as_staff(mock_interaction, *role_ids)

    lookup = await _run_command(interaction, monkeypatch)

    lookup.assert_not_awaited()
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_token_sources_is_denied_in_dms(mock_interaction, monkeypatch):
    # In a DM the user is a plain discord.User with no roles.
    mock_interaction.user = MagicMock(spec=discord.User)
    mock_interaction.user.id = 987654321

    lookup = await _run_command(mock_interaction, monkeypatch)

    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_token_sources_reply_is_only_visible_to_the_caller(
    mock_interaction, monkeypatch
):
    interaction = _as_staff(mock_interaction, MODERATOR_ROLE_ID)

    await _run_command(interaction, monkeypatch, counts={"chat": 10})

    assert interaction.response.defer.await_args.kwargs["ephemeral"] is True
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_token_sources_command_defaults_to_the_caller(
    mock_interaction, monkeypatch
):
    interaction = _as_staff(mock_interaction, MODERATOR_ROLE_ID)

    lookup = await _run_command(interaction, monkeypatch, counts={"chat": 10})

    lookup.assert_awaited_once_with("987654321")


@pytest.mark.asyncio
async def test_token_sources_command_looks_up_the_named_user(
    mock_interaction, monkeypatch
):
    interaction = _as_staff(mock_interaction, ADMIN_ROLE_ID)
    target = MagicMock(id=42, display_name="Someone")

    lookup = await _run_command(interaction, monkeypatch, target=target)

    lookup.assert_awaited_once_with("42")


# --- auto-post on redemption ticket open ---


def _ticket_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock()
    guild.get_role = MagicMock(return_value=None)
    guild.get_channel = MagicMock(return_value=MagicMock(spec=discord.CategoryChannel))
    channel = MagicMock(spec=discord.TextChannel)
    channel.set_permissions = AsyncMock()
    channel.edit = AsyncMock()
    channel.send = AsyncMock()
    guild.create_text_channel = AsyncMock(return_value=channel)
    return guild, channel


def _opener():
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.name = "opener"
    member.display_name = "Opener"
    member.mention = "<@42>"
    return member


async def _open_ticket(monkeypatch, lookup):
    guild, channel = _ticket_guild()
    monkeypatch.setattr("features.economy.REDEMPTION_TICKET_CATEGORY_ID", 1)
    monkeypatch.setattr(
        "features.economy.get_user_balance", AsyncMock(return_value=100)
    )
    monkeypatch.setattr("features.economy.get_token_sources", lookup)
    result = await create_redemption_ticket(guild, _opener(), "nitro", 5.0)
    return result, channel


@pytest.mark.asyncio
async def test_ticket_open_posts_the_openers_breakdown(monkeypatch):
    lookup = AsyncMock(return_value={"daily": 300, "chat": 100})

    _, channel = await _open_ticket(monkeypatch, lookup)

    lookup.assert_awaited_once_with("42")
    embeds = [c.kwargs.get("embed") for c in channel.send.await_args_list]
    breakdown = [e for e in embeds if e and "Token Sources" in e.title]
    assert len(breakdown) == 1
    assert "75.0%" in breakdown[0].description


@pytest.mark.asyncio
async def test_ticket_still_opens_if_the_breakdown_fails(monkeypatch):
    # Callers record the returned channel; raising here would make reconcile
    # think no ticket exists and refund a redemption that went through.
    lookup = AsyncMock(side_effect=RuntimeError("mongo down"))

    result, channel = await _open_ticket(monkeypatch, lookup)

    assert result is channel
