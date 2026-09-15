import importlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from features import event_tickets


class TestSanitizeUsername:
    def test_lowercases(self):
        assert (
            event_tickets._sanitize_username("ShivenAjwaliya", 42) == "shivenajwaliya"
        )

    def test_spaces_become_hyphens(self):
        assert event_tickets._sanitize_username("Cool Name", 42) == "cool-name"

    def test_strips_invalid_chars(self):
        assert event_tickets._sanitize_username("Cool_Name!!", 42) == "coolname"

    def test_strips_emoji_and_unicode(self):
        assert event_tickets._sanitize_username("😀foo", 42) == "foo"

    def test_collapses_and_trims_hyphens(self):
        assert event_tickets._sanitize_username("  a   b  ", 42) == "a-b"

    def test_empty_falls_back_to_user_id(self):
        assert event_tickets._sanitize_username("!!!", 42) == "42"

    def test_all_whitespace_falls_back_to_user_id(self):
        assert event_tickets._sanitize_username("   ", 7) == "7"

    def test_truncates_long_names(self):
        result = event_tickets._sanitize_username("a" * 200, 42)
        assert len(result) <= event_tickets._MAX_USERNAME_LEN


class TestExtractOpenerId:
    def test_valid_topic(self):
        assert event_tickets._extract_opener_id("event-opener:12345") == 12345

    def test_valid_topic_with_extra_parts(self):
        assert event_tickets._extract_opener_id("event-opener:999|foo:bar") == 999

    def test_missing_key(self):
        assert event_tickets._extract_opener_id("type:something") is None

    def test_none_topic(self):
        assert event_tickets._extract_opener_id(None) is None

    def test_empty_topic(self):
        assert event_tickets._extract_opener_id("") is None

    def test_non_numeric_value(self):
        assert event_tickets._extract_opener_id("event-opener:abc") is None


class TestTicketNameHelpers:
    def test_active_name_from_bare(self):
        assert event_tickets._active_name("event-foo") == "「❗」event-foo"

    def test_closed_name_from_bare(self):
        assert event_tickets._closed_name("event-foo") == "「👍」event-foo"

    def test_active_from_closed(self):
        assert event_tickets._active_name("「👍」event-foo") == "「❗」event-foo"

    def test_closed_from_active(self):
        assert event_tickets._closed_name("「❗」event-foo") == "「👍」event-foo"

    def test_round_trip(self):
        name = "event-shivenajwaliya"
        closed = event_tickets._closed_name(name)
        reopened = event_tickets._active_name(closed)
        assert reopened == event_tickets._active_name(name)


class TestIsEventTicketChannel:
    def _channel(self, category_id):
        channel = MagicMock(spec=discord.TextChannel)
        channel.category_id = category_id
        return channel

    def test_matches_configured_category(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 555)
        assert event_tickets.is_event_ticket_channel(self._channel(555)) is True

    def test_rejects_wrong_category(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 555)
        assert event_tickets.is_event_ticket_channel(self._channel(999)) is False

    def test_rejects_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 0)
        assert event_tickets.is_event_ticket_channel(self._channel(0)) is False

    def test_rejects_non_text_channel(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 555)
        assert event_tickets.is_event_ticket_channel(None) is False


class TestFindExistingTicket:
    def _category(self, *channels):
        category = MagicMock(spec=discord.CategoryChannel)
        category.channels = list(channels)
        return category

    def _ticket(self, name, topic):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = name
        channel.topic = topic
        return channel

    def test_open_ticket_blocks(self):
        ticket = self._ticket("「❗」event-foo", "event-opener:123")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is ticket

    def test_closed_ticket_does_not_block(self):
        """A closed ticket stays in the category, but must not lock the user out."""
        ticket = self._ticket("「👍」event-foo", "event-opener:123")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_id_prefix_does_not_collide(self):
        """User 123 must not match user 1234's ticket."""
        ticket = self._ticket("「❗」event-other", "event-opener:1234")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_other_user_ticket_ignored(self):
        ticket = self._ticket("「❗」event-other", "event-opener:999")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_channel_without_topic_ignored(self):
        category = self._category(self._ticket("「❗」event-foo", None))
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_empty_category(self):
        assert event_tickets._find_existing_ticket(self._category(), 123) is None

    def test_finds_open_ticket_alongside_closed_one(self):
        closed = self._ticket("「👍」event-foo", "event-opener:123")
        open_ticket = self._ticket("「❗」event-foo", "event-opener:123")
        category = self._category(closed, open_ticket)
        assert event_tickets._find_existing_ticket(category, 123) is open_ticket


class TestEventStaffRoleIds:
    def test_includes_configured_role(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 12345)
        assert event_tickets._event_staff_role_ids() == {12345}

    def test_excludes_zero(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 0)
        assert event_tickets._event_staff_role_ids() == set()


# ---------------------------------------------------------------------------
# Lifecycle tests (issue #401 acceptance criteria)
#
# The helpers above cover pure functions only. These exercise the async
# lifecycle: staff gating, the close/reopen permission flip, and the delete
# transcript path (log channel + opener DM).
# ---------------------------------------------------------------------------

STAFF_ROLE = 12345
CATEGORY = 555
TRANSCRIPT_CHANNEL = 777
OPENER_ID = 42


@pytest.fixture
def configured(monkeypatch):
    """Point the module's config constants at fixed test IDs.

    The module does `from features.config import ...` at import, so the
    constants must be patched on the feature module, not on features.config.
    """
    monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", STAFF_ROLE)
    monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", CATEGORY)
    monkeypatch.setattr(
        event_tickets, "EVENT_TICKET_TRANSCRIPT_CHANNEL_ID", TRANSCRIPT_CHANNEL
    )


class _AsyncIter:
    """Stands in for the async iterator returned by TextChannel.history()."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        async def gen():
            for item in self._items:
                yield item

        return gen()


class _Author:
    def __init__(self, name, user_id):
        self._name = name
        self.id = user_id

    def __str__(self):
        return self._name


def _history_message(content, author="alice", author_id=OPENER_ID):
    return SimpleNamespace(
        created_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        author=_Author(author, author_id),
        content=content,
        attachments=[],
    )


def _member(user_id, *role_ids, name="someone"):
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.name = name
    member.mention = f"<@{user_id}>"
    member.roles = []
    for role_id in role_ids:
        role = MagicMock(spec=discord.Role)
        role.id = role_id
        member.roles.append(role)
    return member


def _ticket_channel(
    messages=(), name="「❗」event-alice", topic=f"event-opener:{OPENER_ID}"
):
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = name
    channel.topic = topic
    channel.category_id = CATEGORY
    channel.send = AsyncMock()
    channel.edit = AsyncMock()
    channel.delete = AsyncMock()
    channel.set_permissions = AsyncMock()
    channel.history = MagicMock(return_value=_AsyncIter(messages))

    guild = MagicMock(spec=discord.Guild)
    guild.name = "TestGuild"
    guild.get_member = MagicMock(return_value=None)
    guild.get_channel = MagicMock(return_value=None)
    channel.guild = guild
    return channel


def _bot_with_opener(opener=None):
    bot = MagicMock(spec=commands.Bot)
    bot.get_user = MagicMock(return_value=opener)
    bot.fetch_user = AsyncMock(return_value=opener)
    return bot


def _log_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


# --- staff gating (AC: event staff can manage every ticket) ---


async def test_close_rejects_non_staff(configured):
    channel = _ticket_channel()
    assert await event_tickets.close_event_ticket_channel(channel, _member(9)) is False
    channel.set_permissions.assert_not_awaited()
    channel.send.assert_not_awaited()


async def test_reopen_rejects_non_staff(configured):
    channel = _ticket_channel()
    assert await event_tickets.reopen_event_ticket_channel(channel, _member(9)) is False
    channel.send.assert_not_awaited()


async def test_delete_rejects_non_staff(configured):
    channel = _ticket_channel()
    bot = _bot_with_opener()
    result = await event_tickets.delete_event_ticket_channel(channel, _member(9), bot)
    assert result is False
    channel.delete.assert_not_awaited()


async def test_delete_rejects_channel_outside_the_ticket_category(configured):
    channel = _ticket_channel()
    channel.category_id = CATEGORY + 1
    bot = _bot_with_opener()
    result = await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), bot
    )
    assert result is False
    channel.delete.assert_not_awaited()


# --- close / reopen permission flip ---


async def test_close_locks_the_opener_and_marks_the_channel(configured):
    channel = _ticket_channel()
    channel.guild.get_member.return_value = _member(OPENER_ID)

    assert (
        await event_tickets.close_event_ticket_channel(channel, _member(1, STAFF_ROLE))
        is True
    )

    assert channel.set_permissions.await_args.kwargs["send_messages"] is False
    assert channel.edit.await_args.kwargs["name"] == "「👍」event-alice"
    channel.send.assert_awaited_once()


async def test_reopen_restores_the_opener_and_marks_the_channel(configured):
    channel = _ticket_channel(name="「👍」event-alice")
    channel.guild.get_member.return_value = _member(OPENER_ID)

    assert (
        await event_tickets.reopen_event_ticket_channel(channel, _member(1, STAFF_ROLE))
        is True
    )

    assert channel.set_permissions.await_args.kwargs["send_messages"] is True
    assert channel.edit.await_args.kwargs["name"] == "「❗」event-alice"


async def test_close_does_not_lock_an_opener_who_is_staff(configured):
    # Staff keep access to their own ticket; locking them would be a lockout.
    channel = _ticket_channel()
    channel.guild.get_member.return_value = _member(OPENER_ID, STAFF_ROLE)

    await event_tickets.close_event_ticket_channel(channel, _member(1, STAFF_ROLE))

    channel.set_permissions.assert_not_awaited()


async def test_close_still_locks_when_the_rename_fails(configured):
    # The permission change matters more than the cosmetic prefix.
    channel = _ticket_channel()
    channel.guild.get_member.return_value = _member(OPENER_ID)
    channel.edit.side_effect = discord.HTTPException(MagicMock(), "rate limited")

    assert (
        await event_tickets.close_event_ticket_channel(channel, _member(1, STAFF_ROLE))
        is True
    )

    assert channel.set_permissions.await_args.kwargs["send_messages"] is False
    channel.send.assert_awaited_once()


# --- delete: transcript to log channel and to the opener's DM ---


async def test_delete_posts_the_transcript_to_the_log_channel(configured):
    channel = _ticket_channel(messages=[_history_message("my submission")])
    log = _log_channel()
    channel.guild.get_channel.return_value = log

    assert (
        await event_tickets.delete_event_ticket_channel(
            channel, _member(1, STAFF_ROLE), _bot_with_opener()
        )
        is True
    )

    sent = log.send.await_args.kwargs["file"]
    assert sent.filename == "「❗」event-alice_transcript.txt"
    assert b"my submission" in sent.fp.getvalue()


async def test_delete_dms_the_transcript_to_the_opener(configured):
    opener = MagicMock(spec=discord.User)
    opener.send = AsyncMock()
    channel = _ticket_channel(messages=[_history_message("my submission")])
    log = _log_channel()
    channel.guild.get_channel.return_value = log

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener(opener)
    )

    dm_file = opener.send.await_args.kwargs["file"]
    assert b"my submission" in dm_file.fp.getvalue()


async def test_dm_and_log_transcripts_are_separate_file_objects(configured):
    # A discord.File wraps a single-use stream: sharing one buffer between the
    # DM and the log post would send an empty second attachment.
    opener = MagicMock(spec=discord.User)
    opener.send = AsyncMock()
    channel = _ticket_channel(messages=[_history_message("my submission")])
    log = _log_channel()
    channel.guild.get_channel.return_value = log

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener(opener)
    )

    assert (
        opener.send.await_args.kwargs["file"].fp
        is not log.send.await_args.kwargs["file"].fp
    )


async def test_delete_completes_when_the_opener_has_left_the_server(configured):
    channel = _ticket_channel(messages=[_history_message("my submission")])
    bot = MagicMock(spec=commands.Bot)
    bot.get_user = MagicMock(return_value=None)
    bot.fetch_user = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))

    assert (
        await event_tickets.delete_event_ticket_channel(
            channel, _member(1, STAFF_ROLE), bot
        )
        is True
    )

    channel.delete.assert_awaited_once()


async def test_delete_completes_when_the_opener_has_dms_closed(configured):
    opener = MagicMock(spec=discord.User)
    opener.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "dms closed"))
    channel = _ticket_channel(messages=[_history_message("my submission")])

    assert (
        await event_tickets.delete_event_ticket_channel(
            channel, _member(1, STAFF_ROLE), _bot_with_opener(opener)
        )
        is True
    )

    channel.delete.assert_awaited_once()


async def test_delete_completes_when_the_log_post_fails(configured):
    channel = _ticket_channel(messages=[_history_message("my submission")])
    log = _log_channel()
    log.send.side_effect = discord.HTTPException(MagicMock(), "too large")
    channel.guild.get_channel.return_value = log

    assert (
        await event_tickets.delete_event_ticket_channel(
            channel, _member(1, STAFF_ROLE), _bot_with_opener()
        )
        is True
    )

    channel.delete.assert_awaited_once()


async def test_delete_saves_the_transcript_before_deleting_the_channel(configured):
    # Deleting first would destroy the history the transcript is built from.
    order = []
    opener = MagicMock(spec=discord.User)
    opener.send = AsyncMock(side_effect=lambda *a, **k: order.append("dm"))
    channel = _ticket_channel(messages=[_history_message("my submission")])
    log = _log_channel()
    log.send.side_effect = lambda *a, **k: order.append("log")
    channel.guild.get_channel.return_value = log
    channel.delete.side_effect = lambda *a, **k: order.append("delete")

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener(opener)
    )

    assert order == ["dm", "log", "delete"]


# --- creation: the opener topic must exist the moment the channel does ---


def _create_interaction(existing_channels=()):
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "「❗」event-alice"
    channel.mention = "#event-alice"
    channel.edit = AsyncMock()
    channel.send = AsyncMock()

    category = MagicMock(spec=discord.CategoryChannel)
    category.channels = list(existing_channels)

    guild = MagicMock(spec=discord.Guild)
    guild.get_channel = MagicMock(return_value=category)
    guild.get_role = MagicMock(return_value=None)
    guild.default_role = MagicMock()
    guild.create_text_channel = AsyncMock(return_value=channel)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.user = _member(OPENER_ID, name="alice")
    interaction.guild = guild
    interaction.client = MagicMock()
    interaction.client.user.display_avatar.url = "https://example.invalid/a.png"
    return interaction, guild, channel


async def test_opener_topic_is_set_in_the_create_call(configured):
    """The topic identifies the opener, and _find_existing_ticket reads it.

    Setting it in a second API call leaves a window where the channel exists
    with no topic, so a second click finds no existing ticket and opens a
    duplicate. The topic must land atomically with the channel.
    """
    interaction, guild, channel = _create_interaction()

    await event_tickets.create_event_ticket_channel(interaction)

    assert guild.create_text_channel.await_args.kwargs["topic"] == (
        f"event-opener:{OPENER_ID}"
    )
    channel.edit.assert_not_called()


# --- config parity: every ID must exist in BOTH config branches ---

EVENT_TICKET_CONSTANTS = (
    "EVENT_TICKET_PANEL_CHANNEL_ID",
    "EVENT_TICKET_CATEGORY_ID",
    "EVENT_TICKET_TRANSCRIPT_CHANNEL_ID",
)


def _assert_event_ticket_ids_configured(config_module):
    values = []
    for name in EVENT_TICKET_CONSTANTS:
        value = getattr(config_module, name)
        assert isinstance(value, int) and value > 0, f"{name} is not configured"
        values.append(value)
    assert len(set(values)) == len(values), "the three IDs must be distinct channels"


def test_dev_config_has_every_event_ticket_id():
    # The suite runs under BOT_MODE=TEST, which resolves to the DEV branch.
    import features.config

    _assert_event_ticket_ids_configured(features.config)


def test_prod_config_has_every_event_ticket_id():
    # An ID set in only one branch leaves the feature silently inert on the
    # other server, since every guard treats 0 as "not configured".
    import features.config

    os.environ["BOT_MODE"] = "PROD"
    try:
        _assert_event_ticket_ids_configured(importlib.reload(features.config))
    finally:
        os.environ["BOT_MODE"] = "TEST"
        importlib.reload(features.config)
