"""Tests for issue #548: on_ready re-fires on every gateway reconnect.

load_features() already treats a repeat load as normal (main.py swallows
ExtensionAlreadyLoaded). Step 3 never got the equivalent guard, so the tourney
command registration raised on every reconnect and reported a feature as
failed when nothing had failed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

import main
from features.tourney.tourney_commands import setup_tourney_commands


@pytest.fixture
def bot():
    return commands.Bot(command_prefix="!", intents=discord.Intents.none())


@pytest.fixture(autouse=True)
def fresh_process_state(monkeypatch):
    """Each test is a fresh process as far as the once-per-process flags go."""
    monkeypatch.setattr(main, "_TOURNEY_PANELS_RESTORED", False, raising=False)
    import features.tourney.tourney_commands as tc

    monkeypatch.setattr(tc, "_TOURNEY_COMMANDS_REGISTERED", False, raising=False)


# --- setup_tourney_commands is re-entrant ---


async def test_registering_twice_does_not_raise(bot):
    setup_tourney_commands(bot)
    setup_tourney_commands(bot)  # the reconnect; must be a no-op


async def test_the_close_command_is_registered_once(bot):
    setup_tourney_commands(bot)
    setup_tourney_commands(bot)

    assert bot.get_command("close") is not None
    assert bot.get_command("c") is not None


async def test_persistent_views_are_not_added_twice(bot):
    # add_view sits before the failing line, so it accumulated a duplicate
    # view on every reconnect even while the registration was crashing.
    bot.add_view = MagicMock()

    setup_tourney_commands(bot)
    setup_tourney_commands(bot)

    assert bot.add_view.call_count == 1


# --- start_tourney_system: panels restore once per process ---


def _patch_tourney(monkeypatch, restore):
    monkeypatch.setattr(main, "setup_tourney_commands", MagicMock())
    monkeypatch.setattr(main, "restore_tourney_panels", restore)


async def test_panels_are_restored_on_the_first_start(monkeypatch, bot):
    restore = AsyncMock()
    _patch_tourney(monkeypatch, restore)

    assert await main.start_tourney_system(bot) == []
    restore.assert_awaited_once()


async def test_panels_are_not_restored_again_on_a_reconnect(monkeypatch, bot):
    # A reconnect does not kill the View objects, so the buttons still work.
    # Reposting would delete the panel and break its pins and jump links.
    restore = AsyncMock()
    _patch_tourney(monkeypatch, restore)

    await main.start_tourney_system(bot)
    await main.start_tourney_system(bot)

    restore.assert_awaited_once()


async def test_a_failed_restore_is_retried_on_the_next_reconnect(monkeypatch, bot):
    # The live log showed the first attempt failing on DNS. That must recover,
    # not latch the flag and skip forever.
    restore = AsyncMock(side_effect=[RuntimeError("dns"), None])
    _patch_tourney(monkeypatch, restore)

    assert await main.start_tourney_system(bot) == ["Tournaments"]
    assert await main.start_tourney_system(bot) == []
    assert restore.await_count == 2


async def test_a_real_registration_failure_is_still_reported(monkeypatch, bot):
    monkeypatch.setattr(
        main, "setup_tourney_commands", MagicMock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(main, "restore_tourney_panels", AsyncMock())

    with patch.object(main, "record_failure") as record:
        assert await main.start_tourney_system(bot) == ["Tournaments"]

    record.assert_called_once()
