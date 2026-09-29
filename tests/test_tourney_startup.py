"""Tests for issue #548: on_ready re-fires on every gateway reconnect.

load_features() already treats a repeat load as normal (main.py swallows
ExtensionAlreadyLoaded). Step 3 never got the equivalent guard, so the tourney
command registration raised on every reconnect and reported a feature as
failed when nothing had failed.
"""

import asyncio
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


# --- /starttourney and /endtourney replace the prefix commands (#567) ---

ADMIN_CHANNEL = 424242


class _StopHere(Exception):
    """Raised from a patched step to end a run once the behavior under test ran."""


def _slash_interaction(channel_id=ADMIN_CHANNEL):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 1
    interaction.user.name = "staff"
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = channel_id
    interaction.channel.send = AsyncMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.client = MagicMock()
    interaction.client.get_channel = MagicMock(return_value=None)
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    return interaction


def _private_text(interaction):
    return " ".join(
        str(c.args[0])
        for c in interaction.followup.send.call_args_list
        if c.args and c.kwargs.get("ephemeral")
    )


@pytest.fixture
async def tourney(bot, monkeypatch):
    """Registered commands plus patched gates and DB calls."""
    import features.tourney.tourney_commands as tc

    monkeypatch.setattr(tc, "TOURNEY_ADMIN_CHANNEL_ID", ADMIN_CHANNEL)
    monkeypatch.setattr(tc, "is_staff", lambda member: True)
    patches = {
        "get_active_tourney_session": AsyncMock(return_value=None),
        "create_tourney_session": AsyncMock(),
        "reset_tourney_session_start_time": AsyncMock(),
        "update_tourney_runtime_state": AsyncMock(),
        "reset_ticket_counter": MagicMock(),
        "lock_command": AsyncMock(side_effect=_StopHere),
    }
    for name, mock in patches.items():
        monkeypatch.setattr(tc, name, mock)
    setup_tourney_commands(bot)
    return MagicMock(tc=tc, bot=bot, **patches)


async def _start(tourney, interaction, region=None, force=False):
    command = tourney.bot.tree.get_command("starttourney")
    await command.callback(interaction, region=region, force=force)


async def test_start_and_end_are_slash_commands_registered_once(bot):
    setup_tourney_commands(bot)
    setup_tourney_commands(bot)

    assert bot.tree.get_command("starttourney") is not None
    assert bot.tree.get_command("endtourney") is not None
    assert bot.get_command("starttourney") is None
    assert bot.get_command("endtourney") is None


async def test_region_is_a_picker_and_force_defaults_off(bot):
    setup_tourney_commands(bot)
    params = {p.name: p for p in bot.tree.get_command("starttourney").parameters}

    assert [c.value for c in params["region"].choices] == ["SA"]
    assert params["region"].required is False
    assert params["force"].required is False
    assert params["force"].default is False


async def test_starttourney_denies_non_staff(tourney, monkeypatch):
    monkeypatch.setattr(tourney.tc, "is_staff", lambda member: False)
    interaction = _slash_interaction()

    await _start(tourney, interaction)

    assert "permission" in _private_text(interaction)
    tourney.create_tourney_session.assert_not_awaited()
    tourney.reset_ticket_counter.assert_not_called()


async def test_starttourney_denies_outside_the_admin_channel(tourney):
    interaction = _slash_interaction(channel_id=1)

    await _start(tourney, interaction)

    assert f"<#{ADMIN_CHANNEL}>" in _private_text(interaction)
    tourney.create_tourney_session.assert_not_awaited()


async def test_starttourney_refuses_an_active_session_without_force(tourney):
    tourney.get_active_tourney_session.return_value = {"_id": 7}
    interaction = _slash_interaction()

    await _start(tourney, interaction)

    text = _private_text(interaction)
    assert "already" in text and "force" in text
    assert "!starttourney" not in text, "the warning must name the slash command"
    tourney.reset_ticket_counter.assert_not_called()
    tourney.reset_tourney_session_start_time.assert_not_awaited()


async def test_starttourney_force_proceeds_over_an_active_session(tourney):
    tourney.get_active_tourney_session.return_value = {"_id": 7}
    interaction = _slash_interaction()

    with pytest.raises(_StopHere):
        await _start(tourney, interaction, force=True)

    tourney.reset_ticket_counter.assert_called_once()
    tourney.reset_tourney_session_start_time.assert_awaited_once_with(7)


@pytest.mark.parametrize("region, stored", [("SA", "SA"), (None, None)])
async def test_region_reaches_the_session_unchanged(tourney, region, stored):
    tourney.get_active_tourney_session.side_effect = [None, {"_id": 7}]
    interaction = _slash_interaction()

    with pytest.raises(_StopHere):
        await _start(tourney, interaction, region=region)

    tourney.create_tourney_session.assert_awaited_once()
    tourney.update_tourney_runtime_state.assert_any_await(7, region=stored)


async def test_starttourney_defers_before_any_work(tourney):
    interaction = _slash_interaction()

    with pytest.raises(_StopHere):
        await _start(tourney, interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)


async def test_endtourney_denies_non_staff(tourney, monkeypatch):
    monkeypatch.setattr(tourney.tc, "is_staff", lambda member: False)
    interaction = _slash_interaction()

    await asyncio.sleep(0)  # let setup's resume task make its own session check
    checks_before = tourney.get_active_tourney_session.await_count

    await tourney.bot.tree.get_command("endtourney").callback(interaction)

    assert "permission" in _private_text(interaction)
    assert tourney.get_active_tourney_session.await_count == checks_before
    interaction.channel.send.assert_not_awaited()


async def test_endtourney_denies_outside_the_admin_channel(tourney):
    interaction = _slash_interaction(channel_id=1)

    await asyncio.sleep(0)  # let setup's resume task make its own session check
    checks_before = tourney.get_active_tourney_session.await_count

    await tourney.bot.tree.get_command("endtourney").callback(interaction)

    assert f"<#{ADMIN_CHANNEL}>" in _private_text(interaction)
    assert tourney.get_active_tourney_session.await_count == checks_before
    interaction.channel.send.assert_not_awaited()
