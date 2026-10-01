"""Tests for the Supply Drop Leaderboard (issue #407).

Derived from the issue's Acceptance Criteria:

* A user can access a supply drop leaderboard.
* The leaderboard displays users sorted by their total supply drops.
* The leaderboard clearly shows counts for 'Normal Drops' and 'Booster Drops'
  for each user.
* The system correctly tracks and updates supply drop counts for users.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

import features.economy as economy
from features.config import BOOSTER_CHANNEL_ID, GENERAL_CHANNEL_ID
from features.economy import (
    DropClaimButton,
    Economy,
    _format_supply_drop_line,
)


# --- AC: shows 'Normal Drops' and 'Booster Drops' counts, plus the total ---


def test_supply_drop_line_shows_normal_booster_and_total():
    line = _format_supply_drop_line(
        1, {"_id": "42", "supply_drops_normal": 3, "supply_drops_booster": 2}
    )
    # Podium medal, mention, a total, and both per-type counts.
    assert line == "🥇 <@42> - 📦 **5** total (🪂 3 Normal | 🚀 2 Booster)"


def test_supply_drop_line_numbered_after_the_podium():
    line = _format_supply_drop_line(
        4, {"_id": "7", "supply_drops_normal": 10, "supply_drops_booster": 0}
    )
    assert line == "**#4** <@7> - 📦 **10** total (🪂 10 Normal | 🚀 0 Booster)"


def test_supply_drop_line_survives_doc_without_counts():
    # A user doc that predates drop tracking has neither field; render as zeroes
    # rather than raising KeyError, matching the other board helpers.
    line = _format_supply_drop_line(2, {"_id": "42"})
    assert line == "🥈 <@42> - 📦 **0** total (🪂 0 Normal | 🚀 0 Booster)"


def test_supply_drop_line_total_is_the_sum_of_the_two_counts():
    line = _format_supply_drop_line(
        5, {"_id": "9", "supply_drops_normal": 4, "supply_drops_booster": 6}
    )
    assert "📦 **10** total" in line


# --- AC: the leaderboard is sorted by total supply drops ---


async def test_get_supply_drops_page_sorts_by_total_descending(monkeypatch):
    from database import mongo

    fake_db, cursor = _fake_users_db(["doc"])
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.get_supply_drops_page(20, 10) == ["doc"]

    # Only users who have actually claimed a drop appear on the board.
    assert fake_db.users.find.call_args.args[0] == {"supply_drops_total": {"$gt": 0}}
    cursor.sort.assert_called_once_with("supply_drops_total", -1)
    cursor.skip.assert_called_once_with(20)
    cursor.limit.assert_called_once_with(10)


async def test_get_supply_drops_total_counts_the_paged_population(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.count_documents = AsyncMock(return_value=4)
    monkeypatch.setattr(mongo, "db", fake_db)

    # The page bounds must count exactly the users the pages walk over.
    assert await mongo.get_supply_drops_total() == 4
    assert fake_db.users.count_documents.await_args.args[0] == {
        "supply_drops_total": {"$gt": 0}
    }


async def test_get_user_supply_drop_rank_counts_users_with_a_higher_total(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.find_one = AsyncMock(
        return_value={"_id": "42", "supply_drops_total": 5}
    )
    fake_db.users.count_documents = AsyncMock(return_value=2)
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.get_user_supply_drop_rank("42") == 3  # 2 ahead -> rank 3
    assert fake_db.users.count_documents.await_args.args[0] == {
        "supply_drops_total": {"$gt": 5}
    }


async def test_supply_drop_page_and_total_and_rank_are_safe_without_a_db(monkeypatch):
    from database import mongo

    monkeypatch.setattr(mongo, "db", None)
    assert await mongo.get_supply_drops_page(0, 10) == []
    assert await mongo.get_supply_drops_total() == 0
    assert await mongo.get_user_supply_drop_rank("42") == 0


# --- AC: the system correctly tracks and updates supply drop counts ---


async def test_increment_supply_drop_count_bumps_normal_field(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock()
    monkeypatch.setattr(mongo, "db", fake_db)

    await mongo.increment_supply_drop_count("u1", is_booster=False)

    filt, update = fake_db.users.update_one.await_args.args
    assert filt == {"_id": "u1"}
    assert update["$inc"]["supply_drops_normal"] == 1
    assert update["$inc"]["supply_drops_total"] == 1
    assert "supply_drops_booster" not in update["$inc"]
    assert fake_db.users.update_one.await_args.kwargs["upsert"] is True


async def test_increment_supply_drop_count_bumps_booster_field(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.update_one = AsyncMock()
    monkeypatch.setattr(mongo, "db", fake_db)

    await mongo.increment_supply_drop_count("u1", is_booster=True)

    _, update = fake_db.users.update_one.await_args.args
    assert update["$inc"]["supply_drops_booster"] == 1
    assert update["$inc"]["supply_drops_total"] == 1
    assert "supply_drops_normal" not in update["$inc"]


async def test_claiming_a_general_drop_tracks_a_normal_drop(monkeypatch):
    tracker = AsyncMock()
    monkeypatch.setattr(economy, "increment_supply_drop_count", tracker)

    await _claim_drop_in_channel(monkeypatch, channel_id=GENERAL_CHANNEL_ID)

    tracker.assert_awaited_once()
    assert tracker.await_args.kwargs.get("is_booster", False) is False


async def test_claiming_a_booster_drop_tracks_a_booster_drop(monkeypatch):
    tracker = AsyncMock()
    monkeypatch.setattr(economy, "increment_supply_drop_count", tracker)

    await _claim_drop_in_channel(monkeypatch, channel_id=BOOSTER_CHANNEL_ID)

    tracker.assert_awaited_once()
    assert tracker.await_args.kwargs.get("is_booster") is True


async def test_a_lost_claim_does_not_track_a_supply_drop(monkeypatch):
    # Two near-simultaneous clicks: only the winner (claim_drop True) should be
    # counted. A loser must not inflate the board.
    tracker = AsyncMock()
    monkeypatch.setattr(economy, "increment_supply_drop_count", tracker)

    await _claim_drop_in_channel(
        monkeypatch, channel_id=GENERAL_CHANNEL_ID, won_claim=False
    )

    tracker.assert_not_awaited()


# --- AC: a user can access the supply drop leaderboard ---


def test_leaderboard_group_exposes_a_supply_drops_subcommand():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = Economy.__new__(Economy)  # skip __init__ so task loops don't start

    for command in cog.get_app_commands():
        bot.tree.add_command(command)

    group = bot.tree.get_command("leaderboard")
    assert isinstance(group, discord.app_commands.Group)
    assert "supply-drops" in {sub.name for sub in group.commands}


# --- helpers ---


def _fake_users_db(page):
    """A users collection whose find() returns a chainable cursor."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=page)

    fake_db = MagicMock()
    fake_db.users.find = MagicMock(return_value=cursor)
    return fake_db, cursor


async def _claim_drop_in_channel(monkeypatch, *, channel_id, won_claim=True):
    """Drive DropClaimButton.callback for a non-staff claimer in a channel."""
    monkeypatch.setattr(economy, "claim_drop", AsyncMock(return_value=won_claim))
    monkeypatch.setattr(economy, "increment_user_balance", AsyncMock())
    monkeypatch.setattr(economy, "get_setting", AsyncMock(return_value=""))
    monkeypatch.setattr(economy, "set_setting", AsyncMock())

    button = DropClaimButton(50)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 987654321
    interaction.user.display_name = "TestUser"
    interaction.user.roles = []  # not staff

    message = MagicMock()
    message.id = 424242
    message.channel.id = channel_id
    embed = discord.Embed(title="🪂 Supply Drop")
    message.embeds = [embed]
    interaction.message = message

    await button.callback(interaction)
