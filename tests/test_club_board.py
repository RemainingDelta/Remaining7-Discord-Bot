"""Tests for the club-list board (overview + club stat embeds) in features/clubs.py (#618)."""

import itertools
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from features.config import CLUB_LIST_CHANNEL_ID

# Keyed by channel so DEV and PROD, which share one database, never clash.
BOARD_KEY = f"club_list_message_ids:{CLUB_LIST_CHANNEL_ID}"

MAX_EMBED_CHARS = 6000


def _snapshot(trophies, **extra):
    snap = {
        "trophies": trophies,
        "required_trophies": 100_000,
        "member_count": 30,
        "president": "Prez",
        "vice_presidents": 6,
        "seniors": 18,
        "min_member_trophies": 99_400,
        "max_member_trophies": 252_900,
        "country_rank": None,
        "global_rank": None,
    }
    snap.update(extra)
    return snap


def _club(tag, name, trophies, country=None, ranked=None, **snap):
    return {
        "_id": tag,
        "name": name,
        "country_code": country,
        "snapshot": _snapshot(trophies, **snap) if trophies is not None else None,
        "ranked": ranked,
        "fetched_at": None,
        "failing_since": None,
    }


def _ranked(low, high, tiers):
    return {
        "min_rank": 4,
        "min_rank_name": low,
        "max_rank": 17,
        "max_rank_name": high,
        "tier_counts": tiers,
        "players_counted": sum(tiers.values()),
    }


def _text(embed: discord.Embed) -> str:
    parts = [embed.title or "", embed.description or "", embed.footer.text or ""]
    for field in embed.fields:
        parts += [field.name, field.value]
    return "\n".join(parts)


def _embed_chars(embed: discord.Embed) -> int:
    return len(embed)


# --- Club embeds ---


def test_club_embeds_are_always_six_messages():
    from features.clubs import CLUB_MESSAGES, build_club_embeds

    for count in (1, 7, 45, 50):
        clubs = [_club(f"#T{i}", f"Club {i}", 1_000_000 + i) for i in range(count)]
        assert len(build_club_embeds(clubs)) == CLUB_MESSAGES == 6


def test_clubs_appear_in_descending_trophy_order():
    from features.clubs import build_club_embeds

    clubs = [
        _club("#A", "Low", 1_000_000),
        _club("#B", "High", 6_000_000),
        _club("#C", "Mid", 3_000_000),
    ]
    names = [f.name for e in build_club_embeds(clubs) for f in e.fields]
    assert [n for n in names if n in ("Low", "High", "Mid")] == ["High", "Mid", "Low"]


def test_45_clubs_spread_evenly_and_all_shown_once():
    from features.clubs import build_club_embeds

    clubs = [_club(f"#T{i}", f"Club {i}", 1_000_000 + i) for i in range(45)]
    embeds = build_club_embeds(clubs)
    sizes = [len(e.fields) for e in embeds]
    assert sum(sizes) == 45
    assert max(sizes) - min(sizes) <= 1
    names = [f.name for e in embeds for f in e.fields]
    assert len(set(names)) == 45


def test_club_card_shows_stats():
    from features.clubs import build_club_embeds

    club = _club(
        "#A",
        "7 Dwarves",
        6_072_652,
        country="US",
        country_rank=3,
        global_rank=10,
        president="R7 | SPARTAN",
        ranked=_ranked("SILVER I", "MASTERS II", {"SILVER": 20, "MASTERS": 1}),
    )
    field = build_club_embeds([club])[0].fields[0]
    assert field.name == "7 Dwarves"
    for expected in (
        "R7 | SPARTAN",
        "6,072,652",
        "3 in 🇺🇸",
        "10",
        "99.4k",
        "252.9k",
        "100,000",
        "30/30",
        "Silver I",
        "Masters II",
    ):
        assert expected in field.value, expected
    assert "6" in field.value and "18" in field.value


def test_unranked_club_shows_not_ranked():
    from features.clubs import build_club_embeds

    field = build_club_embeds([_club("#A", "Liars", 2_754_750)])[0].fields[0]
    assert "Not Ranked" in field.value


def test_globally_ranked_club_without_country_rank_shows_global_only():
    from features.clubs import build_club_embeds

    field = build_club_embeds([_club("#A", "X", 5_000_000, global_rank=12)])[0].fields[
        0
    ]
    assert "Not Ranked" not in field.value
    assert "12" in field.value


def test_club_without_ranked_data_shows_no_ranked_range():
    from features.clubs import build_club_embeds

    field = build_club_embeds([_club("#A", "X", 1_000_000, ranked=None)])[0].fields[0]
    assert " I -" not in field.value and "Silver" not in field.value


def test_club_not_fetched_yet_is_still_listed():
    from features.clubs import build_club_embeds

    field = build_club_embeds([_club("#A", "New Club", None)])[0].fields[0]
    assert field.name == "New Club"
    assert "not fetched yet" in field.value.lower()


def test_fifty_long_named_clubs_fit_discord_limits():
    from features.clubs import build_club_embeds

    clubs = [
        _club(
            f"#T{i:02d}",
            "W" * 32,
            9_999_999 - i,
            country="US",
            country_rank=200,
            global_rank=200,
            president="P" * 32,
            ranked=_ranked("LEGENDARY III", "LEGENDARY III", {"LEGENDARY": 30}),
        )
        for i in range(50)
    ]
    for embed in build_club_embeds(clubs):
        assert _embed_chars(embed) <= MAX_EMBED_CHARS
        assert len(embed.fields) <= 25
        assert all(len(f.value) <= 1024 and len(f.name) <= 256 for f in embed.fields)


def test_club_embeds_carry_disclaimer_and_update_note():
    from features.brawl.commands import SUPERCELL_DISCLAIMER
    from features.clubs import build_club_embeds

    last = build_club_embeds([_club("#A", "X", 1)])[-1]
    assert SUPERCELL_DISCLAIMER in last.footer.text
    assert "30 minutes" in last.footer.text


# --- Overview ---


def test_overview_totals_and_averages():
    from features.clubs import build_overview_embed

    clubs = [
        _club("#A", "A", 6_000_000, member_count=30, vice_presidents=6, seniors=18),
        _club(
            "#B",
            "B",
            2_000_000,
            member_count=20,
            vice_presidents=2,
            seniors=4,
            required_trophies=50_000,
        ),
    ]
    text = _text(build_overview_embed(clubs))
    assert "8,000,000" in text  # total trophies
    assert "4,000,000" in text  # average trophies
    assert "50/60" in text  # members vs capacity
    assert "75,000" in text  # average required
    assert "25/30" in text  # average members


def test_overview_ranked_distribution_adds_to_100():
    from features.clubs import build_overview_embed

    clubs = [
        _club(
            "#A", "A", 1, ranked=_ranked("SILVER I", "GOLD I", {"SILVER": 2, "GOLD": 1})
        ),
        _club(
            "#B",
            "B",
            1,
            ranked=_ranked("SILVER I", "MYTHIC I", {"SILVER": 1, "MYTHIC": 2}),
        ),
    ]
    embed = build_overview_embed(clubs)
    dist = next(f.value for f in embed.fields if "Ranked" in f.name)
    percents = [int(p) for p in __import__("re").findall(r"(\d+)%", dist)]
    assert 98 <= sum(percents) <= 102
    assert dist.index("Silver") < dist.index("Gold") < dist.index("Mythic")


def test_overview_skips_clubs_without_snapshot_in_averages():
    from features.clubs import build_overview_embed

    clubs = [_club("#A", "A", 4_000_000), _club("#B", "B", None)]
    fields = {f.name: f.value for f in build_overview_embed(clubs).fields}
    assert fields["Average Trophies"].endswith("4,000,000")
    assert fields["Total Clubs"].endswith("2")


# --- Board messages: posted once, then edited in place ---


class _FakeChannel:
    def __init__(self):
        self.messages = {}
        self._ids = itertools.count(1000)
        self.sends = 0

    async def send(self, **kwargs):
        self.sends += 1
        msg = MagicMock(spec=discord.Message)
        msg.id = next(self._ids)
        msg.kwargs = kwargs
        msg.edits = 0

        async def edit(**kw):
            msg.kwargs = kw
            msg.edits += 1

        msg.edit = AsyncMock(side_effect=edit)
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise discord.NotFound(MagicMock(status=404, reason="Not Found"), "gone")
        return self.messages[message_id]


@pytest.fixture
def board(mock_bot):
    from features.clubs import ClubTracking

    channel = _FakeChannel()
    settings = {}

    async def get_setting(key, default=None):
        return settings.get(key, default)

    async def set_setting(key, value):
        settings[key] = value

    clubs = [_club(f"#T{i}", f"Club {i}", 1_000_000 + i) for i in range(45)]
    mock_bot.get_channel = MagicMock(
        side_effect=lambda cid: channel if cid == CLUB_LIST_CHANNEL_ID else None
    )
    with (
        patch("features.clubs.get_setting", new=get_setting),
        patch("features.clubs.set_setting", new=set_setting),
        patch(
            "features.clubs.list_tracked_clubs", new=AsyncMock(return_value=clubs)
        ) as lst,
    ):
        yield MagicMock(
            cog=ClubTracking(mock_bot),
            bot=mock_bot,
            channel=channel,
            settings=settings,
            clubs=clubs,
            list=lst,
        )


def _stored_ids(board):
    return [int(i) for i in json.loads(board.settings[BOARD_KEY])]


async def test_first_run_posts_exactly_seven_messages_in_order(board):
    await board.cog.update_club_board()
    assert board.channel.sends == 7
    ids = _stored_ids(board)
    assert ids == sorted(ids) and len(ids) == 7
    first = board.channel.messages[ids[0]]
    assert "Overview" in first.kwargs["embed"].title


async def test_refreshes_add_remove_and_restart_reuse_the_same_messages(board):
    from features.clubs import ClubTracking

    await board.cog.update_club_board()
    first_ids = _stored_ids(board)
    for _ in range(3):
        await board.cog.update_club_board()
    board.list.return_value = board.clubs + [_club("#NEW", "New Club", 9_000_000)]
    await board.cog.update_club_board()
    board.list.return_value = board.clubs[:-5]
    await board.cog.update_club_board()
    restarted = ClubTracking(board.bot)
    await restarted.update_club_board()
    assert board.channel.sends == 7
    assert _stored_ids(board) == first_ids
    assert all(board.channel.messages[i].edits == 6 for i in first_ids)


async def test_edit_shows_new_data(board):
    await board.cog.update_club_board()
    board.list.return_value = [_club("#NEW", "Fresh Club", 9_000_000)]
    await board.cog.update_club_board()
    first_club_msg = board.channel.messages[_stored_ids(board)[1]]
    assert first_club_msg.kwargs["embed"].fields[0].name == "Fresh Club"


async def test_deleted_message_is_the_only_one_replaced(board):
    await board.cog.update_club_board()
    ids = _stored_ids(board)
    del board.channel.messages[ids[3]]
    await board.cog.update_club_board()
    new_ids = _stored_ids(board)
    assert board.channel.sends == 8
    assert [a == b for a, b in zip(ids, new_ids)] == [
        True,
        True,
        True,
        False,
        True,
        True,
        True,
    ]


async def test_missing_channel_does_nothing(board):
    board.bot.get_channel = MagicMock(return_value=None)
    await board.cog.update_club_board()
    assert board.channel.sends == 0
    assert BOARD_KEY not in board.settings


async def test_refresh_completion_updates_the_board(board):
    board.cog.update_club_board = AsyncMock()
    await board.cog.on_refresh_complete()
    board.cog.update_club_board.assert_awaited_once()


async def test_edit_failure_keeps_message_and_retries_later(board):
    await board.cog.update_club_board()
    ids = _stored_ids(board)
    msg = board.channel.messages[ids[2]]
    msg.edit.side_effect = discord.HTTPException(
        MagicMock(status=500, reason="err"), "boom"
    )
    await board.cog.update_club_board()
    assert _stored_ids(board) == ids
    assert board.channel.sends == 7
