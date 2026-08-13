"""Tests for the crash-safe reward payout ledger (shared by /event-rewards and
/poll-rewards) and the poll payout loop's per-voter skip behavior.

The ledger claims a paid:False row before the balance $inc and commits paid:True
after; a pre-existing row makes the claim skip, so re-running after a mid-loop
crash only pays never-claimed recipients. These tests exercise both the claim
primitive and the poll loop that consumes it.
"""

from unittest.mock import AsyncMock, MagicMock

import discord

import database.mongo as mongo
from database.mongo import claim_reward_payout
from features.event import PollPayoutConfirmView


# --- claim_reward_payout primitive ---


def _fake_db(find_one_and_update_return):
    db = MagicMock()
    db.reward_payouts.find_one_and_update = AsyncMock(
        return_value=find_one_and_update_return
    )
    return db


async def test_claim_returns_true_when_row_is_new(monkeypatch):
    # find_one_and_update returns None -> no prior doc -> we own this payout.
    db = _fake_db(None)
    monkeypatch.setattr(mongo, "db", db)
    assert await claim_reward_payout("m1", "u1", 5, "admin") is True


async def test_claim_returns_false_when_row_exists(monkeypatch):
    # A pre-existing doc (already paid, or a crashed prior run) -> skip.
    db = _fake_db({"_id": "m1:u1", "paid": True})
    monkeypatch.setattr(mongo, "db", db)
    assert await claim_reward_payout("m1", "u1", 5, "admin") is False


async def test_claim_writes_source_into_setoninsert(monkeypatch):
    db = _fake_db(None)
    monkeypatch.setattr(mongo, "db", db)

    await claim_reward_payout("m1", "u1", 5, "admin", source="poll")

    _, update = db.reward_payouts.find_one_and_update.call_args.args
    assert update["$setOnInsert"]["source"] == "poll"


async def test_claim_source_defaults_to_event(monkeypatch):
    db = _fake_db(None)
    monkeypatch.setattr(mongo, "db", db)

    await claim_reward_payout("m1", "u1", 5, "admin")

    _, update = db.reward_payouts.find_one_and_update.call_args.args
    assert update["$setOnInsert"]["source"] == "event"


# --- poll payout loop skip behavior ---


def _voter(uid):
    v = MagicMock()
    v.id = uid
    return v


async def test_poll_loop_skips_already_claimed_voter(monkeypatch):
    # Voter u2 was already claimed by a prior (crashed) run; u1 and u3 are fresh.
    # A re-run must pay only u1 and u3, never u2, and report skipped=1.
    async def fake_claim(mid, uid, amount, admin, source="event"):
        return uid != "u2"

    increment = AsyncMock()
    mark_paid = AsyncMock()
    mark_processed = AsyncMock()

    monkeypatch.setattr(
        "features.event.is_poll_reward_processed", AsyncMock(return_value=False)
    )
    monkeypatch.setattr("features.event.claim_reward_payout", fake_claim)
    monkeypatch.setattr("features.event.increment_user_balance", increment)
    monkeypatch.setattr("features.event.mark_reward_paid", mark_paid)
    monkeypatch.setattr("features.event.mark_poll_reward_processed", mark_processed)

    original_msg = MagicMock()
    original_msg.id = 999
    original_msg.add_reaction = AsyncMock()

    voters = [_voter("u1"), _voter("u2"), _voter("u3")]
    view = PollPayoutConfirmView(
        original_msg, voters, 5, "Option A", MagicMock(id="admin")
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.user = MagicMock()
    interaction.user.id = "admin"
    interaction.message = MagicMock()
    interaction.message.embeds = [discord.Embed(title="Confirm?")]
    interaction.edit_original_response = AsyncMock()

    await view.confirm.callback(interaction)

    # Only the two unclaimed voters were paid.
    paid_ids = {call.args[0] for call in increment.await_args_list}
    assert paid_ids == {"u1", "u3"}
    assert increment.await_count == 2
    assert mark_paid.await_count == 2

    # Whole-message gate still written after the loop.
    mark_processed.assert_awaited_once()

    # Summary reflects 2 paid + 1 skipped.
    summary = interaction.message.embeds[0].fields[0].value
    assert "**2** voters" in summary
    assert "Skipped **1**" in summary
