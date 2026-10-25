"""Tests for the "Choose a Club" dropdowns and club detail view (#619)."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from features.config import CLUB_EMOJIS


def _snapshot(trophies, **extra):
    snap = {
        "trophies": trophies,
        "required_trophies": 55_000,
        "member_count": 30,
        "president": "rodvyns",
        "president_tag": "#P9C2LU0",
        "vice_presidents": 1,
        "seniors": 4,
        "min_member_trophies": 55_151,
        "max_member_trophies": 123_995,
        "country_rank": None,
        "global_rank": None,
        "badge_id": 8000035,
        "type": "open",
        "description": "English Speaking | Active Club",
    }
    snap.update(extra)
    return snap


def _club(tag, name, trophies, country="US", **snap):
    return {
        "_id": tag,
        "name": name,
        "country_code": country,
        "snapshot": _snapshot(trophies, **snap) if trophies is not None else None,
        "fetched_at": None,
        "failing_since": None,
    }


def _clubs(count):
    return [_club(f"#T{i:02d}", f"Club {i}", 1_000_000 + i) for i in range(count)]


def _selects(view):
    return [item for item in view.children if isinstance(item, discord.ui.Select)]


# --- Dropdowns ---


def test_picker_lists_clubs_in_trophy_order_with_trophies():
    from features.clubs.picker import ClubPicker

    clubs = [
        _club("#LOW", "Low", 1_000_000),
        _club("#HIGH", "7 Dwarves", 6_072_838),
        _club("#MID", "Mid", 3_000_000),
    ]
    (select,) = _selects(ClubPicker.for_clubs(clubs))
    assert [o.value for o in select.options] == ["#HIGH", "#MID", "#LOW"]
    assert select.options[0].label == "7 Dwarves | 🏆 6,072,838"


@pytest.mark.parametrize(
    "count, sizes", [(25, [25]), (26, [25, 1]), (45, [25, 20]), (50, [25, 25])]
)
def test_clubs_split_into_two_menus_of_up_to_25(count, sizes):
    from features.clubs.picker import ClubPicker

    selects = _selects(ClubPicker.for_clubs(_clubs(count)))
    assert [len(s.options) for s in selects] == sizes


def test_menus_have_brawltools_placeholders_and_stable_ids():
    from features.clubs.picker import ClubPicker

    first, second = _selects(ClubPicker.for_clubs(_clubs(45)))
    assert first.placeholder == "Choose a Club (1-25)"
    assert second.placeholder == "Choose a Club (26-50)"
    assert first.custom_id == "club_picker:1"
    assert second.custom_id == "club_picker:2"


def test_no_clubs_means_no_menus():
    from features.clubs.picker import ClubPicker

    assert ClubPicker.for_clubs([]) is None


def test_long_names_fit_the_option_label_limit():
    from features.clubs.picker import ClubPicker

    (select,) = _selects(ClubPicker.for_clubs([_club("#A", "X" * 120, 1)]))
    assert len(select.options[0].label) <= 100
    assert select.options[0].label.endswith("| 🏆 1")


def test_registered_picker_is_persistent():
    from features.clubs.picker import ClubPicker

    view = ClubPicker()
    assert view.timeout is None
    assert view.is_persistent()
    assert {s.custom_id for s in _selects(view)} == {"club_picker:1", "club_picker:2"}


# --- Selecting a club ---


def _selection(interaction, tag):
    from features.clubs.picker import ClubPicker

    select = _selects(ClubPicker())[0]
    select._values = [tag]  # what discord.py fills in from the interaction
    return select.callback(interaction)


async def test_selecting_a_club_shows_its_details_privately(mock_interaction):
    club = _club("#29LRGYYYP", "Renaissance", 2_525_346)
    with patch(
        "features.clubs.picker.get_tracked_club", new=AsyncMock(return_value=club)
    ) as get:
        await _selection(mock_interaction, "#29LRGYYYP")
    get.assert_awaited_once_with("#29LRGYYYP")
    call = mock_interaction.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    assert call.kwargs["embed"].title == "Renaissance (#29LRGYYYP)"


async def test_selecting_a_removed_club_says_so(mock_interaction):
    with patch(
        "features.clubs.picker.get_tracked_club", new=AsyncMock(return_value=None)
    ):
        await _selection(mock_interaction, "#GONE")
    call = mock_interaction.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    assert "no longer tracked" in call.args[0].lower()


# --- Detail embed ---


def _detail(club):
    from features.clubs.board import build_club_detail_embed

    embed = build_club_detail_embed(club)
    return embed, {f.name: f.value for f in embed.fields}


def test_detail_title_links_to_brawlify_with_badge():
    embed, _ = _detail(_club("#29LRGYYYP", "Renaissance", 2_525_346))
    assert embed.title == "Renaissance (#29LRGYYYP)"
    assert embed.url == "https://brawlify.com/club/29LRGYYYP"
    assert (
        embed.thumbnail.url
        == "https://cdn.brawlify.com/club-badges/regular/8000035.png"
    )


def test_detail_sections_match_brawltools():
    _, fields = _detail(_club("#A", "Renaissance", 2_525_346))
    assert list(fields) == [
        "Trophies",
        "Trophy Range",
        "President",
        "Required Trophies",
        "Type",
        "Members",
        "Description",
    ]
    assert "`2,525,346`" in fields["Trophies"]
    assert "**Average**" in fields["Trophies"] and "`84,178`" in fields["Trophies"]
    assert (
        "`55,151`" in fields["Trophy Range"] and "`123,995`" in fields["Trophy Range"]
    )
    assert "[rodvyns](https://brawlify.com/player/P9C2LU0)" in fields["President"]
    assert "`55,000`" in fields["Required Trophies"]
    assert "`Open`" in fields["Type"] and "🇺🇸" in fields["Type"]
    assert (
        CLUB_EMOJIS["type"] in fields["Type"]
        and CLUB_EMOJIS["region"] in fields["Type"]
    )
    assert "`30/30`" in fields["Members"]
    assert "**Vice-Presidents** `1`" in fields["Members"]
    assert "**Seniors** `4`" in fields["Members"]
    assert fields["Description"] == "```\nEnglish Speaking | Active Club\n```"


@pytest.mark.parametrize(
    "api_type, label",
    [("open", "Open"), ("inviteOnly", "Invite Only"), ("closed", "Closed")],
)
def test_detail_type_labels(api_type, label):
    _, fields = _detail(_club("#A", "X", 1, type=api_type))
    assert f"`{label}`" in fields["Type"]


def test_detail_without_country_has_no_flag():
    _, fields = _detail(_club("#A", "X", 1, country=None))
    assert CLUB_EMOJIS["region"] not in fields["Type"]


def test_detail_without_description_skips_the_section():
    _, fields = _detail(_club("#A", "X", 1, description=""))
    assert "Description" not in fields


def test_description_cannot_break_out_of_its_code_block():
    _, fields = _detail(_club("#A", "X", 1, description="evil ``` **bold**"))
    assert fields["Description"].count("```") == 2


def test_detail_for_snapshot_saved_before_619_still_renders():
    club = _club("#A", "Old", 1)
    for key in ("badge_id", "type", "description", "president_tag"):
        del club["snapshot"][key]
    embed, fields = _detail(club)
    assert embed.thumbnail.url is None
    assert "Type" not in fields and "Description" not in fields
    assert fields["President"].endswith("rodvyns")


def test_detail_for_club_not_fetched_yet():
    embed, fields = _detail(_club("#A", "New Club", None))
    assert embed.title == "New Club (#A)"
    assert "not fetched yet" in embed.description.lower()
    assert not fields


def test_detail_average_handles_empty_club():
    _, fields = _detail(_club("#A", "X", 0, member_count=0, min_member_trophies=None))
    assert "**Average**" in fields["Trophies"] and "`0`" in fields["Trophies"]
    assert "Trophy Range" not in fields


# --- Snapshot carries the detail fields ---


def test_snapshot_keeps_badge_type_and_description():
    from features.clubs.snapshots import build_snapshot

    snap = build_snapshot(
        {"badgeId": 8000035, "type": "inviteOnly", "description": "hi", "members": []},
        None,
        None,
    )
    assert snap["badge_id"] == 8000035
    assert snap["type"] == "inviteOnly"
    assert snap["description"] == "hi"


# --- Board attaches the menus to the club stats message ---


class _FakeChannel:
    def __init__(self):
        self.messages = {}
        self.sends = 0

    async def send(self, **kwargs):
        self.sends += 1
        msg = MagicMock(spec=discord.Message)
        msg.id = 1000 + self.sends
        msg.kwargs = kwargs

        async def edit(**kw):
            msg.kwargs = kw

        msg.edit = AsyncMock(side_effect=edit)
        self.messages[msg.id] = msg
        return msg

    def get_partial_message(self, message_id):
        return self.messages[message_id]


async def test_board_attaches_menus_to_club_stats_message_only(mock_bot):
    from features.clubs.cog import ClubTracking

    channel = _FakeChannel()
    mock_bot.get_channel = MagicMock(return_value=channel)
    settings = {}

    async def set_setting(key, value):
        settings[key] = value

    with (
        patch(
            "features.clubs.cog.get_setting",
            new=AsyncMock(side_effect=lambda k: settings.get(k)),
        ),
        patch("features.clubs.cog.set_setting", new=set_setting),
        patch(
            "features.clubs.cog.list_tracked_clubs",
            new=AsyncMock(return_value=_clubs(30)),
        ),
    ):
        cog = ClubTracking(mock_bot)
        await cog.update_club_board()
        await cog.update_club_board()  # the edit path carries the menus too

    overview, stats = (channel.messages[i] for i in sorted(channel.messages))
    assert overview.kwargs.get("view") is None
    assert [len(s.options) for s in _selects(stats.kwargs["view"])] == [25, 5]
    assert channel.sends == 2


async def test_menus_are_registered_at_startup_so_they_survive_restarts(mock_bot):
    from features.clubs.cog import ClubTracking
    from features.clubs.picker import ClubPicker

    mock_bot.add_view = MagicMock()
    with patch("discord.ext.tasks.Loop.start"):  # don't start the real loops
        await ClubTracking(mock_bot).cog_load()
    (view,), _ = mock_bot.add_view.call_args
    assert isinstance(view, ClubPicker) and view.is_persistent()
