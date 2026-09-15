import importlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from features.config import ADMIN_ROLE_ID
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
    def test_includes_both_configured_roles(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 12345)
        monkeypatch.setattr(event_tickets, "ADMIN_ROLE_ID", 54321)
        assert event_tickets._event_staff_role_ids() == {12345, 54321}

    def test_keeps_the_admin_role_when_event_staff_is_unset(self, monkeypatch):
        # A missing event-staff role must not lock admins out of the feature.
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 0)
        monkeypatch.setattr(event_tickets, "ADMIN_ROLE_ID", 54321)
        assert event_tickets._event_staff_role_ids() == {54321}

    def test_excludes_zero(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 0)
        monkeypatch.setattr(event_tickets, "ADMIN_ROLE_ID", 0)
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


def _history_message(content, author="alice", author_id=OPENER_ID, attachments=()):
    return SimpleNamespace(
        created_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        author=_Author(author, author_id),
        content=content,
        attachments=list(attachments),
    )


FILESIZE_LIMIT = 10 * 1024 * 1024


def _attachment(filename, data=b"IMAGEBYTES", size=None, read_error=None):
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = filename
    attachment.size = len(data) if size is None else size
    attachment.url = f"https://cdn.invalid/{filename}"
    if read_error is None:
        attachment.read = AsyncMock(return_value=data)
    else:
        attachment.read = AsyncMock(side_effect=read_error)
    return attachment


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
    guild.filesize_limit = FILESIZE_LIMIT
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

    sent = log.send.await_args.kwargs["files"][0]
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

    dm_file = opener.send.await_args.kwargs["files"][0]
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
        opener.send.await_args.kwargs["files"][0].fp
        is not log.send.await_args.kwargs["files"][0].fp
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


def _create_interaction(existing_channels=(), resolvable_roles=()):
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "「❗」event-alice"
    channel.mention = "#event-alice"
    channel.edit = AsyncMock()
    channel.send = AsyncMock()

    category = MagicMock(spec=discord.CategoryChannel)
    category.channels = list(existing_channels)

    roles = {}
    for role_id in resolvable_roles:
        role = MagicMock(spec=discord.Role)
        role.id = role_id
        roles[role_id] = role

    guild = MagicMock(spec=discord.Guild)
    guild.get_channel = MagicMock(return_value=category)
    guild.get_role = MagicMock(side_effect=lambda role_id: roles.get(role_id))
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


# ---------------------------------------------------------------------------
# Admin access: every gate runs through _event_staff_role_ids(), so admins
# must be accepted there rather than at each call site.
# ---------------------------------------------------------------------------


def test_admin_role_counts_as_event_staff(configured):
    assert event_tickets._is_event_staff(_member(1, ADMIN_ROLE_ID)) is True


def test_event_staff_role_still_counts(configured):
    assert event_tickets._is_event_staff(_member(1, STAFF_ROLE)) is True


def test_member_with_neither_role_is_not_staff(configured):
    assert event_tickets._is_event_staff(_member(1)) is False


def test_plain_user_is_not_staff(configured):
    # A discord.User has no roles at all; the gate must not raise.
    assert event_tickets._is_event_staff(MagicMock(spec=discord.User)) is False


async def test_new_ticket_grants_access_to_the_admin_role(configured):
    interaction, guild, _ = _create_interaction(
        resolvable_roles=(STAFF_ROLE, ADMIN_ROLE_ID)
    )

    await event_tickets.create_event_ticket_channel(interaction)

    looked_up = {call.args[0] for call in guild.get_role.call_args_list}
    assert ADMIN_ROLE_ID in looked_up
    # @everyone, the opener, and both staff roles.
    assert len(guild.create_text_channel.await_args.kwargs["overwrites"]) == 4


async def test_admin_can_close_reopen_and_delete(configured):
    admin = _member(1, ADMIN_ROLE_ID)

    closed = _ticket_channel()
    closed.guild.get_member.return_value = _member(OPENER_ID)
    assert await event_tickets.close_event_ticket_channel(closed, admin) is True

    reopened = _ticket_channel(name="「👍」event-alice")
    reopened.guild.get_member.return_value = _member(OPENER_ID)
    assert await event_tickets.reopen_event_ticket_channel(reopened, admin) is True

    deleted = _ticket_channel(messages=[_history_message("submission")])
    result = await event_tickets.delete_event_ticket_channel(
        deleted, admin, _bot_with_opener()
    )
    assert result is True


# ---------------------------------------------------------------------------
# Panel repost on restart
# ---------------------------------------------------------------------------

PANEL_CHANNEL = 888


@pytest.fixture
def panel_configured(monkeypatch, configured):
    monkeypatch.setattr(event_tickets, "EVENT_TICKET_PANEL_CHANNEL_ID", PANEL_CHANNEL)
    monkeypatch.setattr(event_tickets, "_PANEL_REPOSTED", False, raising=False)


def _panel_channel(messages=()):
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "event-tickets"
    channel.purge = AsyncMock()
    channel.send = AsyncMock()
    channel.history = MagicMock(return_value=_AsyncIter(messages))

    guild = MagicMock(spec=discord.Guild)
    guild.me = MagicMock(spec=discord.Member)
    channel.guild = guild

    permissions = MagicMock()
    permissions.manage_messages = True
    channel.permissions_for = MagicMock(return_value=permissions)
    return channel


def _panel_bot(channel):
    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.display_avatar.url = "https://example.invalid/a.png"
    bot.get_channel = MagicMock(return_value=channel)
    return bot


def _stale_panel_message():
    message = MagicMock(spec=discord.Message)
    message.delete = AsyncMock()
    return message


async def test_repost_deletes_messages_from_every_author(panel_configured):
    # Unlike repost_privacy_policy, this channel is panel-only: everything goes,
    # so the purge must not be filtered by author.
    channel = _panel_channel()

    await event_tickets.repost_event_ticket_panel(_panel_bot(channel))

    channel.purge.assert_awaited_once()
    assert "check" not in channel.purge.await_args.kwargs


async def test_repost_posts_a_fresh_panel_with_its_view(panel_configured):
    channel = _panel_channel()

    await event_tickets.repost_event_ticket_panel(_panel_bot(channel))

    kwargs = channel.send.await_args.kwargs
    assert isinstance(kwargs["view"], event_tickets.EventTicketPanelView)
    assert kwargs["embed"].title == "Event Tickets"


async def test_repost_rebuilds_the_embed_instead_of_reusing_the_old_one(
    panel_configured,
):
    # restore_tourney_panels re-sends the embed it found, so edits to the panel
    # text never propagate. This must build from source every time.
    channel = _panel_channel(messages=[_stale_panel_message()])
    bot = _panel_bot(channel)

    await event_tickets.repost_event_ticket_panel(bot)

    expected = event_tickets.build_event_panel_embed(bot.user)
    sent = channel.send.await_args.kwargs["embed"]
    assert sent.title == expected.title
    assert sent.description == expected.description


async def test_repost_purges_before_posting(panel_configured):
    order = []
    channel = _panel_channel()
    channel.purge = AsyncMock(side_effect=lambda *a, **k: order.append("purge"))
    channel.send = AsyncMock(side_effect=lambda *a, **k: order.append("send"))

    await event_tickets.repost_event_ticket_panel(_panel_bot(channel))

    assert order == ["purge", "send"]


async def test_repost_falls_back_to_single_deletes_when_bulk_purge_fails(
    panel_configured,
):
    # Discord refuses to bulk-delete anything older than 14 days.
    stale = [_stale_panel_message(), _stale_panel_message()]
    channel = _panel_channel(messages=stale)
    channel.purge = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "too old for bulk delete")
    )

    await event_tickets.repost_event_ticket_panel(_panel_bot(channel))

    for message in stale:
        message.delete.assert_awaited_once()
    channel.send.assert_awaited_once()


async def test_repost_skips_when_the_channel_id_is_unset(panel_configured, monkeypatch):
    monkeypatch.setattr(event_tickets, "EVENT_TICKET_PANEL_CHANNEL_ID", 0)
    bot = _panel_bot(_panel_channel())

    await event_tickets.repost_event_ticket_panel(bot)

    bot.get_channel.assert_not_called()


async def test_repost_skips_a_missing_channel(panel_configured):
    bot = _panel_bot(None)

    await event_tickets.repost_event_ticket_panel(bot)  # must not raise


async def test_repost_skips_a_non_text_channel(panel_configured):
    voice = MagicMock(spec=discord.VoiceChannel)
    bot = _panel_bot(voice)

    await event_tickets.repost_event_ticket_panel(bot)  # must not raise


async def test_repost_skips_when_the_bot_cannot_manage_messages(panel_configured):
    # Posting without being able to clean up would stack a new panel on every
    # restart, so skip entirely and leave the log line as the signal.
    channel = _panel_channel()
    channel.permissions_for.return_value.manage_messages = False

    await event_tickets.repost_event_ticket_panel(_panel_bot(channel))

    channel.purge.assert_not_awaited()
    channel.send.assert_not_awaited()


async def test_repost_runs_once_per_process(panel_configured):
    # on_ready re-fires on every gateway reconnect; only a real restart should
    # wipe and repost the channel.
    channel = _panel_channel()
    bot = _panel_bot(channel)

    await event_tickets.repost_event_ticket_panel(bot)
    await event_tickets.repost_event_ticket_panel(bot)

    channel.send.assert_awaited_once()


async def test_repost_survives_a_discord_error(panel_configured):
    channel = _panel_channel()
    channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))

    await event_tickets.repost_event_ticket_panel(_panel_bot(channel))  # must not raise


# ---------------------------------------------------------------------------
# Transcript images (#387)
#
# Attachment URLs are signed and expire in about a day, and deleting the
# channel makes the originals collectable, so the bytes have to be re-uploaded
# while the channel still exists.
# ---------------------------------------------------------------------------


def _images_in(send_mock):
    files = send_mock.await_args.kwargs["files"]
    return [f for f in files if not f.filename.endswith(".txt")]


def _transcript_text(send_mock):
    files = send_mock.await_args.kwargs["files"]
    return files[0].fp.getvalue().decode()


def _channel_with_attachments(*attachments_per_message):
    messages = [
        _history_message("see attached", attachments=list(attachments))
        for attachments in attachments_per_message
    ]
    channel = _ticket_channel(messages=messages)
    log = _log_channel()
    channel.guild.get_channel.return_value = log
    return channel, log


async def test_delete_reuploads_images_to_the_log_channel(configured):
    channel, log = _channel_with_attachments([_attachment("shot.png", b"PNGDATA")])

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    images = _images_in(log.send)
    assert len(images) == 1
    assert "shot.png" in images[0].filename
    assert images[0].fp.getvalue() == b"PNGDATA"


async def test_delete_dms_the_images_to_the_opener(configured):
    opener = MagicMock(spec=discord.User)
    opener.send = AsyncMock()
    channel, _ = _channel_with_attachments([_attachment("shot.png", b"PNGDATA")])

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener(opener)
    )

    images = _images_in(opener.send)
    assert [image.fp.getvalue() for image in images] == [b"PNGDATA"]


async def test_dm_and_log_images_are_separate_file_objects(configured):
    # Same single-use-stream rule as the transcript itself.
    opener = MagicMock(spec=discord.User)
    opener.send = AsyncMock()
    channel, log = _channel_with_attachments([_attachment("shot.png", b"PNGDATA")])

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener(opener)
    )

    assert _images_in(opener.send)[0].fp is not _images_in(log.send)[0].fp


async def test_delete_does_not_reupload_non_images(configured):
    channel, log = _channel_with_attachments([_attachment("notes.pdf", b"PDFDATA")])

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    assert _images_in(log.send) == []
    # Still recorded, so nothing disappears without a trace.
    assert "notes.pdf" in _transcript_text(log.send)


async def test_delete_attaches_at_most_nine_images(configured):
    # Discord allows 10 attachments per message and the .txt takes one slot.
    channel, log = _channel_with_attachments(
        *[[_attachment(f"shot{i}.png", b"D")] for i in range(10)]
    )

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    assert len(_images_in(log.send)) == 9
    assert "shot9.png" in _transcript_text(log.send)


async def test_delete_skips_an_image_larger_than_the_upload_limit(configured):
    channel, log = _channel_with_attachments(
        [_attachment("huge.png", b"D", size=FILESIZE_LIMIT + 1)]
    )

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    assert _images_in(log.send) == []
    assert "huge.png" in _transcript_text(log.send)


async def test_delete_skips_an_unreadable_image_and_still_completes(configured):
    channel, log = _channel_with_attachments(
        [_attachment("gone.png", read_error=discord.NotFound(MagicMock(), "gone"))]
    )

    result = await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    assert result is True
    assert _images_in(log.send) == []
    channel.delete.assert_awaited_once()


async def test_delete_keeps_duplicate_image_filenames_distinct(configured):
    channel, log = _channel_with_attachments(
        [_attachment("image.png", b"FIRST")], [_attachment("image.png", b"SECOND")]
    )

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    images = _images_in(log.send)
    assert len({image.filename for image in images}) == 2


async def test_delete_scans_the_channel_history_once(configured):
    # Collecting the text and the images in separate passes would double the
    # API cost on a long ticket.
    channel, log = _channel_with_attachments([_attachment("shot.png", b"PNGDATA")])

    await event_tickets.delete_event_ticket_channel(
        channel, _member(1, STAFF_ROLE), _bot_with_opener()
    )

    channel.history.assert_called_once()
