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
    # create_redemption_ticket returns the channel it made; the queue processor
    # reads .id off it to record on the entry, so hand back a channel with one.
    create_ticket = AsyncMock(return_value=MagicMock(id=999))
    remove_entry = AsyncMock()
    # apply_queue_refund is the member-left refund mechanism (crash-safe, idempotent).
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
    monkeypatch.setattr("features.economy.apply_queue_refund", refund)
    monkeypatch.setattr("features.economy._increment_redeem_counter", AsyncMock())
    # Crash-safe claim/record: claims succeed by default; tests that exercise a
    # lost claim or a pre-claimed entry re-patch these.
    monkeypatch.setattr(
        "features.economy.claim_redemption_queue_entry",
        AsyncMock(return_value=True),
    )
    # Member-left refund claim: succeeds by default, returning the claimed doc.
    monkeypatch.setattr(
        "features.economy.claim_redemption_queue_refund",
        AsyncMock(return_value={"user_id": "1", "item": "brawl pass"}),
    )
    monkeypatch.setattr(
        "features.economy.set_redemption_queue_entry_channel", AsyncMock()
    )
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

    # Crash-safe order: claim the entry for refund -> pay idempotently -> remove.
    create_ticket.assert_not_awaited()
    refund.assert_awaited_once_with(
        "1", "a1", tokens=_token_price_for_item("brawl pass")
    )
    remove_entry.assert_awaited_once_with("a1")
    transcript_channel.send.assert_awaited_once()


async def test_queue_processing_skips_member_left_when_refund_claim_lost(monkeypatch):
    # A racing staff /redemption-queue-remove (or a prior reconcile) already
    # claimed the entry -> claim returns None -> pay nothing, remove nothing.
    category = _make_category_with_members([])
    cog, transcript_channel = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass"}]
    create_ticket, remove_entry, refund = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )
    monkeypatch.setattr(
        "features.economy.claim_redemption_queue_refund",
        AsyncMock(return_value=None),
    )

    await cog.process_redemption_queue()

    create_ticket.assert_not_awaited()
    refund.assert_not_awaited()
    remove_entry.assert_not_awaited()
    transcript_channel.send.assert_not_awaited()


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


async def test_queue_processing_records_channel_before_removing(monkeypatch):
    # Crash-safe order: claim -> create ticket -> record its channel id -> remove.
    category = _make_category_with_members([1])
    cog, _ = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass"}]
    create_ticket, remove_entry, _ = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )
    claim = AsyncMock(return_value=True)
    set_channel = AsyncMock()
    monkeypatch.setattr("features.economy.claim_redemption_queue_entry", claim)
    monkeypatch.setattr(
        "features.economy.set_redemption_queue_entry_channel", set_channel
    )

    await cog.process_redemption_queue()

    claim.assert_awaited_once_with("a1")
    create_ticket.assert_awaited_once()
    set_channel.assert_awaited_once_with("a1", 999)  # id of the created channel
    remove_entry.assert_awaited_once_with("a1")


async def test_queue_processing_skips_already_claimed_entry(monkeypatch):
    # A claimed leftover from a crashed run (ticket may already exist) must never
    # be reprocessed here — that is the cold-boot reconcile's job.
    category = _make_category_with_members([1])
    cog, _ = _make_economy_cog(category)
    entries = [
        {
            "_id": "a1",
            "user_id": "1",
            "item": "brawl pass",
            "claimed_at": datetime.utcnow(),
        }
    ]
    create_ticket, remove_entry, _ = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr("features.economy.claim_redemption_queue_entry", claim)

    await cog.process_redemption_queue()

    claim.assert_not_awaited()  # skipped before even attempting a claim
    create_ticket.assert_not_awaited()
    remove_entry.assert_not_awaited()


async def test_queue_processing_skips_when_claim_lost(monkeypatch):
    # claim returns False (an earlier, possibly crashed, run owns the entry) ->
    # no second ticket, no removal.
    category = _make_category_with_members([1])
    cog, _ = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass"}]
    create_ticket, remove_entry, _ = _patch_queue_helpers(
        monkeypatch, entries, budgets=[50.0]
    )
    monkeypatch.setattr(
        "features.economy.claim_redemption_queue_entry",
        AsyncMock(return_value=False),
    )

    await cog.process_redemption_queue()

    create_ticket.assert_not_awaited()
    remove_entry.assert_not_awaited()


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


# --- reconcile_redemption_queue (crash recovery) ---


def _patch_queue_reconcile_helpers(monkeypatch, stuck_entries):
    """Patches the queue-reconcile collaborators; returns (refund, remove)."""
    refund = AsyncMock()
    remove_entry = AsyncMock()
    monkeypatch.setattr(
        "features.economy.get_stuck_redemption_queue_entries",
        AsyncMock(return_value=stuck_entries),
    )
    monkeypatch.setattr("features.economy.add_item_token", refund)
    monkeypatch.setattr("features.economy.remove_redemption_queue_entry", remove_entry)
    return refund, remove_entry


async def test_queue_reconcile_noop_when_nothing_stuck(monkeypatch):
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    refund, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, [])

    await cog.reconcile_redemption_queue()

    refund.assert_not_awaited()
    remove_entry.assert_not_awaited()


async def test_queue_reconcile_with_channel_removes_without_refund(monkeypatch):
    # channel_id recorded -> the ticket was created -> drop the entry, no refund.
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass", "channel_id": 999}]
    refund, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, entries)

    await cog.reconcile_redemption_queue()

    refund.assert_not_awaited()
    remove_entry.assert_awaited_once_with("a1")


async def test_queue_reconcile_no_channel_no_ticket_returns_item(monkeypatch):
    # Crash before/at ticket creation, no matching ticket -> return the item.
    cog, transcript_channel = _make_economy_cog(_make_category_with_ticket_topics([]))
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass", "channel_id": None}]
    refund, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, entries)

    await cog.reconcile_redemption_queue()

    refund.assert_awaited_once_with("1", "brawl pass", quantity=1)
    remove_entry.assert_awaited_once_with("a1")
    transcript_channel.send.assert_awaited_once()


async def test_queue_reconcile_no_channel_matching_ticket_no_refund(monkeypatch):
    # Crash in the create->persist window: a ticket exists for this user+item.
    category = _make_category_with_ticket_topics(
        ["redemption-opener:1|item:brawl pass|budget_usd:9.00"]
    )
    cog, _ = _make_economy_cog(category)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass", "channel_id": None}]
    refund, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, entries)

    await cog.reconcile_redemption_queue()

    refund.assert_not_awaited()
    remove_entry.assert_awaited_once_with("a1")


async def test_queue_reconcile_defers_when_category_unavailable(monkeypatch):
    # Without the category we cannot verify a ticket -> leave the entry, no refund.
    cog, _ = _make_economy_cog(None)
    entries = [{"_id": "a1", "user_id": "1", "item": "brawl pass", "channel_id": None}]
    refund, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, entries)

    await cog.reconcile_redemption_queue()

    refund.assert_not_awaited()
    remove_entry.assert_not_awaited()


async def test_queue_reconcile_refund_kind_tokens_pays_and_removes(monkeypatch):
    # A refund claim (member-left) that crashed before paying -> reconcile pays
    # the token refund idempotently and drops the entry.
    cog, transcript_channel = _make_economy_cog(_make_category_with_ticket_topics([]))
    entries = [{"_id": "a1", "user_id": "1", "item": "nitro", "refund_kind": "tokens"}]
    add_item, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, entries)
    apply_refund = AsyncMock()
    monkeypatch.setattr("features.economy.apply_queue_refund", apply_refund)

    await cog.reconcile_redemption_queue()

    apply_refund.assert_awaited_once_with(
        "1", "a1", tokens=_token_price_for_item("nitro")
    )
    # The refund branch fires BEFORE the channel_id/topic-scan logic: the ticket
    # path's item return (add_item_token) must never run for a token refund.
    add_item.assert_not_awaited()
    remove_entry.assert_awaited_once_with("a1")
    transcript_channel.send.assert_awaited_once()


async def test_queue_reconcile_refund_kind_item_returns_item(monkeypatch):
    # A refund claim (staff /redemption-queue-remove) that crashed before paying
    # -> reconcile returns the item idempotently and drops the entry.
    cog, transcript_channel = _make_economy_cog(_make_category_with_ticket_topics([]))
    entries = [
        {"_id": "a1", "user_id": "1", "item": "brawl pass", "refund_kind": "item"}
    ]
    add_item, remove_entry = _patch_queue_reconcile_helpers(monkeypatch, entries)
    apply_refund = AsyncMock()
    monkeypatch.setattr("features.economy.apply_queue_refund", apply_refund)

    await cog.reconcile_redemption_queue()

    apply_refund.assert_awaited_once_with("1", "a1", item="brawl pass")
    add_item.assert_not_awaited()
    remove_entry.assert_awaited_once_with("a1")
    transcript_channel.send.assert_awaited_once()


# --- /redemption-queue-remove (crash-safe item return) ---


def _patch_queue_remove_helpers(monkeypatch, claimed_doc):
    """Patches the command collaborators; returns (claim, apply, remove) mocks."""
    monkeypatch.setattr("features.economy._is_redemption_staff", lambda _u: True)
    claim = AsyncMock(return_value=claimed_doc)
    apply_refund = AsyncMock()
    remove_entry = AsyncMock()
    monkeypatch.setattr("features.economy.claim_redemption_queue_refund", claim)
    monkeypatch.setattr("features.economy.apply_queue_refund", apply_refund)
    monkeypatch.setattr("features.economy.remove_redemption_queue_entry", remove_entry)
    return claim, apply_refund, remove_entry


def _make_interaction():
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


async def test_queue_remove_claims_pays_then_removes(monkeypatch):
    # Crash-safe order: claim the entry for refund -> return the item -> remove.
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    claim, apply_refund, remove_entry = _patch_queue_remove_helpers(
        monkeypatch, {"user_id": "1", "item": "brawl pass"}
    )
    interaction = _make_interaction()

    await cog.redemption_queue_remove.callback(cog, interaction, "a1")

    claim.assert_awaited_once_with("a1", "item")
    apply_refund.assert_awaited_once_with("1", "a1", item="brawl pass")
    remove_entry.assert_awaited_once_with("a1")
    interaction.response.send_message.assert_awaited_once()


async def test_queue_remove_refuses_when_claim_lost(monkeypatch):
    # Entry missing or already claimed (racing member-left drop / reconcile) ->
    # claim returns None -> no payout, no removal, just an error reply.
    cog, _ = _make_economy_cog(_make_category_with_ticket_topics([]))
    claim, apply_refund, remove_entry = _patch_queue_remove_helpers(monkeypatch, None)
    interaction = _make_interaction()

    await cog.redemption_queue_remove.callback(cog, interaction, "a1")

    apply_refund.assert_not_awaited()
    remove_entry.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()


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


# --- claim_redemption_queue_refund (atomic refund claim) ---


async def test_claim_redemption_queue_refund_query_shape(monkeypatch):
    from bson import ObjectId
    from database import mongo

    oid = ObjectId()
    fake_db = MagicMock()
    fake_db.redemption_queue.find_one_and_update = AsyncMock(
        return_value={"_id": oid, "user_id": "1", "item": "brawl pass"}
    )
    monkeypatch.setattr(mongo, "db", fake_db)

    doc = await mongo.claim_redemption_queue_refund(str(oid), "tokens")

    assert doc is not None
    call = fake_db.redemption_queue.find_one_and_update.await_args
    query, update = call.args[0], call.args[1]
    # Only claims an UNclaimed entry -> a racing claim (ticket or refund) loses.
    assert query == {"_id": oid, "claimed_at": {"$exists": False}}
    assert update["$set"]["refund_kind"] == "tokens"
    # Does NOT set channel_id -> reconcile routes it to the refund branch.
    assert "channel_id" not in update["$set"]
    assert call.kwargs.get("return_document") is True


async def test_claim_redemption_queue_refund_none_when_already_claimed(monkeypatch):
    from bson import ObjectId
    from database import mongo

    fake_db = MagicMock()
    fake_db.redemption_queue.find_one_and_update = AsyncMock(return_value=None)
    monkeypatch.setattr(mongo, "db", fake_db)

    # Filter didn't match (already claimed / not found) -> None -> must not pay.
    assert await mongo.claim_redemption_queue_refund(str(ObjectId()), "item") is None


async def test_claim_redemption_queue_refund_none_on_bad_id(monkeypatch):
    from database import mongo

    monkeypatch.setattr(mongo, "db", MagicMock())
    assert await mongo.claim_redemption_queue_refund("not-an-objectid", "item") is None


# --- apply_queue_refund (idempotent payout + receipt) ---


def _fake_db_with_user():
    fake_db = MagicMock()
    # get_user_data (called inside apply_queue_refund) finds an existing doc.
    fake_db.users.find_one = AsyncMock(
        return_value={"_id": "1", "brawlers": {"shelly": {"level": 1}}}
    )
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    return fake_db


async def test_apply_queue_refund_tokens_shape(monkeypatch):
    from database import mongo

    fake_db = _fake_db_with_user()
    monkeypatch.setattr(mongo, "db", fake_db)

    ok = await mongo.apply_queue_refund("1", "a1", tokens=9)

    assert ok is True
    call = fake_db.users.update_one.await_args
    query, update = call.args[0], call.args[1]
    # Idempotency guard: only applies if this entry_id isn't already recorded.
    assert query == {"_id": "1", "queue_refunds_done": {"$ne": "a1"}}
    # The $inc payout and the receipt land in ONE atomic write.
    assert update["$inc"] == {"balance": 9}
    assert update["$addToSet"] == {"queue_refunds_done": "a1"}


async def test_apply_queue_refund_item_shape(monkeypatch):
    from database import mongo

    fake_db = _fake_db_with_user()
    monkeypatch.setattr(mongo, "db", fake_db)

    await mongo.apply_queue_refund("1", "a1", item="brawl pass")

    update = fake_db.users.update_one.await_args.args[1]
    assert update["$inc"] == {"inventory.brawl pass": 1}
    assert update["$addToSet"] == {"queue_refunds_done": "a1"}


async def test_apply_queue_refund_uses_upsert_off(monkeypatch):
    # upsert must stay OFF: the $ne filter + upsert would dup-key on _id.
    from database import mongo

    fake_db = _fake_db_with_user()
    monkeypatch.setattr(mongo, "db", fake_db)

    await mongo.apply_queue_refund("1", "a1", tokens=9)

    assert fake_db.users.update_one.await_args.kwargs.get("upsert", False) is False


async def test_apply_queue_refund_ensures_user_doc_exists(monkeypatch):
    # The helper owns the pre-create invariant so a missing doc can't silently
    # swallow the refund: get_user_data creates the doc before the payout write.
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.find_one = AsyncMock(return_value=None)  # doc missing
    fake_db.users.insert_one = AsyncMock()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    monkeypatch.setattr(mongo, "db", fake_db)

    await mongo.apply_queue_refund("ghost", "a1", tokens=9)

    fake_db.users.insert_one.assert_awaited_once()  # created before the payout


async def test_apply_queue_refund_returns_false_on_replay(monkeypatch):
    # Receipt already present -> filter matches nothing -> no-op (idempotent).
    from database import mongo

    fake_db = _fake_db_with_user()
    fake_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.apply_queue_refund("1", "a1", tokens=9) is False


# --- claim_drop (atomic, restart-safe per-drop single-claim guard) ---


async def test_claim_drop_won_when_new(monkeypatch):
    # find_one_and_update returns None -> no prior record -> this caller claimed it.
    from database import mongo

    fake_db = MagicMock()
    fake_db.drop_claims.find_one_and_update = AsyncMock(return_value=None)
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.claim_drop("msg1", "u1") is True


async def test_claim_drop_lost_when_already_claimed(monkeypatch):
    # A pre-existing record (someone else, possibly before a restart) -> reject.
    from database import mongo

    fake_db = MagicMock()
    fake_db.drop_claims.find_one_and_update = AsyncMock(
        return_value={"_id": "msg1", "claimed_by": "u2"}
    )
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.claim_drop("msg1", "u1") is False


async def test_claim_drop_records_claimer_via_setoninsert(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.drop_claims.find_one_and_update = AsyncMock(return_value=None)
    monkeypatch.setattr(mongo, "db", fake_db)

    await mongo.claim_drop("msg1", "u1")

    _, update = fake_db.drop_claims.find_one_and_update.call_args.args
    kwargs = fake_db.drop_claims.find_one_and_update.call_args.kwargs
    assert update["$setOnInsert"]["claimed_by"] == "u1"
    assert kwargs["upsert"] is True
