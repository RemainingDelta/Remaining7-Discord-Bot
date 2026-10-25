"""Tests for per-user token source tracking (#606).

Cases are derived from the issue's Acceptance Criteria:
- the source of every token a user earns is recorded
- any user's total can be broken down by source as percentages
- chatting, daily and drops (plus the other earning paths) are tracked

Redemption refunds return tokens that were already counted under their real
source when first earned, so they must never add to a source counter.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import database.mongo as mongo
import features.economy as economy
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


# --- per-user daily earning history (for purchase breakdowns) ---


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _history_db():
    db = _fake_db(existing={"_id": "42", "brawlers": {"shelly": {}}})
    db.user_token_days.update_one = AsyncMock()
    return db


def _day_write(source, amount):
    today = _today()
    return (
        {"_id": f"42:{today}"},
        {"$inc": {source: amount}, "$setOnInsert": {"user_id": "42", "day": today}},
    )


@pytest.mark.asyncio
async def test_earning_is_added_to_the_users_day(monkeypatch):
    db = _history_db()
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 25, source="chat")

    filt, update = _day_write("chat", 25)
    db.user_token_days.update_one.assert_awaited_once_with(filt, update, upsert=True)


@pytest.mark.asyncio
async def test_daily_claim_is_added_to_the_users_day():
    db = _history_db()
    with patch.object(mongo, "db", db):
        await mongo.claim_daily_reward("42", 120, cutoff_ts=0.0, now_ts=1.0)

    filt, update = _day_write("daily", 120)
    db.user_token_days.update_one.assert_awaited_once_with(filt, update, upsert=True)


@pytest.mark.asyncio
async def test_quest_reward_is_added_to_the_users_day():
    db = _history_db()
    with patch.object(mongo, "db", db):
        await mongo.add_quest_reward("42", tokens=50, exp=20)

    filt, update = _day_write("quest", 50)
    db.user_token_days.update_one.assert_awaited_once_with(filt, update, upsert=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grant",
    [
        lambda: mongo.increment_user_balance("42", 25),
        lambda: mongo.increment_user_balance("42", -25, source="drop"),
        lambda: mongo.apply_queue_refund("42", "entry1", tokens=500),
    ],
    ids=["no_source", "deduction", "refund"],
)
async def test_non_earnings_are_not_added_to_the_users_day(grant):
    db = _history_db()
    with patch.object(mongo, "db", db):
        await grant()

    db.user_token_days.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_daily_claim_is_not_added_to_the_users_day():
    db = _history_db()
    db.users.find_one_and_update = AsyncMock(return_value=None)
    with patch.object(mongo, "db", db):
        await mongo.claim_daily_reward("42", 120, cutoff_ts=0.0, now_ts=1.0)

    db.user_token_days.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_history_write_does_not_fail_the_payout():
    db = _history_db()
    db.user_token_days.update_one = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(mongo, "db", db):
        await mongo.increment_user_balance("42", 25, source="chat")

    db.users.update_one.assert_awaited_once()


# --- split_recent_earnings: how the last N tokens were earned ---


def _day(day, **sources):
    return {"_id": f"42:{day}", "user_id": "42", "day": day, **sources}


def test_most_recent_day_is_used_first():
    days = [_day("2026-10-02", admin=50), _day("2026-10-01", chat=100)]

    assert mongo.split_recent_earnings(days, 50) == {"admin": 50}


def test_window_reaches_back_across_days():
    days = [_day("2026-10-02", admin=50), _day("2026-10-01", chat=100)]

    assert mongo.split_recent_earnings(days, 100) == {"admin": 50, "chat": 50}


def test_oldest_day_is_split_proportionally():
    days = [_day("2026-10-01", chat=30, daily=90)]

    assert mongo.split_recent_earnings(days, 60) == {"chat": 15, "daily": 45}


def test_split_always_sums_to_the_amount():
    days = [_day("2026-10-01", chat=1, daily=1, drop=1)]

    split = mongo.split_recent_earnings(days, 2)

    # Rounding remainders stay with tracked sources, not "untracked".
    assert "untracked" not in split
    assert sum(split.values()) == 2


def test_tokens_from_before_tracking_are_untracked():
    days = [_day("2026-10-01", chat=10)]

    assert mongo.split_recent_earnings(days, 25) == {"chat": 10, "untracked": 15}


def test_no_history_is_all_untracked():
    assert mongo.split_recent_earnings([], 18000) == {"untracked": 18000}


class _Cursor:
    def __init__(self, docs):
        self.docs = docs
        self.sorted_by = None

    def sort(self, *args):
        self.sorted_by = args
        return self

    def __aiter__(self):
        async def gen():
            for d in self.docs:
                yield d

        return gen()


@pytest.mark.asyncio
async def test_recent_earnings_reads_the_users_days_newest_first():
    db = MagicMock()
    cursor = _Cursor([_day("2026-10-02", admin=50), _day("2026-10-01", chat=100)])
    db.user_token_days.find = MagicMock(return_value=cursor)
    with patch.object(mongo, "db", db):
        result = await mongo.recent_earnings_breakdown("42", 100)

    db.user_token_days.find.assert_called_once_with({"user_id": "42"})
    assert cursor.sorted_by == ("day", -1)
    assert result == {"admin": 50, "chat": 50}


# --- purchase snapshots ---


@pytest.mark.asyncio
async def test_purchase_snapshot_records_what_was_paid():
    db = MagicMock()
    db.purchase_snapshots.insert_one = AsyncMock()
    with patch.object(mongo, "db", db):
        await mongo.save_purchase_snapshot("42", "nitro", 16200, {"daily": 16200})

    doc = db.purchase_snapshots.insert_one.await_args.args[0]
    assert doc["user_id"] == "42"
    assert doc["item"] == "nitro"
    assert doc["price"] == 16200
    assert doc["breakdown"] == {"daily": 16200}
    assert doc["used_channel_id"] is None


@pytest.mark.asyncio
async def test_ticket_claims_the_oldest_unused_snapshot_for_that_item():
    db = MagicMock()
    db.purchase_snapshots.find_one_and_update = AsyncMock(return_value=None)
    with patch.object(mongo, "db", db):
        await mongo.claim_purchase_snapshot("42", "nitro", 777)

    call = db.purchase_snapshots.find_one_and_update.await_args
    filt, update = call.args
    assert filt == {"user_id": "42", "item": "nitro", "used_channel_id": None}
    assert update == {"$set": {"used_channel_id": 777}}
    assert call.kwargs["sort"] == [("created_at", 1)]


# --- /buy saves the snapshot ---


async def _buy(monkeypatch, mock_interaction, *, discount, snapshot_error=None):
    mock_interaction.user.roles = []
    mock_interaction.user.id = 42
    price = economy.SHOP_DATA["nitro"]["price"]
    monkeypatch.setattr(
        "features.economy.get_user_balance", AsyncMock(return_value=10**6)
    )
    monkeypatch.setattr(
        "features.economy._booster_discount_available",
        AsyncMock(return_value=discount),
    )
    monkeypatch.setattr("features.economy.purchase_item", AsyncMock(return_value=True))
    breakdown = AsyncMock(return_value={"chat": 1})
    monkeypatch.setattr("features.economy.recent_earnings_breakdown", breakdown)
    save = AsyncMock(side_effect=snapshot_error)
    monkeypatch.setattr("features.economy.save_purchase_snapshot", save)
    await Economy.buy.callback(Economy.__new__(Economy), mock_interaction, "nitro")
    return price, breakdown, save


@pytest.mark.asyncio
async def test_buy_snapshots_the_tokens_spent(monkeypatch, mock_interaction):
    price, breakdown, save = await _buy(monkeypatch, mock_interaction, discount=False)

    breakdown.assert_awaited_once_with("42", price)
    save.assert_awaited_once_with("42", "nitro", price, {"chat": 1})


@pytest.mark.asyncio
async def test_buy_snapshots_the_discounted_price(monkeypatch, mock_interaction):
    price, breakdown, _ = await _buy(monkeypatch, mock_interaction, discount=True)

    breakdown.assert_awaited_once_with("42", economy._discounted_price(price))


@pytest.mark.asyncio
async def test_a_failed_snapshot_still_completes_the_purchase(
    monkeypatch, mock_interaction
):
    await _buy(
        monkeypatch, mock_interaction, discount=False, snapshot_error=RuntimeError()
    )

    embed = mock_interaction.response.send_message.await_args.kwargs["embed"]
    assert "Purchase Successful" in embed.title


# --- redemption ticket shows the purchase breakdown ---


def _ticket_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock()
    guild.get_role = MagicMock(return_value=None)
    guild.get_channel = MagicMock(return_value=MagicMock(spec=discord.CategoryChannel))
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 777
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


async def _open_ticket(monkeypatch, snapshot, lifetime=None):
    guild, channel = _ticket_guild()
    monkeypatch.setattr("features.economy.REDEMPTION_TICKET_CATEGORY_ID", 1)
    monkeypatch.setattr(
        "features.economy.get_user_balance", AsyncMock(return_value=100)
    )
    claim = (
        snapshot
        if isinstance(snapshot, AsyncMock)
        else AsyncMock(return_value=snapshot)
    )
    monkeypatch.setattr("features.economy.claim_purchase_snapshot", claim)
    lookup = AsyncMock(return_value=lifetime or {})
    monkeypatch.setattr("features.economy.get_token_sources", lookup)
    result = await create_redemption_ticket(guild, _opener(), "nitro", 5.0)
    return result, channel, claim, lookup


def _breakdown_embed(channel):
    embeds = [c.kwargs.get("embed") for c in channel.send.await_args_list]
    found = [e for e in embeds if e and e.title.startswith("📊")]
    assert len(found) == 1
    return found[0]


@pytest.mark.asyncio
async def test_ticket_shows_how_the_purchase_was_earned(monkeypatch):
    snapshot = {"price": 18000, "breakdown": {"admin": 13500, "chat": 4500}}

    _, channel, claim, lookup = await _open_ticket(monkeypatch, snapshot)

    claim.assert_awaited_once_with("42", "nitro", 777)
    lookup.assert_not_awaited()
    embed = _breakdown_embed(channel)
    assert "18,000" in embed.title
    assert "13500" in embed.description and "75.0%" in embed.description


@pytest.mark.asyncio
async def test_ticket_shows_untracked_tokens(monkeypatch):
    snapshot = {"price": 100, "breakdown": {"chat": 40, "untracked": 60}}

    _, channel, _, _ = await _open_ticket(monkeypatch, snapshot)

    assert "Before tracking" in _breakdown_embed(channel).description


@pytest.mark.asyncio
async def test_ticket_without_a_snapshot_falls_back_to_lifetime(monkeypatch):
    _, channel, _, lookup = await _open_ticket(
        monkeypatch, None, lifetime={"daily": 300, "chat": 100}
    )

    lookup.assert_awaited_once_with("42")
    embed = _breakdown_embed(channel)
    assert "75.0%" in embed.description
    assert "No purchase record" in embed.description


@pytest.mark.asyncio
async def test_ticket_still_opens_if_the_breakdown_fails(monkeypatch):
    # Callers record the returned channel; raising here would make reconcile
    # think no ticket exists and refund a redemption that went through.
    failing = AsyncMock(side_effect=RuntimeError("mongo down"))

    result, channel, _, _ = await _open_ticket(monkeypatch, failing)

    assert result is channel
