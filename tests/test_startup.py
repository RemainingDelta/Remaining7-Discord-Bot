"""Tests for the bot startup sequence in features/startup.py (#469).

Derived from #469's first acceptance criterion: a command sent shortly after a
restart must either be processed or produce feedback. Two things have to hold for
that. Every extension must be attempted even when one of them fails, and a command
that genuinely is not available yet must say so instead of going silent.

The gateway ordering itself (setup_hook finishing before the first MESSAGE_CREATE)
is a discord.py guarantee with no live-bot harness in this repo, so it is verified
by running BOT_MODE=DEV against the test server rather than here.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from features.startup import EXTENSIONS, handle_command_error, load_all_extensions


def _ctx():
    ctx = MagicMock(spec=commands.Context)
    ctx.reply = AsyncMock()
    return ctx


async def test_all_extensions_are_attempted():
    bot = MagicMock(spec=commands.Bot)
    bot.load_extension = AsyncMock()

    assert await load_all_extensions(bot) == []
    assert bot.load_extension.await_count == len(EXTENSIONS)


async def test_one_failing_extension_does_not_skip_the_rest():
    """#469: the 16 loads shared one try/except, so a failure in the second cog
    silently dropped every cog after it -- including the one registering !c."""
    attempted = []

    async def fake_load(name):
        attempted.append(name)
        if name == EXTENSIONS[1]:
            raise RuntimeError("bad cog")

    bot = MagicMock(spec=commands.Bot)
    bot.load_extension = AsyncMock(side_effect=fake_load)

    failed = await load_all_extensions(bot)

    assert attempted == list(EXTENSIONS)
    assert failed == [EXTENSIONS[1]]


async def test_every_extension_still_fails_independently():
    """The pathological case: all of them broken, all of them reported."""
    bot = MagicMock(spec=commands.Bot)
    bot.load_extension = AsyncMock(side_effect=RuntimeError("everything is broken"))

    assert await load_all_extensions(bot) == list(EXTENSIONS)


def test_heartbeat_extension_is_loaded():
    """The missed-!c sweep has no window to scan unless the clock is running."""
    assert "features.heartbeat" in EXTENSIONS


async def test_unknown_command_before_startup_gets_feedback():
    """The reported symptom was total silence during the startup window."""
    ctx = _ctx()

    await handle_command_error(ctx, commands.CommandNotFound(), startup_done=False)

    ctx.reply.assert_awaited_once()


async def test_unknown_command_after_startup_stays_silent():
    """Negative case: once started, random !chatter must not start getting replies."""
    ctx = _ctx()

    await handle_command_error(ctx, commands.CommandNotFound(), startup_done=True)

    ctx.reply.assert_not_awaited()


async def test_failure_to_send_the_feedback_is_not_fatal():
    ctx = _ctx()
    ctx.reply = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(), "message deleted")
    )

    await handle_command_error(ctx, commands.CommandNotFound(), startup_done=False)

    ctx.reply.assert_awaited_once()


async def test_real_command_errors_are_still_reported(capsys):
    """Adding a handler must not newly swallow genuine command failures."""
    ctx = _ctx()
    error = commands.CommandInvokeError(ValueError("kaboom"))

    await handle_command_error(ctx, error, startup_done=True)

    assert "kaboom" in capsys.readouterr().err
