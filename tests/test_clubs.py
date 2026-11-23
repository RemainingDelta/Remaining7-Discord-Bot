"""Tests for features/clubs.py and the tracked club helpers, from #615's acceptance criteria."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from features import brawl_stars_client as bs
from features.config import (
    ADMIN_ROLE_ID,
    COMMUNITY_MANAGER_ROLE_ID,
    FOUNDER_ROLE_ID,
    MAX_TRACKED_CLUBS,
    MEMBER_ROLE_ID,
)


def _role(role_id):
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    return role


def _with_roles(interaction, *role_ids):
    interaction.user.roles = [_role(r) for r in role_ids]
    return interaction


def _sent_text(interaction):
    """Every message content and embed description sent in reply, joined."""
    parts = []
    for mock in (interaction.response.send_message, interaction.followup.send):
        for call in mock.call_args_list:
            if call.args:
                parts.append(str(call.args[0]))
            if call.kwargs.get("content"):
                parts.append(call.kwargs["content"])
            embeds = list(call.kwargs.get("embeds") or [])
            if call.kwargs.get("embed"):
                embeds.append(call.kwargs["embed"])
            parts.extend(e.description or "" for e in embeds)
    return "\n".join(parts)


def _all_ephemeral(interaction):
    calls = (
        interaction.response.send_message.call_args_list
        + interaction.followup.send.call_args_list
    )
    return bool(calls) and all(c.kwargs.get("ephemeral") for c in calls)


def _none_ephemeral(interaction):
    """Replies and the deferred "thinking" message are all visible to the channel."""
    calls = (
        interaction.response.send_message.call_args_list
        + interaction.response.defer.call_args_list
        + interaction.followup.send.call_args_list
    )
    return bool(calls) and not any(c.kwargs.get("ephemeral") for c in calls)


@pytest.fixture
def db():
    """Patch the tracked club helpers where features.clubs uses them."""
    with (
        patch(
            "features.clubs.add_tracked_club", new=AsyncMock(return_value=True)
        ) as add,
        patch(
            "features.clubs.remove_tracked_club", new=AsyncMock(return_value=True)
        ) as remove,
        patch(
            "features.clubs.list_tracked_clubs", new=AsyncMock(return_value=[])
        ) as list_,
        patch(
            "features.clubs.count_tracked_clubs", new=AsyncMock(return_value=0)
        ) as count,
    ):
        yield MagicMock(add=add, remove=remove, list=list_, count=count)


@pytest.fixture
def api():
    with patch(
        "features.brawl_stars_client.get_club",
        new=AsyncMock(return_value={"tag": "#ABC", "name": "Remaining Delta"}),
    ) as get_club:
        yield get_club


@pytest.fixture
def cog(mock_bot):
    from features.clubs import ClubTracking

    c = ClubTracking(mock_bot)
    c.request_refresh = AsyncMock()
    return c


@pytest.fixture
def manager(mock_interaction):
    return _with_roles(mock_interaction, MEMBER_ROLE_ID, COMMUNITY_MANAGER_ROLE_ID)


async def _add(cog, interaction, tag="ABC"):
    await cog.club_add.callback(cog, interaction, tag)


async def _remove(cog, interaction, tag="#ABC"):
    await cog.club_remove.callback(cog, interaction, tag)


async def _list(cog, interaction):
    await cog.club_list.callback(cog, interaction)


# --- Permissions ---


@pytest.mark.parametrize("command", [_add, _remove, _list])
async def test_member_without_club_roles_is_refused(
    cog, mock_interaction, db, api, command
):
    _with_roles(mock_interaction, MEMBER_ROLE_ID)
    await command(cog, mock_interaction)
    assert _all_ephemeral(mock_interaction)
    assert "permission" in _sent_text(mock_interaction).lower()
    for helper in (db.add, db.remove, db.list, db.count):
        helper.assert_not_awaited()
    api.assert_not_awaited()


@pytest.mark.parametrize(
    "role_id", [COMMUNITY_MANAGER_ROLE_ID, ADMIN_ROLE_ID, FOUNDER_ROLE_ID]
)
async def test_each_club_manager_role_can_add(cog, mock_interaction, db, api, role_id):
    _with_roles(mock_interaction, MEMBER_ROLE_ID, role_id)
    await _add(cog, mock_interaction)
    db.add.assert_awaited_once()


async def test_non_member_user_is_refused(cog, mock_interaction, db, api):
    mock_interaction.user = MagicMock(spec=discord.User)
    await _add(cog, mock_interaction)
    db.add.assert_not_awaited()


# --- /club-add ---


async def test_add_saves_normalized_tag_and_name(cog, manager, db, api):
    await _add(cog, manager, " abc ")
    api.assert_awaited_once_with("#ABC")
    db.add.assert_awaited_once_with("#ABC", "Remaining Delta")
    assert "Remaining Delta" in _sent_text(manager)
    assert _none_ephemeral(manager)


async def test_add_refreshes_once_on_success(cog, manager, db, api):
    await _add(cog, manager)
    cog.request_refresh.assert_awaited_once()


async def test_add_unknown_tag_saves_nothing(cog, manager, db, api):
    api.side_effect = bs.NotFoundError("not found")
    await _add(cog, manager)
    db.add.assert_not_awaited()
    cog.request_refresh.assert_not_awaited()
    assert "no club" in _sent_text(manager).lower()


@pytest.mark.parametrize(
    "error",
    [
        bs.ApiUnavailableError("down"),
        bs.AccessDeniedError("denied", "accessDenied.invalidIp"),
    ],
)
async def test_add_api_error_saves_nothing(cog, manager, db, api, error):
    api.side_effect = error
    await _add(cog, manager)
    db.add.assert_not_awaited()
    assert "unavailable" in _sent_text(manager).lower()


async def test_add_empty_tag_is_rejected(cog, manager, db, api):
    await _add(cog, manager, " # ")
    api.assert_not_awaited()
    db.add.assert_not_awaited()


async def test_add_duplicate_is_rejected(cog, manager, db, api):
    db.add.return_value = False
    await _add(cog, manager)
    cog.request_refresh.assert_not_awaited()
    assert "already" in _sent_text(manager).lower()


async def test_add_with_and_without_hash_use_same_tag(cog, mock_bot, db, api):
    from features.clubs import ClubTracking

    tags = []
    for raw in ("#abc", "abc"):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()
        interaction.user = MagicMock(spec=discord.Member)
        _with_roles(interaction, COMMUNITY_MANAGER_ROLE_ID)
        c = ClubTracking(mock_bot)
        c.request_refresh = AsyncMock()
        await _add(c, interaction, raw)
        tags.append(db.add.await_args.args[0])
    assert tags[0] == tags[1] == "#ABC"


async def test_add_accepted_just_below_cap(cog, manager, db, api):
    db.count.return_value = MAX_TRACKED_CLUBS - 1
    await _add(cog, manager)
    db.add.assert_awaited_once()


async def test_add_rejected_at_cap(cog, manager, db, api):
    db.count.return_value = MAX_TRACKED_CLUBS
    await _add(cog, manager)
    db.add.assert_not_awaited()
    api.assert_not_awaited()
    assert str(MAX_TRACKED_CLUBS) in _sent_text(manager)


# --- /club-remove ---


async def test_remove_deletes_and_refreshes(cog, manager, db, api):
    await _remove(cog, manager, "abc")
    db.remove.assert_awaited_once_with("#ABC")
    cog.request_refresh.assert_awaited_once()
    db.add.assert_not_awaited()
    assert _none_ephemeral(manager)


async def test_remove_untracked_club_says_so(cog, manager, db, api):
    db.remove.return_value = False
    await _remove(cog, manager)
    cog.request_refresh.assert_not_awaited()
    assert "not tracked" in _sent_text(manager).lower()


# --- /club-list ---


def _club(tag, name, **extra):
    doc = {
        "_id": tag,
        "name": name,
        "country_code": None,
        "snapshot": None,
        "fetched_at": None,
        "failing_since": None,
    }
    doc.update(extra)
    return doc


async def test_list_shows_not_fetched_yet_before_first_refresh(cog, manager, db, api):
    db.list.return_value = [_club("#ABC", "Remaining Delta")]
    await _list(cog, manager)
    text = _sent_text(manager)
    assert "Remaining Delta" in text and "#ABC" in text
    assert "not fetched yet" in text.lower()
    assert "failing" not in text.lower()


async def test_list_flags_only_failing_clubs(cog, manager, db, api):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.list.return_value = [
        _club("#OK1", "Healthy", fetched_at=now, country_code="US"),
        _club("#BAD", "Broken", fetched_at=now - timedelta(hours=2), failing_since=now),
    ]
    await _list(cog, manager)
    lines = _sent_text(manager).splitlines()
    healthy = next(line for line in lines if "Healthy" in line)
    broken = next(line for line in lines if "Broken" in line)
    assert "failing" not in healthy.lower()
    assert "failing since" in broken.lower()


async def test_list_with_no_clubs_says_so(cog, manager, db, api):
    await _list(cog, manager)
    assert "no clubs" in _sent_text(manager).lower()


async def test_list_splits_long_output_under_embed_limit(cog, manager, db, api):
    db.list.return_value = [
        _club(
            f"#TAG{i:02d}",
            "N" * 40,
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        for i in range(MAX_TRACKED_CLUBS)
    ]
    await _list(cog, manager)
    embeds = []
    for call in manager.followup.send.call_args_list:
        embeds.extend(call.kwargs.get("embeds") or [])
    assert embeds
    assert all(len(e.description) <= 4096 for e in embeds)
    assert sum(e.description.count("#TAG") for e in embeds) == MAX_TRACKED_CLUBS


# --- Autocomplete ---


async def test_autocomplete_filters_by_name_or_tag(cog, mock_interaction, db):
    db.list.return_value = [
        _club("#QQGLJU2R", "Remaining Delta"),
        _club("#2YYJJV9PC", "7 Dwarves"),
    ]
    by_name = await cog.club_tag_autocomplete(mock_interaction, "delta")
    by_tag = await cog.club_tag_autocomplete(mock_interaction, "2yyj")
    assert [c.value for c in by_name] == ["#QQGLJU2R"]
    assert by_name[0].name == "Remaining Delta (#QQGLJU2R)"
    assert [c.value for c in by_tag] == ["#2YYJJV9PC"]


async def test_autocomplete_returns_at_most_25(cog, mock_interaction, db):
    db.list.return_value = [_club(f"#T{i}", f"Club {i}") for i in range(40)]
    assert len(await cog.club_tag_autocomplete(mock_interaction, "")) == 25


async def test_autocomplete_returns_empty_on_error(cog, mock_interaction, db):
    db.list.side_effect = RuntimeError("db down")
    assert await cog.club_tag_autocomplete(mock_interaction, "x") == []


# --- Mongo helpers ---


def _tracked_db():
    import database.mongo as mongo  # noqa: F401

    fake = MagicMock()
    fake.tracked_clubs.insert_one = AsyncMock()
    fake.tracked_clubs.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    return fake


async def test_add_tracked_club_inserts_club_with_empty_refresh_fields():
    import database.mongo as mongo

    fake = _tracked_db()
    with patch.object(mongo, "db", fake):
        assert await mongo.add_tracked_club("#ABC", "Remaining Delta") is True
    doc = fake.tracked_clubs.insert_one.await_args.args[0]
    assert doc["_id"] == "#ABC" and doc["name"] == "Remaining Delta"
    for field in ("country_code", "snapshot", "fetched_at", "failing_since"):
        assert doc[field] is None


async def test_add_tracked_club_returns_false_on_duplicate():
    import database.mongo as mongo
    from pymongo.errors import DuplicateKeyError

    fake = _tracked_db()
    fake.tracked_clubs.insert_one.side_effect = DuplicateKeyError("dup")
    with patch.object(mongo, "db", fake):
        assert await mongo.add_tracked_club("#ABC", "Remaining Delta") is False


async def test_remove_tracked_club_only_touches_tracked_clubs():
    import database.mongo as mongo

    fake = _tracked_db()
    with patch.object(mongo, "db", fake):
        assert await mongo.remove_tracked_club("#ABC") is True
    fake.tracked_clubs.delete_one.assert_awaited_once_with({"_id": "#ABC"})
    touched = {name for name, *_ in fake.method_calls}
    assert touched == {"tracked_clubs.delete_one"}


async def test_remove_untracked_club_returns_false():
    import database.mongo as mongo

    fake = _tracked_db()
    fake.tracked_clubs.delete_one.return_value = MagicMock(deleted_count=0)
    with patch.object(mongo, "db", fake):
        assert await mongo.remove_tracked_club("#ABC") is False


async def test_list_reply_is_public(cog, manager, db, api):
    db.list.return_value = [_club("#ABC", "Remaining Delta")]
    await _list(cog, manager)
    assert _none_ephemeral(manager)


@pytest.mark.parametrize(
    "error", [bs.NotFoundError("not found"), bs.ApiUnavailableError("down")]
)
async def test_add_errors_are_public(cog, manager, db, api, error):
    api.side_effect = error
    await _add(cog, manager)
    assert _none_ephemeral(manager)
