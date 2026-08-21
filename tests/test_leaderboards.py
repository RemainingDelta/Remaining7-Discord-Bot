"""Tests for the leaderboard formatting helpers and page queries.

The two leaderboards used to build their rows inside async discord.ui.View
methods, which needed both Discord and Mongo to exercise — so none of it was
tested, and the token and level boards silently drifted apart. These cover the
extracted pure helpers plus the query shapes behind them.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from features.economy import (
    Economy,
    _format_level_line,
    _format_token_line,
    _leaderboard_footer,
    _max_page,
    _rank_prefix,
)


# --- _rank_prefix ---


def test_rank_prefix_medals_for_top_three():
    assert _rank_prefix(1) == "🥇"
    assert _rank_prefix(2) == "🥈"
    assert _rank_prefix(3) == "🥉"


def test_rank_prefix_is_numbered_from_fourth():
    assert _rank_prefix(4) == "**#4**"
    assert _rank_prefix(27) == "**#27**"


# --- _format_token_line ---


def test_format_token_line_renders_mention_and_balance():
    line = _format_token_line(1, {"_id": "42", "balance": 1500})
    assert line == "🥇 <@42> - 💰 **1500**"


def test_format_token_line_truncates_float_balances():
    # Balances can arrive as floats; they render as whole tokens.
    line = _format_token_line(4, {"_id": "42", "balance": 1500.7})
    assert line == "**#4** <@42> - 💰 **1500**"


def test_format_token_line_survives_doc_without_balance():
    # Regression: get_user_data creates docs holding only _id/currencies/brawlers,
    # so a doc with no `balance` key reaches the leaderboard and used to raise
    # KeyError. It must render as zero instead.
    line = _format_token_line(1, {"_id": "42"})
    assert line == "🥇 <@42> - 💰 **0**"


# --- _format_level_line ---


def test_format_level_line_renders_level_and_exp():
    line = _format_level_line(2, {"_id": "42", "level": 10, "exp": 500})
    assert line == "🥈 <@42> - Level **10** | **500** EXP"


def test_format_level_line_survives_doc_without_level_or_exp():
    # Regression, same cause as the token line above. Defaults match the ones
    # get_leveling_data already applies: level 1, exp 0.
    line = _format_level_line(1, {"_id": "42"})
    assert line == "🥇 <@42> - Level **1** | **0** EXP"


# --- _leaderboard_footer ---


def test_leaderboard_footer_is_one_indexed_with_hash_prefix():
    assert _leaderboard_footer(0, 7) == "Page 1 | Your Rank: #7"
    assert _leaderboard_footer(3, 21) == "Page 4 | Your Rank: #21"


# --- _max_page ---


def test_max_page_partial_and_exact_pages():
    assert _max_page(1, 10) == 0
    assert _max_page(10, 10) == 0
    assert _max_page(11, 10) == 1
    assert _max_page(20, 10) == 1


def test_max_page_clamps_at_zero_when_empty():
    # (0 - 1) // 10 is -1, which would make "page < max_page" nonsense.
    assert _max_page(0, 10) == 0


# --- page queries ---


async def test_get_leaderboard_page_filters_to_docs_with_a_balance(monkeypatch):
    from database import mongo

    fake_db, cursor = _fake_users_db(["doc"])
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.get_leaderboard_page(20, 10) == ["doc"]

    # Field-less docs are excluded rather than rendered as a tail of zeroes.
    assert fake_db.users.find.call_args.args[0] == {"balance": {"$exists": True}}
    cursor.sort.assert_called_once_with("balance", -1)
    cursor.skip.assert_called_once_with(20)
    cursor.limit.assert_called_once_with(10)


async def test_get_levels_page_filters_to_docs_with_a_level(monkeypatch):
    from database import mongo

    fake_db, cursor = _fake_users_db(["doc"])
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.get_levels_page(0, 10) == ["doc"]

    # Without this filter the board pages through users who have no level at
    # all, which is what made "No leveled users yet!" untrue.
    assert fake_db.users.find.call_args.args[0] == {"level": {"$exists": True}}
    # Level first, then exp as the tiebreak.
    cursor.sort.assert_called_once_with([("level", -1), ("exp", -1)])


# --- filtered totals ---


async def test_leaderboard_totals_count_the_same_population_as_the_pages(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.count_documents = AsyncMock(return_value=3)
    monkeypatch.setattr(mongo, "db", fake_db)

    # Page bounds have to count the filtered population; counting every user
    # would let "Next" walk off the end into empty pages.
    assert await mongo.get_leaderboard_total() == 3
    assert fake_db.users.count_documents.await_args.args[0] == {
        "balance": {"$exists": True}
    }

    assert await mongo.get_levels_total() == 3
    assert fake_db.users.count_documents.await_args.args[0] == {
        "level": {"$exists": True}
    }


@pytest.mark.parametrize("helper", ["get_leaderboard_page", "get_levels_page"])
async def test_page_helpers_return_empty_without_a_db(monkeypatch, helper):
    from database import mongo

    monkeypatch.setattr(mongo, "db", None)
    assert await getattr(mongo, helper)(0, 10) == []


@pytest.mark.parametrize("helper", ["get_leaderboard_total", "get_levels_total"])
async def test_total_helpers_return_zero_without_a_db(monkeypatch, helper):
    from database import mongo

    monkeypatch.setattr(mongo, "db", None)
    assert await getattr(mongo, helper)() == 0


# --- get_user_level_rank ---


async def test_get_user_level_rank_counts_higher_level_then_higher_exp(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.find_one = AsyncMock(
        return_value={"_id": "42", "level": 5, "exp": 20}
    )
    fake_db.users.count_documents = AsyncMock(return_value=2)
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.get_user_level_rank("42") == 3  # 2 ahead of you -> rank 3

    assert fake_db.users.count_documents.await_args.args[0] == {
        "$or": [{"level": {"$gt": 5}}, {"level": 5, "exp": {"$gt": 20}}]
    }


async def test_get_user_level_rank_does_not_create_a_user_doc(monkeypatch):
    from database import mongo

    fake_db = MagicMock()
    fake_db.users.find_one = AsyncMock(return_value=None)
    fake_db.users.count_documents = AsyncMock(return_value=0)
    fake_db.users.insert_one = AsyncMock()
    fake_db.users.update_one = AsyncMock()
    monkeypatch.setattr(mongo, "db", fake_db)

    # Regression: this used to route through get_leveling_data -> get_user_data,
    # which *inserts* a doc holding only _id/currencies/brawlers. Viewing the
    # level board therefore minted the very documents that crashed both boards.
    assert await mongo.get_user_level_rank("42") == 1
    fake_db.users.insert_one.assert_not_awaited()
    fake_db.users.update_one.assert_not_awaited()

    # An absent doc is treated as level 1 / exp 0, matching get_leveling_data.
    assert fake_db.users.count_documents.await_args.args[0] == {
        "$or": [{"level": {"$gt": 1}}, {"level": 1, "exp": {"$gt": 0}}]
    }


# --- command tree registration ---


def test_leaderboard_group_exposes_token_and_level_subcommands():
    # main.py wraps every load_extension in one broad try/except, so a duplicate
    # command name does not raise -- it aborts the block and silently drops
    # Economy plus every extension loaded after it. That reads as "half the bot
    # is missing", so register the cog's commands here to catch it in CI.
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = Economy.__new__(Economy)  # skip __init__ so task loops don't start

    for command in cog.get_app_commands():
        bot.tree.add_command(command)  # raises CommandAlreadyRegistered on a dupe

    group = bot.tree.get_command("leaderboard")
    assert isinstance(group, discord.app_commands.Group)
    assert {sub.name for sub in group.commands} == {"token", "level"}


def test_old_flat_leaderboard_commands_are_gone():
    cog = Economy.__new__(Economy)
    names = {command.name for command in cog.get_app_commands()}
    # Both were replaced by the group; leaving /leaderboard behind would collide
    # with the group name at add_cog time.
    assert "levels-leaderboard" not in names
    assert "leaderboard" in names  # now the group, not a plain command


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
