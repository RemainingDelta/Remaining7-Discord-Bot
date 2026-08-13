"""Tests for pure functions in features/economy.py."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from features.config import (
    REDEMPTION_TICKET_CATEGORY_ID,
    REDEMPTION_TRANSCRIPT_CHANNEL_ID,
)
from features.economy import (
    Economy,
    _booster_tenure_eligible,
    _budget_month_key,
    _budget_cost_for_item,
    _discounted_price,
    _extract_topic_value,
    _pending_redemptions_total,
    _redemption_instructions,
    _token_price_for_item,
)


# --- _budget_month_key ---


def test_budget_month_key_is_valid_format():
    key = _budget_month_key()
    datetime.strptime(key, "%Y-%m")  # raises ValueError if format is wrong


def test_budget_month_key_matches_current_month():
    key = _budget_month_key()
    expected = datetime.utcnow().strftime("%Y-%m")
    assert key == expected


# --- _budget_cost_for_item ---


def test_budget_cost_brawl_pass():
    assert _budget_cost_for_item("brawl pass") == 9.0


def test_budget_cost_brawl_pass_plus():
    assert _budget_cost_for_item("brawl pass+") == 13.0


def test_budget_cost_nitro():
    assert _budget_cost_for_item("nitro") == 10.0


def test_budget_cost_paypal():
    assert _budget_cost_for_item("paypal") == 15.0


def test_budget_cost_shoutout_is_free():
    assert _budget_cost_for_item("shoutout") == 0.0


def test_budget_cost_case_insensitive():
    assert _budget_cost_for_item("Brawl Pass") == 9.0
    assert _budget_cost_for_item("NITRO") == 10.0


def test_budget_cost_unknown_item_returns_zero():
    assert _budget_cost_for_item("nonexistent item xyz") == 0.0


# --- _token_price_for_item ---


def test_token_price_unknown_item_returns_zero():
    assert _token_price_for_item("this item does not exist") == 0


# --- _discounted_price ---


def test_discounted_price_brawl_pass():
    assert _discounted_price(5000) == 4500


def test_discounted_price_small_price():
    assert _discounted_price(500) == 450


def test_discounted_price_truncates():
    assert _discounted_price(55) == 49


def test_discounted_price_zero():
    assert _discounted_price(0) == 0


# --- _booster_tenure_eligible ---


class _FakeMember:
    def __init__(self, has_role: bool, premium_since):
        self._has_role = has_role
        self.premium_since = premium_since

    def get_role(self, role_id):
        return MagicMock() if self._has_role else None


def test_tenure_eligible_long_boost():
    since = datetime.now(timezone.utc) - timedelta(days=20)
    assert _booster_tenure_eligible(_FakeMember(True, since)) is True


def test_tenure_ineligible_short_boost():
    since = datetime.now(timezone.utc) - timedelta(days=5)
    assert _booster_tenure_eligible(_FakeMember(True, since)) is False


def test_tenure_ineligible_no_premium_since():
    assert _booster_tenure_eligible(_FakeMember(True, None)) is False


def test_tenure_ineligible_without_role():
    since = datetime.now(timezone.utc) - timedelta(days=20)
    assert _booster_tenure_eligible(_FakeMember(False, since)) is False


def test_tenure_ineligible_non_member_user():
    # Users outside a guild (e.g. DMs) have no get_role/premium_since.
    assert _booster_tenure_eligible(object()) is False


# --- _extract_topic_value ---


def test_extract_topic_value_single_key():
    assert (
        _extract_topic_value("redemption-opener:12345", "redemption-opener") == "12345"
    )


def test_extract_topic_value_with_multiple_parts():
    topic = "redemption-opener:12345|item:brawl pass|type:redemption"
    assert _extract_topic_value(topic, "item") == "brawl pass"
    assert _extract_topic_value(topic, "redemption-opener") == "12345"
    assert _extract_topic_value(topic, "type") == "redemption"


def test_extract_topic_value_key_not_present():
    assert _extract_topic_value("redemption-opener:12345", "missing") is None


def test_extract_topic_value_none_topic():
    assert _extract_topic_value(None, "key") is None


def test_extract_topic_value_empty_topic():
    assert _extract_topic_value("", "key") is None


def test_extract_topic_value_empty_value():
    # key is present but value is empty string
    assert _extract_topic_value("key:", "key") == ""


# --- _redemption_instructions ---


def test_instructions_brawl_pass():
    assert "in-game ID" in _redemption_instructions("brawl pass")
    assert "in-game ID" in _redemption_instructions("brawl pass+")


def test_instructions_nitro():
    assert "Nitro" in _redemption_instructions("nitro")


def test_instructions_paypal():
    assert "PayPal" in _redemption_instructions("paypal")


def test_instructions_shoutout():
    assert "shouted out" in _redemption_instructions("shoutout")


def test_instructions_default():
    assert _redemption_instructions("pin") == "- Provide necessary details."


# --- _pending_redemptions_total ---


def _fake_ticket_channel(topic):
    channel = MagicMock(spec=discord.TextChannel)
    channel.topic = topic
    return channel


def _fake_guild_with_tickets(topics):
    category = MagicMock(spec=discord.CategoryChannel)
    category.text_channels = [_fake_ticket_channel(t) for t in topics]
    guild = MagicMock(spec=discord.Guild)
    guild.get_channel = MagicMock(
        side_effect=lambda cid: (
            category if cid == REDEMPTION_TICKET_CATEGORY_ID else None
        )
    )
    return guild


def test_pending_total_none_guild():
    assert _pending_redemptions_total(None) == (0.0, 0)


def test_pending_total_category_not_found():
    guild = MagicMock(spec=discord.Guild)
    guild.get_channel = MagicMock(return_value=None)
    assert _pending_redemptions_total(guild) == (0.0, 0)


def test_pending_total_empty_category():
    guild = _fake_guild_with_tickets([])
    assert _pending_redemptions_total(guild) == (0.0, 0)


def test_pending_total_sums_ticket_topics():
    guild = _fake_guild_with_tickets(
        [
            "redemption-opener:1|item:brawl pass|budget_usd:10.00",
            "redemption-opener:2|item:paypal|budget_usd:15.00",
        ]
    )
    assert _pending_redemptions_total(guild) == (25.0, 2)


def test_pending_total_skips_non_ticket_channels():
    guild = _fake_guild_with_tickets(
        [
            None,
            "just a normal channel topic",
            "redemption-opener:1|item:nitro|budget_usd:10.00",
        ]
    )
    assert _pending_redemptions_total(guild) == (10.0, 1)


def test_pending_total_falls_back_to_item_cost():
    guild = _fake_guild_with_tickets(
        [
            "redemption-opener:1|item:brawl pass",  # missing budget_usd
            "redemption-opener:2|item:paypal|budget_usd:notanumber",
        ]
    )
    assert _pending_redemptions_total(guild) == (24.0, 2)


def test_pending_total_ignores_zero_cost_tickets():
    guild = _fake_guild_with_tickets(
        [
            "redemption-opener:1|item:shoutout|budget_usd:0.00",
            "redemption-opener:2|item:nitro|budget_usd:10.00",
        ]
    )
    assert _pending_redemptions_total(guild) == (10.0, 1)


# --- process_redemption_queue ---


def _make_economy_cog(category):
    cog = Economy.__new__(Economy)  # skip __init__ so task loops don't start
    bot = MagicMock()
    transcript_channel = MagicMock()
    transcript_channel.send = AsyncMock()
    channels = {
        REDEMPTION_TICKET_CATEGORY_ID: category,
        REDEMPTION_TRANSCRIPT_CHANNEL_ID: transcript_channel,
    }
    bot.get_channel = MagicMock(side_effect=channels.get)
    cog.bot = bot
    return cog, transcript_channel


def _http_error(exc_type, status):
    """Builds a discord HTTP exception without a real aiohttp response."""
    return exc_type(MagicMock(status=status), "boom")


def _make_category_with_members(member_ids, fetch_member=None):
    category = MagicMock(spec=discord.CategoryChannel)
    guild = MagicMock(spec=discord.Guild)
    members = {mid: MagicMock(spec=discord.Member) for mid in member_ids}
    guild.get_member = MagicMock(side_effect=members.get)
    # A cache miss falls back to fetch_member; default to "genuinely gone".
    guild.fetch_member = fetch_member or AsyncMock(
        side_effect=_http_error(discord.NotFound, 404)
    )
    category.guild = guild
    return category


def _patch_queue_helpers(monkeypatch, entries, budgets):
    """Patches the queue processing collaborators; returns the key mocks."""
    create_ticket = AsyncMock()
    remove_entry = AsyncMock()
    refund = AsyncMock()
    monkeypatch.setattr(
        "features.economy.get_redemption_queue", AsyncMock(return_value=entries)
    )
    monkeypatch.setattr(
        "features.economy.get_effective_budget",
        AsyncMock(side_effect=[(50.0, 0.0, 0.0, b) for b in budgets]),
    )
    monkeypatch.setattr("features.economy.create_redemption_ticket", create_ticket)
    monkeypatch.setattr("features.economy.remove_redemption_queue_entry", remove_entry)
    monkeypatch.setattr("features.economy.increment_user_balance", refund)
    monkeypatch.setattr("features.economy._increment_redeem_counter", AsyncMock())
    return create_ticket, remove_entry, refund


async def test_queue_processing_fulfills_fifo(monkeypatch):
    category = _make_category_with_members([1, 2])
    cog, _ = _make_economy_cog(category)
    entries = [
        {"_id": "a1", "user_id": "1", "item": "brawl pass"},
        {"_id": "a2", "user_id": "2", "item": "paypal"},
    ]
    create_ticket, remove_entry, _ = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0, 40.0]
    )

    await cog.process_redemption_queue()

    assert create_ticket.await_count == 2
    first_item = create_ticket.await_args_list[0].args[2]
    second_item = create_ticket.await_args_list[1].args[2]
    assert (first_item, second_item) == ("brawl pass", "paypal")
    assert remove_entry.await_count == 2


async def test_queue_processing_skips_unaffordable_entry(monkeypatch):
    category = _make_category_with_members([1, 2])
    cog, _ = _make_economy_cog(category)
    entries = [
        {"_id": "a1", "user_id": "1", "item": "paypal"},  # $15 > $12 available
        {"_id": "a2", "user_id": "2", "item": "brawl pass"},  # $9 fits
    ]
    create_ticket, remove_entry, _ = _patch_queue_helpers(
        monkeypatch, entries, budgets=[12.0, 12.0]
    )

    await cog.process_redemption_queue()

    assert create_ticket.await_count == 1
    assert create_ticket.await_args.args[2] == "brawl pass"
    remove_entry.assert_awaited_once_with("a2")


async def test_queue_processing_refunds_when_member_left(monkeypatch):
    category = _make_category_with_members([])
    cog, transcript_channel = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass"}]
    create_ticket, remove_entry, refund = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )

    await cog.process_redemption_queue()

    create_ticket.assert_not_awaited()
    remove_entry.assert_awaited_once_with("a1")
    refund.assert_awaited_once_with("1", _token_price_for_item("brawl pass"))
    transcript_channel.send.assert_awaited_once()


async def test_queue_processing_keeps_entry_on_cache_miss_when_member_present(
    monkeypatch,
):
    # get_member misses (cold cache) but the user is still in the server, so
    # fetch_member resolves them — the redemption must proceed, not refund.
    fetch_member = AsyncMock(return_value=MagicMock(spec=discord.Member))
    category = _make_category_with_members([], fetch_member=fetch_member)
    cog, transcript_channel = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass"}]
    create_ticket, remove_entry, refund = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )

    await cog.process_redemption_queue()

    fetch_member.assert_awaited_once_with(1)
    create_ticket.assert_awaited_once()
    remove_entry.assert_awaited_once_with("a1")
    refund.assert_not_awaited()
    transcript_channel.send.assert_not_awaited()


async def test_queue_processing_skips_entry_on_transient_fetch_error(monkeypatch):
    # A transient API error must NOT be treated as "user left" — leave the entry
    # queued for the next cycle without refunding or dropping it.
    fetch_member = AsyncMock(side_effect=_http_error(discord.HTTPException, 503))
    category = _make_category_with_members([], fetch_member=fetch_member)
    cog, transcript_channel = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass"}]
    create_ticket, remove_entry, refund = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )

    await cog.process_redemption_queue()

    create_ticket.assert_not_awaited()
    remove_entry.assert_not_awaited()
    refund.assert_not_awaited()
    transcript_channel.send.assert_not_awaited()


async def test_queue_entry_kept_when_ticket_creation_fails(monkeypatch):
    category = _make_category_with_members([1, 2])
    cog, _ = _make_economy_cog(category)
    entries = [
        {"_id": "a1", "user_id": "1", "item": "brawl pass"},
        {"_id": "a2", "user_id": "2", "item": "nitro"},
    ]
    create_ticket, remove_entry, _ = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0, 40.0]
    )
    create_ticket.side_effect = [Exception("boom"), MagicMock()]

    await cog.process_redemption_queue()

    assert create_ticket.await_count == 2
    remove_entry.assert_awaited_once_with("a2")


async def test_queue_processing_raises_without_category(monkeypatch):
    cog, _ = _make_economy_cog(None)
    _patch_queue_helpers(monkeypatch, [], budgets=[])

    with pytest.raises(RuntimeError):
        await cog.process_redemption_queue()


# --- reconcile_pending_redemptions (crash recovery) ---


def _make_category_with_ticket_topics(topics):
    category = MagicMock(spec=discord.CategoryChannel)
    category.text_channels = [_fake_ticket_channel(t) for t in topics]
    return category


def _patch_reconcile_helpers(monkeypatch, pending_rows):
    """Patches the reconcile collaborators; returns (refund, clear) mocks."""
    refund = AsyncMock()
    clear = AsyncMock()
    monkeypatch.setattr(
        "features.economy.get_all_pending_redemptions",
        AsyncMock(return_value=pending_rows),
    )
    monkeypatch.setattr("features.economy.add_item_token", refund)
    monkeypatch.setattr("features.economy.clear_pending_redemption", clear)
    return refund, clear


async def test_reconcile_noop_when_nothing_pending(monkeypatch):
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    refund, clear = _patch_reconcile_helpers(monkeypatch, [])

    await cog.reconcile_pending_redemptions()

    refund.assert_not_awaited()
    clear.assert_not_awaited()


async def test_reconcile_with_channel_id_clears_without_refund(monkeypatch):
    # Ticket was created (channel_id persisted) -> never refund.
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    rows = [
        {"user_id": "1", "id": "p1", "item": "brawl pass", "channel_id": 999},
    ]
    refund, clear = _patch_reconcile_helpers(monkeypatch, rows)

    await cog.reconcile_pending_redemptions()

    refund.assert_not_awaited()
    clear.assert_awaited_once_with("1", "p1")


async def test_reconcile_no_channel_no_ticket_refunds(monkeypatch):
    # Crash before/at ticket creation, no matching ticket exists -> refund.
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    rows = [
        {"user_id": "1", "id": "p1", "item": "brawl pass", "channel_id": None},
    ]
    refund, clear = _patch_reconcile_helpers(monkeypatch, rows)

    await cog.reconcile_pending_redemptions()

    refund.assert_awaited_once_with("1", "brawl pass", quantity=1)
    clear.assert_awaited_once_with("1", "p1")


async def test_reconcile_no_channel_matching_ticket_adopts_without_refund(monkeypatch):
    # Crash in the create->persist window: a ticket exists for this user+item.
    category = _make_category_with_ticket_topics(
        ["redemption-opener:1|item:brawl pass|budget_usd:9.00"]
    )
    cog, _ = _make_economy_cog(category)
    rows = [
        {"user_id": "1", "id": "p1", "item": "brawl pass", "channel_id": None},
    ]
    refund, clear = _patch_reconcile_helpers(monkeypatch, rows)

    await cog.reconcile_pending_redemptions()

    refund.assert_not_awaited()
    clear.assert_awaited_once_with("1", "p1")


async def test_reconcile_ticket_match_requires_same_item(monkeypatch):
    # A ticket for a different item must not be adopted -> still refunds.
    category = _make_category_with_ticket_topics(
        ["redemption-opener:1|item:nitro|budget_usd:10.00"]
    )
    cog, _ = _make_economy_cog(category)
    rows = [
        {"user_id": "1", "id": "p1", "item": "brawl pass", "channel_id": None},
    ]
    refund, clear = _patch_reconcile_helpers(monkeypatch, rows)

    await cog.reconcile_pending_redemptions()

    refund.assert_awaited_once_with("1", "brawl pass", quantity=1)
    clear.assert_awaited_once_with("1", "p1")


async def test_reconcile_defers_when_category_unavailable(monkeypatch):
    # Without the category we cannot verify a ticket -> leave marker, no refund.
    cog, _ = _make_economy_cog(None)
    rows = [
        {"user_id": "1", "id": "p1", "item": "brawl pass", "channel_id": None},
    ]
    refund, clear = _patch_reconcile_helpers(monkeypatch, rows)

    await cog.reconcile_pending_redemptions()

    refund.assert_not_awaited()
    clear.assert_not_awaited()


# --- begin_pending_redemption (atomic token consume + marker) ---


async def test_begin_pending_redemption_atomic_query_shape(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    monkeypatch.setattr(mongo, "db", fake_db)

    pending_id = await mongo.begin_pending_redemption("42", "brawl pass", 9.0)

    assert isinstance(pending_id, str) and pending_id
    call = fake_db.users.update_one.await_args
    query, update = call.args[0], call.args[1]
    # Conditional decrement: only matches when the user still owns the item.
    assert query == {"_id": "42", "inventory.brawl pass": {"$gte": 1}}
    assert update["$inc"] == {"inventory.brawl pass": -1}
    pushed = update["$push"]["pending_redemptions"]
    assert pushed["id"] == pending_id
    assert pushed["item"] == "brawl pass"
    assert pushed["channel_id"] is None


async def test_begin_pending_redemption_returns_none_when_not_owned(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.begin_pending_redemption("42", "brawl pass", 9.0) is None


# --- purchase_item (atomic deduct + grant) ---


async def test_purchase_item_atomic_query_shape(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    monkeypatch.setattr(mongo, "db", fake_db)

    ok = await mongo.purchase_item("42", "brawl pass", 18000)

    assert ok is True
    call = fake_db.users.update_one.await_args
    query, update = call.args[0], call.args[1]
    # Conditional deduct: only matches when the balance still covers the price.
    assert query == {"_id": "42", "balance": {"$gte": 18000}}
    # Deduct + grant happen in one atomic $inc on the same document.
    assert update["$inc"] == {"balance": -18000, "inventory.brawl pass": 1}
    # No discount stamp requested -> no $set.
    assert "$set" not in update


async def test_purchase_item_returns_false_when_insufficient(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
    monkeypatch.setattr(mongo, "db", fake_db)

    # modified_count == 0 -> balance no longer covers the price -> no-op.
    assert await mongo.purchase_item("42", "brawl pass", 18000) is False


async def test_purchase_item_stamps_discount_month(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    monkeypatch.setattr(mongo, "db", fake_db)

    ok = await mongo.purchase_item("42", "brawl pass", 16200, discount_month="2026-08")

    assert ok is True
    update = fake_db.users.update_one.await_args.args[1]
    # The booster-discount month is stamped in the same atomic write.
    assert update["$set"] == {"booster_discount_month": "2026-08"}
    assert update["$inc"] == {"balance": -16200, "inventory.brawl pass": 1}
