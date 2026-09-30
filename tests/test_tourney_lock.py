"""Tests for issue #559: event support is hidden during tourneys.

!starttourney locks the OTHER ticket channel from members and !endtourney (or
the auto-reopen timer) shows it again. The event ticket panel channel follows
the same lock so members cannot open event tickets mid-tourney.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import features.tourney.tourney_commands as tc

OTHER_ID = 1001
EVENT_ID = 2002
MEMBER_ROLE_ID = 3003


def _channel(channel_id: int) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    channel.set_permissions = AsyncMock()
    return channel


@pytest.fixture
def member_role():
    return MagicMock(spec=discord.Role)


@pytest.fixture
def other_channel(member_role):
    channel = _channel(OTHER_ID)
    channel.guild = MagicMock(spec=discord.Guild)
    channel.guild.get_role = MagicMock(return_value=member_role)
    return channel


@pytest.fixture
def event_channel():
    return _channel(EVENT_ID)


@pytest.fixture(autouse=True)
def lock_config(monkeypatch):
    monkeypatch.setattr(tc, "OTHER_TICKET_CHANNEL_ID", OTHER_ID)
    monkeypatch.setattr(tc, "EVENT_TICKET_PANEL_CHANNEL_ID", EVENT_ID, raising=False)
    monkeypatch.setattr(tc, "MEMBER_ROLE_ID", MEMBER_ROLE_ID)
    monkeypatch.setattr(tc, "is_staff", lambda member: True)
    monkeypatch.setattr(tc, "lock_tasks", {})


def _ctx(channels: dict[int, MagicMock]) -> MagicMock:
    ctx = MagicMock()
    ctx.author = MagicMock(spec=discord.Member)
    ctx.reply = AsyncMock()
    ctx.send = AsyncMock()
    ctx.channel = MagicMock()
    ctx.channel.id = 9999
    ctx.bot = MagicMock()
    ctx.bot.get_channel = MagicMock(side_effect=channels.get)
    return ctx


async def test_lock_hides_event_panel_from_members(
    other_channel, event_channel, member_role
):
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.lock_command(ctx)

    event_channel.set_permissions.assert_awaited_once_with(
        member_role, view_channel=False
    )


async def test_lock_still_hides_other_ticket_channel(
    other_channel, event_channel, member_role
):
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.lock_command(ctx)

    other_channel.set_permissions.assert_awaited_once_with(
        member_role, view_channel=False
    )


async def test_unlock_shows_event_panel_again(
    other_channel, event_channel, member_role
):
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.unlock_command(ctx)

    event_channel.set_permissions.assert_awaited_once_with(
        member_role, view_channel=True
    )


async def test_auto_reopen_timer_shows_event_panel_again(
    monkeypatch, other_channel, event_channel, member_role
):
    monkeypatch.setattr(tc, "LOCK_DURATION_HOURS", 0)
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.lock_command(ctx)
    await tc.lock_tasks[OTHER_ID]

    event_channel.set_permissions.assert_awaited_with(member_role, view_channel=True)


async def test_missing_event_panel_does_not_block_lock(other_channel, member_role):
    ctx = _ctx({OTHER_ID: other_channel})  # event panel channel not found

    await tc.lock_command(ctx)

    other_channel.set_permissions.assert_awaited_once_with(
        member_role, view_channel=False
    )


async def test_forbidden_on_event_panel_does_not_raise(
    other_channel, event_channel, member_role
):
    event_channel.set_permissions.side_effect = discord.Forbidden(
        MagicMock(status=403), "Missing Permissions"
    )
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.lock_command(ctx)
    await tc.unlock_command(ctx)

    other_channel.set_permissions.assert_awaited_with(member_role, view_channel=True)


# --- the lock notices post in the channel under /start-tourney and /end-tourney (#567) ---
# Under the slash commands the first ctx.reply answers the interaction and would
# swallow the gate slot, so progress notices go to the channel with send.


async def test_lock_notice_is_posted_in_the_channel(other_channel, event_channel):
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.lock_command(ctx)

    text = ctx.send.await_args.args[0]
    assert "Locked" in text
    assert "/end-tourney" in text, "the lock is lifted by /end-tourney"
    ctx.reply.assert_not_awaited()


async def test_unlock_notice_is_posted_in_the_channel(other_channel, event_channel):
    ctx = _ctx({OTHER_ID: other_channel, EVENT_ID: event_channel})

    await tc.unlock_command(ctx)

    assert "Unlocked" in ctx.send.await_args.args[0]
    ctx.reply.assert_not_awaited()
