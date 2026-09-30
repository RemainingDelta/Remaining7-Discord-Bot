"""Tests for features/sticky.py: the "Set Sticky" message command and /unsticky (#565)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import app_commands

from features.config import EVENT_STAFF_ROLE_ID
from features.sticky import StickyMessages

CHANNEL_ID = 424242


def make_cog(bot=None):
    return StickyMessages(bot or MagicMock())


def make_user(admin=False, event_staff=False):
    user = MagicMock(spec=discord.Member)
    user.guild_permissions = MagicMock(administrator=admin)
    user.get_role = MagicMock(
        side_effect=lambda rid: (
            MagicMock() if event_staff and rid == EVENT_STAFF_ROLE_ID else None
        )
    )
    return user


@pytest.fixture
def channel():
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = CHANNEL_ID
    posted = MagicMock(spec=discord.Message)
    posted.id = 999
    ch.send = AsyncMock(return_value=posted)
    ch.fetch_message = AsyncMock()
    return ch


@pytest.fixture
def interaction(mock_interaction, channel):
    mock_interaction.channel = channel
    mock_interaction.channel_id = CHANNEL_ID
    mock_interaction.user = make_user(admin=True)
    return mock_interaction


def make_attachment(filename="banner.png", data=b"img"):
    att = MagicMock(spec=discord.Attachment)
    att.filename = filename
    att.read = AsyncMock(return_value=data)
    return att


def make_target(content="", attachments=()):
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.attachments = list(attachments)
    return msg


@pytest.fixture
def db():
    """Patch the sticky Mongo helpers used by the cog."""
    with (
        patch("features.sticky.get_sticky", new=AsyncMock(return_value=None)) as get,
        patch("features.sticky.set_sticky", new=AsyncMock()) as set_,
        patch("features.sticky.delete_sticky", new=AsyncMock()) as delete,
    ):
        yield MagicMock(get=get, set=set_, delete=delete)


def was_ephemeral(interaction):
    for call in (
        interaction.response.send_message.call_args,
        interaction.followup.send.call_args,
    ):
        if call is not None and call.kwargs.get("ephemeral"):
            return True
    return False


# --- permissions ---


async def test_set_sticky_denies_non_staff(interaction, db):
    interaction.user = make_user()
    await make_cog().set_sticky_message(interaction, make_target("hello"))

    assert was_ephemeral(interaction)
    db.set.assert_not_awaited()
    interaction.channel.send.assert_not_awaited()


async def test_unsticky_denies_non_staff(interaction, db):
    interaction.user = make_user()
    db.get.return_value = {"content": "hi", "bot_message_id": 1}
    cog = make_cog()

    await cog.unsticky.callback(cog, interaction)

    assert was_ephemeral(interaction)
    db.delete.assert_not_awaited()


async def test_event_staff_can_set_sticky(interaction, db):
    # #404: Event Staff (not admin) may manage stickies.
    interaction.user = make_user(event_staff=True)
    await make_cog().set_sticky_message(interaction, make_target("hello"))

    db.set.assert_awaited_once()


async def test_event_staff_can_unsticky(interaction, db):
    interaction.user = make_user(event_staff=True)
    db.get.return_value = {"content": "hi", "bot_message_id": 1}
    cog = make_cog()

    await cog.unsticky.callback(cog, interaction)

    db.delete.assert_awaited_once_with(CHANNEL_ID)


# --- Set Sticky ---


async def test_set_sticky_text_only_stores_text_and_posts(interaction, db):
    await make_cog().set_sticky_message(interaction, make_target("Read the rules"))

    interaction.channel.send.assert_awaited_once()
    channel_id, content, attachments, bot_msg_id = db.set.call_args.args
    assert channel_id == CHANNEL_ID
    assert content == "Read the rules"
    assert attachments == []
    assert bot_msg_id == 999


async def test_set_sticky_attachments_only_stores_attachments(interaction, db):
    target = make_target("", [make_attachment("banner.png", b"PNGDATA")])

    await make_cog().set_sticky_message(interaction, target)

    _, content, attachments, _ = db.set.call_args.args
    assert content == ""
    assert attachments == [{"filename": "banner.png", "data": b"PNGDATA"}]


async def test_set_sticky_with_nothing_to_stick_errors(interaction, db):
    await make_cog().set_sticky_message(interaction, make_target(""))

    assert was_ephemeral(interaction)
    db.set.assert_not_awaited()
    interaction.channel.send.assert_not_awaited()


async def test_set_sticky_replaces_existing_bot_message_first(interaction, db):
    order = []
    old_msg = MagicMock()
    old_msg.delete = AsyncMock(side_effect=lambda: order.append("delete_old"))
    interaction.channel.fetch_message = AsyncMock(return_value=old_msg)
    posted = MagicMock(id=999)

    async def send(**kwargs):
        order.append("post_new")
        return posted

    interaction.channel.send = AsyncMock(side_effect=send)
    db.get.return_value = {"content": "old", "bot_message_id": 555}

    await make_cog().set_sticky_message(interaction, make_target("new"))

    interaction.channel.fetch_message.assert_awaited_once_with(555)
    assert order == ["delete_old", "post_new"]


async def test_set_sticky_confirms_ephemerally(interaction, db):
    await make_cog().set_sticky_message(interaction, make_target("hello"))

    assert was_ephemeral(interaction)


# --- /unsticky ---


async def test_unsticky_without_sticky_errors(interaction, db):
    cog = make_cog()
    await cog.unsticky.callback(cog, interaction)

    assert was_ephemeral(interaction)
    db.delete.assert_not_awaited()


async def test_unsticky_removes_message_doc_and_pending_repost(interaction, db):
    old_msg = MagicMock()
    old_msg.delete = AsyncMock()
    interaction.channel.fetch_message = AsyncMock(return_value=old_msg)
    db.get.return_value = {"content": "hi", "bot_message_id": 555}
    cog = make_cog()
    pending = asyncio.get_running_loop().create_future()
    cog._pending[CHANNEL_ID] = pending

    await cog.unsticky.callback(cog, interaction)

    old_msg.delete.assert_awaited_once()
    db.delete.assert_awaited_once_with(CHANNEL_ID)
    assert pending.cancelled()
    assert CHANNEL_ID not in cog._pending


# --- registration ---


def test_no_sticky_prefix_commands_are_registered():
    names = {c.name for c in make_cog().get_commands()}
    assert "sticky" not in names
    assert "unsticky" not in names


def test_unsticky_is_a_slash_command():
    names = [c.name for c in make_cog().get_app_commands()]
    assert "unsticky" in names


async def test_cog_load_registers_set_sticky_message_command():
    bot = MagicMock()
    cog = make_cog(bot)

    await cog.cog_load()

    menu = bot.tree.add_command.call_args.args[0]
    assert isinstance(menu, app_commands.ContextMenu)
    assert menu.name == "Set Sticky"
    assert menu.type is discord.AppCommandType.message


async def test_cog_unload_removes_set_sticky_message_command():
    bot = MagicMock()
    cog = make_cog(bot)

    await cog.cog_unload()

    bot.tree.remove_command.assert_called_once_with(
        "Set Sticky", type=discord.AppCommandType.message
    )
