"""Tests for tourney prefix-command registration (#469).

Derived from #469: the reported symptom was `!c` doing nothing at all. One way that
happens permanently rather than just during the startup window is a failure while
registering the Hall of Fame view, which used to run before the @bot.command
declarations and took every tourney prefix command down with it.
"""

import asyncio

import discord
from discord.ext import commands

from features.tourney.tourney_commands import setup_tourney_commands


def _bot():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    # Pretend the dashboard cog is already present so setup does not spin up its
    # real task loops, which would sit forever on wait_until_ready in a test.
    bot.get_cog = lambda name: object()
    return bot


async def _drain():
    for task in asyncio.all_tasks() - {asyncio.current_task()}:
        task.cancel()


async def test_tourney_prefix_commands_are_registered():
    bot = _bot()
    try:
        setup_tourney_commands(bot)
    finally:
        await _drain()

    for name in ("close", "c", "starttourney", "endtourney"):
        assert bot.get_command(name) is not None, name


async def test_close_command_survives_a_failing_view_registration():
    """#469: add_view ran at tourney_commands.py:1755, before the command
    declarations, so one bad view left !c unregistered for the whole process."""
    bot = _bot()

    def boom(*args, **kwargs):
        raise RuntimeError("view registration failed")

    bot.add_view = boom

    try:
        setup_tourney_commands(bot)
    finally:
        await _drain()

    assert bot.get_command("close") is not None
    assert bot.get_command("c") is not None
