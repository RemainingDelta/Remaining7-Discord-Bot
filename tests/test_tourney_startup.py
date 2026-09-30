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


async def test_the_ticket_slash_commands_are_registered_once(bot):
    setup_tourney_commands(bot)
    setup_tourney_commands(bot)

    for name in ("close", "delete", "reopen"):
        assert bot.tree.get_command(name) is not None
    for name in ("close", "c", "delete", "del", "reopen"):
        assert bot.get_command(name) is None, f"prefix !{name} still registered"


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


# --- /start-tourney and /end-tourney replace the prefix commands (#567) ---

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


def _reply_text(interaction):
    """Text the command answered with, which everyone in the channel can see."""
    return " ".join(
        str(c.args[0])
        for c in interaction.followup.send.call_args_list
        if c.args and c.kwargs.get("ephemeral") is False
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
    command = tourney.bot.tree.get_command("start-tourney")
    await command.callback(interaction, region=region, force=force)


async def test_start_and_end_are_slash_commands_registered_once(bot):
    setup_tourney_commands(bot)
    setup_tourney_commands(bot)

    assert bot.tree.get_command("start-tourney") is not None
    assert bot.tree.get_command("end-tourney") is not None
    assert bot.get_command("starttourney") is None
    assert bot.get_command("endtourney") is None
    # Named to match the other hyphenated commands (/tourney-panel, /hall-of-fame).
    assert bot.tree.get_command("starttourney") is None
    assert bot.tree.get_command("endtourney") is None


async def test_region_is_a_picker_and_force_defaults_off(bot):
    setup_tourney_commands(bot)
    params = {p.name: p for p in bot.tree.get_command("start-tourney").parameters}

    assert [c.value for c in params["region"].choices] == ["SA"]
    assert params["region"].required is False
    assert params["force"].required is False
    assert params["force"].default is False


async def test_starttourney_denies_non_staff(tourney, monkeypatch):
    monkeypatch.setattr(tourney.tc, "is_staff", lambda member: False)
    interaction = _slash_interaction()

    await _start(tourney, interaction)

    assert "permission" in _reply_text(interaction)
    tourney.create_tourney_session.assert_not_awaited()
    tourney.reset_ticket_counter.assert_not_called()


async def test_starttourney_denies_outside_the_admin_channel(tourney):
    interaction = _slash_interaction(channel_id=1)

    await _start(tourney, interaction)

    assert f"<#{ADMIN_CHANNEL}>" in _reply_text(interaction)
    tourney.create_tourney_session.assert_not_awaited()


async def test_starttourney_refuses_an_active_session_without_force(tourney):
    tourney.get_active_tourney_session.return_value = {"_id": 7}
    interaction = _slash_interaction()

    await _start(tourney, interaction)

    text = _reply_text(interaction)
    assert "already" in text and "force" in text
    assert "/start-tourney" in text, "the warning must name the slash command"
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
    tourney.update_tourney_runtime_state.assert_any_await(
        7, region=stored, setup_complete=False
    )


async def test_starttourney_defers_before_any_work(tourney):
    interaction = _slash_interaction()

    with pytest.raises(_StopHere):
        await _start(tourney, interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)


async def test_endtourney_denies_non_staff(tourney, monkeypatch):
    monkeypatch.setattr(tourney.tc, "is_staff", lambda member: False)
    interaction = _slash_interaction()

    await asyncio.sleep(0)  # let setup's resume task make its own session check
    checks_before = tourney.get_active_tourney_session.await_count

    await tourney.bot.tree.get_command("end-tourney").callback(interaction)

    assert "permission" in _reply_text(interaction)
    assert tourney.get_active_tourney_session.await_count == checks_before
    interaction.channel.send.assert_not_awaited()


async def test_endtourney_denies_outside_the_admin_channel(tourney):
    interaction = _slash_interaction(channel_id=1)

    await asyncio.sleep(0)  # let setup's resume task make its own session check
    checks_before = tourney.get_active_tourney_session.await_count

    await tourney.bot.tree.get_command("end-tourney").callback(interaction)

    assert f"<#{ADMIN_CHANNEL}>" in _reply_text(interaction)
    assert tourney.get_active_tourney_session.await_count == checks_before
    interaction.channel.send.assert_not_awaited()


# --- /close, /delete, /reopen route to every ticket type (#566) ---

import features.ticket_command_router as router  # noqa: E402

TOURNEY_CAT, CLOSED_CAT = 111, 222


@pytest.fixture
async def tickets(bot, monkeypatch):
    """Registered ticket commands with every per-type handler replaced by a mock."""
    import features.economy as economy
    import features.event_tickets as event_tickets
    import features.booster_shoutout as booster
    import features.support_tickets as support
    import features.tourney.tourney_commands as tc

    for name in (
        "is_redemption_ticket_channel",
        "is_booster_shoutout_ticket_channel",
        "is_support_ticket_channel",
    ):
        monkeypatch.setattr(router, name, lambda channel: False)
    monkeypatch.setattr(event_tickets, "is_event_ticket_channel", lambda c: False)

    handlers = {}
    targets = {
        "redemption": (
            economy,
            "close_redemption_ticket_via_command",
            "handle_redemption_delete_attempt",
            "reopen_redemption_ticket_via_command",
        ),
        "booster": (
            booster,
            "close_booster_shoutout_ticket_via_command",
            "delete_booster_shoutout_ticket_via_command",
            "reopen_booster_shoutout_ticket_via_command",
        ),
        "event": (
            event_tickets,
            "close_event_ticket_via_command",
            "delete_event_ticket_via_command",
            "reopen_event_ticket_via_command",
        ),
        "support": (
            support,
            "close_support_ticket_via_command",
            "delete_support_ticket_via_command",
            "reopen_support_ticket_via_command",
        ),
        "tourney": (
            tc,
            "close_ticket_via_command",
            "delete_ticket_via_command",
            "reopen_ticket_via_command",
        ),
    }
    for kind, (module, close, delete, reopen) in targets.items():
        for action, attr in (("close", close), ("delete", delete), ("reopen", reopen)):
            mock = AsyncMock()
            monkeypatch.setattr(module, attr, mock)
            handlers[(kind, action)] = mock

    monkeypatch.setattr(tc, "get_active_tourney_session", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "increment_staff_closure", AsyncMock())
    monkeypatch.setattr(tc, "update_tourney_queue", AsyncMock())
    monkeypatch.setattr(tc, "TOURNEY_CLOSED_CATEGORY_ID", CLOSED_CAT)
    monkeypatch.setattr(tc, "PRE_TOURNEY_CLOSED_CATEGORY_ID", CLOSED_CAT + 1)
    setup_tourney_commands(bot)
    return MagicMock(bot=bot, tc=tc, handlers=handlers, monkeypatch=monkeypatch)


def _ticket_interaction(category_id=TOURNEY_CAT):
    interaction = _slash_interaction()
    interaction.channel.category_id = category_id
    return interaction


def _mark(tickets, kind):
    """Make the router recognise the channel as this ticket type."""
    import features.event_tickets as event_tickets

    predicate = {
        "redemption": (router, "is_redemption_ticket_channel"),
        "booster": (router, "is_booster_shoutout_ticket_channel"),
        "event": (event_tickets, "is_event_ticket_channel"),
        "support": (router, "is_support_ticket_channel"),
    }.get(kind)
    if predicate:
        tickets.monkeypatch.setattr(*predicate, lambda channel: True)


async def _run(tickets, action, interaction):
    await tickets.bot.tree.get_command(action).callback(interaction)


@pytest.mark.parametrize("action", ["close", "delete", "reopen"])
@pytest.mark.parametrize(
    "kind", ["redemption", "booster", "event", "support", "tourney"]
)
async def test_each_ticket_type_gets_only_its_own_handler(tickets, kind, action):
    _mark(tickets, kind)
    interaction = _ticket_interaction(
        category_id=CLOSED_CAT if action == "reopen" else TOURNEY_CAT
    )

    await _run(tickets, action, interaction)

    for (other_kind, other_action), mock in tickets.handlers.items():
        if (other_kind, other_action) == (kind, action):
            mock.assert_awaited_once()
        else:
            mock.assert_not_awaited()


async def test_the_handler_receives_the_invoker_and_channel(tickets):
    _mark(tickets, "support")
    interaction = _ticket_interaction()

    await _run(tickets, "close", interaction)

    ctx = tickets.handlers[("support", "close")].await_args.args[0]
    assert ctx.author is interaction.user
    assert ctx.channel is interaction.channel


async def test_close_counts_a_staff_closure_during_an_active_session(tickets):
    tickets.tc.get_active_tourney_session.return_value = {"_id": 9}
    interaction = _ticket_interaction()

    await _run(tickets, "close", interaction)

    tickets.tc.increment_staff_closure.assert_awaited_once_with(9, 1, "staff")
    tickets.tc.update_tourney_queue.assert_awaited_once_with(9, change=-1)


async def test_close_without_a_session_leaves_stats_alone(tickets):
    await _run(tickets, "close", _ticket_interaction())

    tickets.tc.increment_staff_closure.assert_not_awaited()
    tickets.tc.update_tourney_queue.assert_not_awaited()


async def test_reopen_outside_a_closed_category_warns_privately(tickets):
    interaction = _ticket_interaction(category_id=TOURNEY_CAT)

    await _run(tickets, "reopen", interaction)

    assert "Closed Tourney Tickets" in _private_text(interaction)
    tickets.handlers[("tourney", "reopen")].assert_not_awaited()


async def test_ticket_commands_are_server_only(tickets):
    for name in ("close", "delete", "reopen"):
        assert tickets.bot.tree.get_command(name).guild_only is True


async def test_ticket_commands_defer_privately_first(tickets):
    interaction = _ticket_interaction()

    await _run(tickets, "close", interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)


async def test_redemption_delete_points_at_the_slash_commands():
    from features.economy import handle_redemption_delete_attempt

    ctx = MagicMock()
    ctx.reply = AsyncMock()

    await handle_redemption_delete_attempt(ctx)

    text = ctx.reply.await_args.args[0]
    assert "/delete" in text and "/close" in text
    assert "!" not in text


async def test_tourney_close_denies_non_staff_privately(bot, monkeypatch):
    """The real tourney handler's permission check still applies."""
    import features.tourney.tourney_commands as tc
    import features.tourney.tourney_utils as tu

    monkeypatch.setattr(tc, "get_active_tourney_session", AsyncMock(return_value=None))
    monkeypatch.setattr(tu, "_is_staff", lambda member: False)
    for name in (
        "is_redemption_ticket_channel",
        "is_booster_shoutout_ticket_channel",
        "is_support_ticket_channel",
    ):
        monkeypatch.setattr(router, name, lambda channel: False)
    import features.event_tickets as event_tickets

    monkeypatch.setattr(event_tickets, "is_event_ticket_channel", lambda c: False)
    setup_tourney_commands(bot)
    interaction = _ticket_interaction()

    await bot.tree.get_command("close").callback(interaction)

    assert "permission" in _private_text(interaction)


# --- restart safety: interrupted /start-tourney is flagged, /end-tourney report posts once ---


async def test_a_finished_start_marks_setup_complete(tourney):
    tourney.lock_command.side_effect = None
    tourney.get_active_tourney_session.side_effect = None
    tourney.get_active_tourney_session.return_value = None
    tourney.create_tourney_session.side_effect = lambda: (
        tourney.get_active_tourney_session.configure_mock(return_value={"_id": 7})
    )
    tourney.bot.get_cog = MagicMock(return_value=None)
    interaction = _slash_interaction()
    interaction.guild.get_channel = MagicMock(return_value=None)
    interaction.guild.get_role = MagicMock(return_value=None)

    await _start(tourney, interaction)

    calls = tourney.update_tourney_runtime_state.await_args_list
    assert calls[-1].args == (7,)
    assert calls[-1].kwargs == {"setup_complete": True}, "written as the last step"


async def test_an_interrupted_start_never_marks_setup_complete(tourney):
    tourney.get_active_tourney_session.side_effect = [None, {"_id": 7}]
    interaction = _slash_interaction()

    with pytest.raises(_StopHere):
        await _start(tourney, interaction)

    for call in tourney.update_tourney_runtime_state.await_args_list:
        assert call.kwargs.get("setup_complete") is not True


def _admin_bot(channel):
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)
    return bot


async def test_boot_warns_when_setup_was_interrupted(monkeypatch):
    import features.tourney.tourney_commands as tc

    monkeypatch.setattr(tc, "TOURNEY_ADMIN_CHANNEL_ID", ADMIN_CHANNEL)
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    bot = _admin_bot(channel)

    warned = await tc.warn_if_setup_interrupted(
        bot, {"_id": 7, "setup_complete": False}
    )

    assert warned is True
    bot.get_channel.assert_called_with(ADMIN_CHANNEL)
    text = channel.send.await_args.args[0]
    assert "/start-tourney" in text and "force" in text


@pytest.mark.parametrize("session", [{"_id": 7, "setup_complete": True}, {"_id": 7}])
async def test_boot_stays_quiet_for_a_completed_or_legacy_session(session):
    import features.tourney.tourney_commands as tc

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()

    warned = await tc.warn_if_setup_interrupted(_admin_bot(channel), session)

    assert warned is False
    channel.send.assert_not_awaited()


def _report_ctx(report_channel):
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.bot.get_channel = MagicMock(return_value=report_channel)
    return ctx


async def test_report_is_posted_and_recorded(monkeypatch):
    import features.tourney.tourney_commands as tc

    record = AsyncMock()
    monkeypatch.setattr(tc, "update_tourney_runtime_state", record)
    report_channel = MagicMock(spec=discord.TextChannel)
    report_channel.send = AsyncMock()
    ctx = _report_ctx(report_channel)
    embed = discord.Embed(title="stats")

    posted = await tc.post_session_report(ctx, {"_id": 7}, embed)

    assert posted is True
    ctx.send.assert_awaited_once_with(embed=embed)
    report_channel.send.assert_awaited_once_with(embed=embed)
    record.assert_awaited_once_with(7, report_posted=True)


async def test_rerun_after_a_restart_does_not_post_the_report_twice(monkeypatch):
    import features.tourney.tourney_commands as tc

    record = AsyncMock()
    monkeypatch.setattr(tc, "update_tourney_runtime_state", record)
    report_channel = MagicMock(spec=discord.TextChannel)
    report_channel.send = AsyncMock()
    ctx = _report_ctx(report_channel)

    posted = await tc.post_session_report(
        ctx, {"_id": 7, "report_posted": True}, discord.Embed(title="stats")
    )

    assert posted is False
    report_channel.send.assert_not_awaited()
    record.assert_not_awaited()
    assert "already" in ctx.send.await_args.args[0]
