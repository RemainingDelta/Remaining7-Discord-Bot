"""Tests for the club-list board (overview + club stat embeds) in features/clubs.py (#618)."""

import itertools
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from features.config import CLUB_EMOJIS, CLUB_LIST_CHANNEL_ID, CLUB_RANK_EMOJIS

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


def _card_name(field) -> str:
    """The club name from a card's first line, '**[Name](link)**'."""
    match = re.match(r"\*\*\[(.+?)\]\(", field.value)
    assert match, field.value
    return match.group(1)


# --- Club embeds ---


def test_club_stats_shows_only_the_top_nine_by_trophies():
    from features.clubs import CLUBS_ON_BOARD, build_club_stats_embed

    clubs = [_club(f"#T{i}", f"Club {i}", 1_000_000 + i) for i in range(45)]
    names = [_card_name(f) for f in build_club_stats_embed(clubs).fields]
    assert CLUBS_ON_BOARD == 9
    assert names == [f"Club {i}" for i in range(44, 35, -1)]


def test_clubs_appear_in_descending_trophy_order():
    from features.clubs import build_club_stats_embed

    clubs = [
        _club("#A", "Low", 1_000_000),
        _club("#B", "High", 6_000_000),
        _club("#C", "Mid", 3_000_000),
    ]
    names = [_card_name(f) for f in build_club_stats_embed(clubs).fields]
    assert names == ["High", "Mid", "Low"]


def test_fewer_than_nine_clubs_are_all_shown():
    from features.clubs import build_club_stats_embed

    clubs = [_club(f"#T{i}", f"Club {i}", i) for i in range(5)]
    assert len(build_club_stats_embed(clubs).fields) == 5


def test_no_clubs_shows_a_placeholder_line():
    from features.clubs import build_club_stats_embed

    embed = build_club_stats_embed([])
    assert not embed.fields
    assert "no clubs" in embed.description.lower()


def test_club_card_shows_stats():
    from features.clubs import build_club_stats_embed

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
    field = build_club_stats_embed([club]).fields[0]
    assert _card_name(field) == "7 Dwarves"
    for expected in (
        "R7 | SPARTAN",
        "`6,072,652`",
        "`3` in 🇺🇸",
        "`10`",
        "`99.4k`",
        "`252.9k`",
        "`100,000`",
        "`30/30`",
        f"{CLUB_RANK_EMOJIS['SILVER']}`I` - {CLUB_RANK_EMOJIS['MASTERS']}`II`",
        "`6`",
        "`18`",
    ):
        assert expected in field.value, expected


def test_unranked_club_shows_not_ranked():
    from features.clubs import build_club_stats_embed

    field = build_club_stats_embed([_club("#A", "Liars", 2_754_750)]).fields[0]
    assert "Not Ranked" in field.value


def test_globally_ranked_club_without_country_rank_shows_global_only():
    from features.clubs import build_club_stats_embed

    field = build_club_stats_embed(
        [_club("#A", "X", 5_000_000, global_rank=12)]
    ).fields[0]
    assert "Not Ranked" not in field.value
    assert "12" in field.value


def test_club_without_ranked_data_shows_no_ranked_range():
    from features.clubs import build_club_stats_embed

    field = build_club_stats_embed([_club("#A", "X", 1_000_000, ranked=None)]).fields[0]
    assert " I -" not in field.value and "Silver" not in field.value


def test_club_not_fetched_yet_is_still_listed():
    from features.clubs import build_club_stats_embed

    field = build_club_stats_embed([_club("#A", "New Club", None)]).fields[0]
    assert _card_name(field) == "New Club"
    assert "not fetched yet" in field.value.lower()


def test_fifty_long_named_clubs_fit_discord_limits():
    from features.clubs import build_club_stats_embed

    clubs = [
        _club(
            f"#T{i:02d}",
            "W" * 32,
            9_999_999 - i,
            country="US",
            country_rank=200,
            global_rank=200,
            president="P" * 32,
            president_tag="#" + "Q" * 10,
            ranked=_ranked("LEGENDARY III", "LEGENDARY III", {"LEGENDARY": 30}),
        )
        for i in range(50)
    ]
    embed = build_club_stats_embed(clubs)
    assert _embed_chars(embed) <= MAX_EMBED_CHARS
    assert len(embed.fields) == 9
    assert all(len(f.value) <= 1024 and len(f.name) <= 256 for f in embed.fields)


def test_club_name_links_to_brawlify():
    from features.clubs import build_club_stats_embed

    field = build_club_stats_embed([_club("#2YYJJV9PC", "7 Dwarves", 1)]).fields[0]
    first_line = field.value.splitlines()[0]
    assert first_line == "**[7 Dwarves](https://brawlify.com/club/2YYJJV9PC)**"


def test_club_name_shows_on_card_not_field_title():
    from features.clubs import build_club_stats_embed

    field = build_club_stats_embed([_club("#A", "7 Dwarves", 1)]).fields[0]
    assert field.name.strip("\u200b") == ""


def test_president_links_to_brawlify_player():
    from features.clubs import build_club_stats_embed

    club = _club("#A", "X", 1, president="R7 | SPARTAN", president_tag="#QQ0Y9PC")
    value = build_club_stats_embed([club]).fields[0].value
    assert "[R7 | SPARTAN](https://brawlify.com/player/QQ0Y9PC)" in value


def test_president_without_tag_is_not_linked():
    from features.clubs import build_club_stats_embed

    club = _club("#A", "X", 1, president="Old Prez")
    value = build_club_stats_embed([club]).fields[0].value
    president_line = next(line for line in value.splitlines() if "Old Prez" in line)
    assert "brawlify.com/player" not in president_line


def test_names_show_as_typed_without_backslashes():
    # Discord doesn't apply backslash escapes inside link text, so a name like
    # "( ◡̀_◡́)" must be sent as-is or the backslash shows up.
    from features.clubs import build_club_stats_embed

    club = _club("#A", "Toxic_| x", 1, president="( ◡̀_◡́)Panda", president_tag="#P1")
    value = build_club_stats_embed([club]).fields[0].value
    assert "\\" not in value
    assert "**[Toxic_| x](https://brawlify.com/club/A)**" in value
    assert "[( ◡̀_◡́)Panda](https://brawlify.com/player/P1)" in value


def test_brackets_in_names_cannot_break_links():
    from features.clubs import build_club_stats_embed

    club = _club(
        "#A", "[7] Club", 1, president="[evil](https://x.y)", president_tag="#P1"
    )
    value = build_club_stats_embed([club]).fields[0].value
    first_line = value.splitlines()[0]
    assert first_line == "**[［7］ Club](https://brawlify.com/club/A)**"
    assert "[evil](https://x.y)" not in value
    assert "](https://brawlify.com/player/P1)" in value


def test_ranked_line_uses_tier_icons_for_every_tier():
    from features.clubs import build_club_stats_embed

    from features.config import CLUB_RANK_EMOJIS

    assert set(CLUB_RANK_EMOJIS) == {
        "BRONZE",
        "SILVER",
        "GOLD",
        "DIAMOND",
        "MYTHIC",
        "LEGENDARY",
        "MASTERS",
        "PRO",
    }
    for tier, icon in CLUB_RANK_EMOJIS.items():
        club = _club(
            "#A", "X", 1, ranked=_ranked(f"{tier} III", f"{tier} I", {tier: 1})
        )
        value = build_club_stats_embed([club]).fields[0].value
        assert f"{icon}`III` - {icon}`I`" in value, tier


def test_board_footer_is_short_update_note_without_disclaimer():
    from features.clubs import build_club_stats_embed, build_overview_embed

    clubs = [_club(f"#T{i}", f"C{i}", i) for i in range(10)]
    for embed in (build_club_stats_embed(clubs), build_overview_embed(clubs)):
        assert embed.footer.text == "Updating every 30 minutes. Posted at"
        assert "Supercell" not in embed.footer.text
        assert embed.timestamp is not None


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
    assert "`8,000,000`" in text  # total trophies
    assert "`4,000,000`" in text  # average trophies
    assert "`50/60`" in text  # members vs capacity
    assert "`75,000`" in text  # average required
    assert "`25/30`" in text  # average members


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
    # Icons in tier order, like BrawlTools: Silver, then Gold, then Mythic.
    icons = CLUB_RANK_EMOJIS
    assert (
        dist.index(icons["SILVER"])
        < dist.index(icons["GOLD"])
        < dist.index(icons["MYTHIC"])
    )


def test_overview_skips_clubs_without_snapshot_in_averages():
    from features.clubs import build_overview_embed

    clubs = [_club("#A", "A", 4_000_000), _club("#B", "B", None)]
    fields = {f.name: f.value for f in build_overview_embed(clubs).fields}
    assert fields["Average Trophies"].endswith("`4,000,000`")
    assert fields["Total Clubs"].endswith("`2`")


# --- Board messages: posted once, then edited in place ---


class _FakeChannel:
    def __init__(self):
        self.messages = {}
        self._ids = itertools.count(1000)
        self.sends = 0
        self.deleted = []

    async def send(self, **kwargs):
        self.sends += 1
        msg = MagicMock(spec=discord.Message)
        msg.id = next(self._ids)
        msg.kwargs = kwargs
        msg.edits = 0

        async def edit(**kw):
            msg.kwargs = kw
            msg.edits += 1

        async def delete():
            self.messages.pop(msg.id, None)
            self.deleted.append(msg.id)

        msg.edit = AsyncMock(side_effect=edit)
        msg.delete = AsyncMock(side_effect=delete)
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


async def test_first_run_posts_exactly_two_messages_in_order(board):
    await board.cog.update_club_board()
    assert board.channel.sends == 2
    ids = _stored_ids(board)
    assert ids == sorted(ids) and len(ids) == 2
    second = board.channel.messages[ids[1]]
    assert "Club Stats" in second.kwargs["embed"].title
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
    assert board.channel.sends == 2
    assert _stored_ids(board) == first_ids
    assert all(board.channel.messages[i].edits == 6 for i in first_ids)


async def test_edit_shows_new_data(board):
    await board.cog.update_club_board()
    board.list.return_value = [_club("#NEW", "Fresh Club", 9_000_000)]
    await board.cog.update_club_board()
    first_club_msg = board.channel.messages[_stored_ids(board)[1]]
    assert _card_name(first_club_msg.kwargs["embed"].fields[0]) == "Fresh Club"


async def test_deleted_message_is_the_only_one_replaced(board):
    await board.cog.update_club_board()
    ids = _stored_ids(board)
    del board.channel.messages[ids[1]]
    await board.cog.update_club_board()
    new_ids = _stored_ids(board)
    assert board.channel.sends == 3
    assert new_ids[0] == ids[0] and new_ids[1] != ids[1]


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
    msg = board.channel.messages[ids[1]]
    msg.edit.side_effect = discord.HTTPException(
        MagicMock(status=500, reason="err"), "boom"
    )
    await board.cog.update_club_board()
    assert _stored_ids(board) == ids
    assert board.channel.sends == 2


async def test_old_extra_board_messages_are_deleted_once(board):
    # The earlier layout posted 7 messages; the first update on the new layout
    # keeps the first 2, deletes the rest, and saves only 2 IDs.
    old = [await board.channel.send(embed=None) for _ in range(7)]
    board.settings[BOARD_KEY] = json.dumps([str(m.id) for m in old])
    sends_before = board.channel.sends
    await board.cog.update_club_board()
    assert _stored_ids(board) == [old[0].id, old[1].id]
    assert sorted(board.channel.deleted) == [m.id for m in old[2:]]
    assert board.channel.sends == sends_before
    assert old[0].edits == 1 and old[1].edits == 1
    await board.cog.update_club_board()
    assert len(board.channel.deleted) == 5


async def test_already_deleted_extra_messages_are_ignored(board):
    old = [await board.channel.send(embed=None) for _ in range(4)]
    board.settings[BOARD_KEY] = json.dumps([str(m.id) for m in old])
    del board.channel.messages[old[3].id]
    await board.cog.update_club_board()
    assert _stored_ids(board) == [old[0].id, old[1].id]


# --- Custom emoji (uploaded as application emoji on each bot) ---

CUSTOM_EMOJI = re.compile(r"^<:[A-Za-z0-9_]{2,32}:\d{17,20}>$")


def test_board_icons_are_custom_emoji_except_globe():
    for key, value in CLUB_EMOJIS.items():
        if key == "global":
            assert value == "🌍"  # BrawlTools uses the standard globe too
        else:
            assert CUSTOM_EMOJI.match(value), (key, value)


def test_rank_icons_are_custom_emoji():
    for tier, value in CLUB_RANK_EMOJIS.items():
        assert CUSTOM_EMOJI.match(value), (tier, value)


def test_board_uses_brawltools_trophy_split():
    # Total trophies use the trophy-with-club icon; range and averages the plain one.
    assert "trophy_with_club" in CLUB_EMOJIS["club_trophies"]
    assert ":trophy:" in CLUB_EMOJIS["trophy"]
    assert "grayscale_trophy" in CLUB_EMOJIS["required"]
    assert "lock" in CLUB_EMOJIS["type"] and "city" in CLUB_EMOJIS["region"]


def test_card_and_overview_use_matching_trophy_icons():
    from features.clubs import build_club_stats_embed, build_overview_embed

    club = _club("#A", "X", 6_000_000)
    lines = build_club_stats_embed([club]).fields[0].value.splitlines()
    assert lines[2].startswith(CLUB_EMOJIS["club_trophies"])  # 🏆 total
    range_line = next(line for line in lines if "k` - `" in line)
    assert range_line.startswith(CLUB_EMOJIS["trophy"])
    fields = {f.name: f.value for f in build_overview_embed([club]).fields}
    assert fields["Total Trophies"].startswith(CLUB_EMOJIS["club_trophies"])
    assert fields["Average Trophies"].startswith(CLUB_EMOJIS["trophy"])


# --- Compact overview, like BrawlTools ---


def _distribution(clubs):
    from features.clubs import build_overview_embed

    embed = build_overview_embed(clubs)
    return next(f for f in embed.fields if "Ranked Distribution" in f.name)


def test_overview_keeps_a_three_column_grid():
    from features.clubs import build_overview_embed

    embed = build_overview_embed([_club("#A", "A", 1)])
    inline = [f for f in embed.fields if f.inline]
    assert len(inline) % 3 == 0
    assert (
        inline[-1].name.strip("\u200b") == "" and inline[-1].value.strip("\u200b") == ""
    )


def test_ranked_distribution_has_plain_title_and_three_tiers_per_line():
    tiers = {
        "BRONZE": 7,
        "SILVER": 63,
        "GOLD": 10,
        "DIAMOND": 7,
        "MYTHIC": 7,
        "LEGENDARY": 6,
    }
    field = _distribution(
        [_club("#A", "A", 1, ranked=_ranked("BRONZE I", "LEGENDARY I", tiers))]
    )
    assert field.name == "Ranked Distribution"
    lines = field.value.splitlines()
    assert len(lines) == 2
    assert all(line.count("%") == 3 for line in lines)
    assert "·" not in field.value


def test_ranked_distribution_skips_tiers_that_round_to_zero():
    tiers = {"SILVER": 300, "MASTERS": 1}
    field = _distribution(
        [_club("#A", "A", 1, ranked=_ranked("SILVER I", "MASTERS I", tiers))]
    )
    assert CLUB_RANK_EMOJIS["MASTERS"] not in field.value
    assert "`0%`" not in field.value


# --- Titles and colors, like BrawlTools ---


def test_overview_title_and_orange_bar():
    from features.clubs import build_overview_embed

    embed = build_overview_embed([_club("#A", "A", 1)])
    assert embed.title == "Overview from Remaining 7 Esports | Overview"
    assert embed.color == discord.Color.orange()


def test_club_stats_title_and_yellow_bar():
    from features.clubs import build_club_stats_embed

    embed = build_club_stats_embed([_club("#A", "A", 1)])
    assert embed.title == "Overview from Remaining 7 Esports | Club Stats"
    assert embed.color == discord.Color.gold()
