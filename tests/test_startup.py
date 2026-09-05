"""Tests for the cog-load and command-sync behaviour in main.py (issue #503).

One failing cog used to abort the whole load, and the global sync then deleted
the skipped cogs' commands from Discord.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import time
from discord.ext import commands, tasks

import main


# --- FEATURE_EXTENSIONS ---


def test_feature_extensions_lists_every_feature_in_load_order():
    assert [module for module, _ in main.FEATURE_EXTENSIONS] == [
        "features.general",
        "features.economy",
        "features.event",
        "features.security",
        "features.scam_detection",
        "features.brawl.commands",
        "features.quests",
        "features.translation",
        "features.support_tickets",
        "features.booster_shoutout",
        "features.github_tickets",
        "features.sticky",
        "features.counting",
        "features.story",
        "features.message_mirror",
        "features.tourney.tourney_reports",
        "features.privacy_policy",
    ]


# --- load_features ---


@pytest.mark.asyncio
async def test_failing_cog_does_not_stop_the_cogs_after_it(monkeypatch):
    """The #503 regression: scam_detection raised and took 12 cogs with it."""
    attempted = []

    async def fake_load(module):
        attempted.append(module)
        if module == "features.scam_detection":
            raise RuntimeError("boom")

    monkeypatch.setattr(main.bot, "load_extension", fake_load)

    failed = await main.load_features()

    assert attempted == [module for module, _ in main.FEATURE_EXTENSIONS]
    assert "features.support_tickets" in attempted
    assert failed == ["Scam Detection"]


@pytest.mark.asyncio
async def test_every_cog_loads_when_none_raise(monkeypatch):
    monkeypatch.setattr(main.bot, "load_extension", AsyncMock())
    assert await main.load_features() == []


@pytest.mark.asyncio
async def test_already_loaded_on_reconnect_is_not_a_failure(monkeypatch):
    """on_ready re-fires on every reconnect; the cogs are already loaded."""

    async def fake_load(module):
        raise commands.ExtensionAlreadyLoaded(module)

    monkeypatch.setattr(main.bot, "load_extension", fake_load)

    assert await main.load_features() == []


@pytest.mark.asyncio
async def test_failure_is_logged_with_exception_type_and_traceback(monkeypatch, capsys):
    async def fake_load(module):
        if module == "features.story":
            raise ImportError("libGL.so.1: cannot open shared object file")

    monkeypatch.setattr(main.bot, "load_extension", fake_load)

    await main.load_features()

    out = capsys.readouterr().out
    assert "Story" in out
    assert "ImportError" in out
    assert "libGL.so.1" in out


@pytest.mark.asyncio
async def test_several_failures_are_all_reported(monkeypatch):
    async def fake_load(module):
        if module in ("features.quests", "features.counting"):
            raise RuntimeError("boom")

    monkeypatch.setattr(main.bot, "load_extension", fake_load)

    assert await main.load_features() == ["Quests", "Counting"]


# --- sync_commands ---


def _named(names):
    """MagicMock treats `name` as its own kwarg, so use plain objects."""
    return [SimpleNamespace(name=n) for n in names]


def _tree(monkeypatch, *, local, remote=None, fetch_raises=None):
    tree = MagicMock()
    tree.get_commands = MagicMock(return_value=_named(local))
    if fetch_raises is not None:
        tree.fetch_commands = AsyncMock(side_effect=fetch_raises)
    else:
        tree.fetch_commands = AsyncMock(return_value=_named(remote or []))
    tree.sync = AsyncMock(return_value=_named(local))
    # Client.tree is a read-only property, so patch it on the class.
    monkeypatch.setattr(type(main.bot), "tree", property(lambda self: tree))
    return tree


@pytest.mark.asyncio
async def test_sync_runs_when_nothing_failed(monkeypatch):
    tree = _tree(monkeypatch, local=["support-panel", "daily"])

    await main.sync_commands([])

    tree.sync.assert_awaited_once()
    tree.fetch_commands.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_skipped_when_it_would_delete_a_command(monkeypatch):
    """The #503 data loss: a partial tree wiped 20 commands from Discord."""
    tree = _tree(
        monkeypatch,
        local=["daily"],
        remote=["daily", "support-panel", "story-start"],
    )

    await main.sync_commands(["Scam Detection"])

    tree.sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_skipped_sync_names_the_commands_it_would_have_deleted(
    monkeypatch, capsys
):
    _tree(monkeypatch, local=["daily"], remote=["daily", "support-panel"])

    await main.sync_commands(["Scam Detection"])

    out = capsys.readouterr().out
    assert "support-panel" in out
    assert "Scam Detection" in out


@pytest.mark.asyncio
async def test_sync_proceeds_when_additive_despite_a_failure(monkeypatch):
    """scam_detection has no slash commands, so its failure must not block."""
    tree = _tree(
        monkeypatch,
        local=["daily", "support-panel"],
        remote=["daily"],
    )

    await main.sync_commands(["Scam Detection"])

    tree.sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_proceeds_when_tree_matches_remote_exactly(monkeypatch):
    tree = _tree(monkeypatch, local=["daily"], remote=["daily"])

    await main.sync_commands(["Scam Detection"])

    tree.sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_skipped_when_remote_commands_cannot_be_read(monkeypatch):
    """Cannot prove the sync is safe, so do not risk it."""
    tree = _tree(
        monkeypatch,
        local=["daily"],
        remote=None,
        fetch_raises=RuntimeError("429"),
    )

    await main.sync_commands(["Scam Detection"])

    tree.sync.assert_not_awaited()


# --- startup failure capture (issue #514) ---


@pytest.mark.asyncio
async def test_cog_failure_detail_is_captured(monkeypatch):
    async def fake_load(module):
        if module == "features.scam_detection":
            raise ImportError("libxcb.so.1: cannot open shared object file")

    monkeypatch.setattr(main.bot, "load_extension", fake_load)

    await main.load_features()

    assert len(main.STARTUP_FAILURES) == 1
    failure = main.STARTUP_FAILURES[0]
    assert failure.label == "Scam Detection"
    assert failure.source == "features.scam_detection"
    assert "libxcb" in str(failure.exception)
    assert "ImportError" in failure.traceback


@pytest.mark.asyncio
async def test_capture_is_cleared_between_runs(monkeypatch):
    async def failing(module):
        raise RuntimeError("boom")

    monkeypatch.setattr(main.bot, "load_extension", failing)
    await main.load_features()
    assert main.STARTUP_FAILURES

    async def clean(module):
        return None

    monkeypatch.setattr(main.bot, "load_extension", clean)
    await main.load_features()
    assert main.STARTUP_FAILURES == []


@pytest.mark.asyncio
async def test_already_loaded_is_not_captured(monkeypatch):
    async def already(module):
        raise commands.ExtensionAlreadyLoaded(module)

    monkeypatch.setattr(main.bot, "load_extension", already)

    await main.load_features()

    assert main.STARTUP_FAILURES == []


def test_record_failure_captures_label_source_and_traceback():
    """Tourney setup and the privacy repost are not cogs but must still report."""
    main.STARTUP_FAILURES.clear()
    try:
        raise ValueError("nope")
    except ValueError as e:
        main.record_failure("Tournaments", "features.tourney.tourney_commands", e)

    failure = main.STARTUP_FAILURES[0]
    assert failure.label == "Tournaments"
    assert failure.source == "features.tourney.tourney_commands"
    assert "nope" in str(failure.exception)
    assert "ValueError" in failure.traceback


# --- sync_commands return value ---


@pytest.mark.asyncio
async def test_sync_returns_the_number_of_commands_synced(monkeypatch):
    monkeypatch.setattr(main.bot.tree, "sync", AsyncMock(return_value=[1, 2, 3]))

    assert await main.sync_commands([]) == 3


@pytest.mark.asyncio
async def test_sync_returns_none_when_skipped(monkeypatch):
    monkeypatch.setattr(
        main.bot.tree,
        "fetch_commands",
        AsyncMock(return_value=[SimpleNamespace(name="gone")]),
    )
    monkeypatch.setattr(main.bot.tree, "get_commands", lambda: [])

    assert await main.sync_commands(["Scam Detection"]) is None


# --- report_startup_to_discord ---


def _bot_logs(monkeypatch, channel):
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)
    monkeypatch.setattr(main, "_STARTUP_REPORTED", False)


def _text_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


@pytest.mark.asyncio
async def test_healthy_boot_posts_a_summary_with_no_attachment(monkeypatch):
    channel = _text_channel()
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=17, synced=72)

    kwargs = channel.send.await_args.kwargs
    summary = kwargs["embeds"][0]
    rendered = " ".join(f"{f.name} {f.value}" for f in summary.fields)
    assert "17/17" in rendered
    assert "72" in rendered
    assert kwargs["file"] is None


@pytest.mark.asyncio
async def test_failure_is_named_and_traceback_attached(monkeypatch):
    channel = _text_channel()
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES[:] = [
        main.StartupFailure(
            "Scam Detection",
            "features.scam_detection",
            ImportError("libxcb.so.1"),
            "LINE " * 800,
        )
    ]

    await main.report_startup_to_discord(loaded=16, synced=72)

    kwargs = channel.send.await_args.kwargs
    rendered = " ".join(
        f"{e.title} " + " ".join(f"{f.name} {f.value}" for f in e.fields)
        for e in kwargs["embeds"]
    )
    assert "Scam Detection" in rendered
    assert "libxcb.so.1" in rendered
    assert kwargs["file"].filename == "startup_failures.txt"
    assert b"LINE" in kwargs["file"].fp.getvalue()


@pytest.mark.asyncio
async def test_summary_is_posted_once_per_process_not_per_reconnect(monkeypatch):
    """on_ready re-fires on every gateway reconnect."""
    channel = _text_channel()
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=17, synced=72)
    await main.report_startup_to_discord(loaded=17, synced=72)
    await main.report_startup_to_discord(loaded=17, synced=72)

    assert channel.send.await_count == 1


@pytest.mark.asyncio
async def test_report_no_ops_when_channel_is_missing(monkeypatch):
    _bot_logs(monkeypatch, None)
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=17, synced=72)  # must not raise


@pytest.mark.asyncio
async def test_report_no_ops_when_channel_is_not_a_text_channel(monkeypatch):
    _bot_logs(monkeypatch, MagicMock(spec=discord.VoiceChannel))
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=17, synced=72)  # must not raise


@pytest.mark.asyncio
async def test_report_no_ops_when_channel_id_is_unconfigured(monkeypatch):
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 0)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)
    monkeypatch.setattr(main, "_STARTUP_REPORTED", False)

    await main.report_startup_to_discord(loaded=17, synced=72)

    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failing_send_does_not_break_startup(monkeypatch):
    channel = _text_channel()
    channel.send = AsyncMock(side_effect=RuntimeError("Missing Permissions"))
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=17, synced=72)  # must swallow

    assert main._STARTUP_REPORTED is False


@pytest.mark.asyncio
async def test_a_skipped_sync_is_reported_as_not_synced(monkeypatch):
    channel = _text_channel()
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=16, synced=None)

    summary = channel.send.await_args.kwargs["embeds"][0]
    assert "not synced" in " ".join(f.value for f in summary.fields)


# --- runtime error reporting (issue #514) ---


@pytest.fixture(autouse=False)
def _clean_error_state():
    main._error_last_sent.clear()
    main._error_recent_sends.clear()
    yield
    main._error_last_sent.clear()
    main._error_recent_sends.clear()


def _boom(message="boom", exc_type=RuntimeError):
    try:
        raise exc_type(message)
    except exc_type as e:
        return e


@pytest.mark.asyncio
async def test_runtime_error_is_posted_with_traceback_attached(
    monkeypatch, _clean_error_state
):
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    await main.report_error("command /daily", _boom("kaboom"))

    kwargs = channel.send.await_args.kwargs
    rendered = " ".join(f"{f.name} {f.value}" for f in kwargs["embeds"][0].fields)
    assert "command /daily" in rendered
    assert "kaboom" in rendered
    assert kwargs["file"].filename == "error.txt"


@pytest.mark.asyncio
async def test_the_same_error_is_not_reposted_within_the_dedup_window(
    monkeypatch, _clean_error_state
):
    """A task failing every minute must not post 1,440 messages a day."""
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    for _ in range(4):
        await main.report_error("task Quests.reconcile", _boom("same"))

    assert channel.send.await_count == 1


@pytest.mark.asyncio
async def test_distinct_errors_are_reported_up_to_the_burst_limit(
    monkeypatch, _clean_error_state
):
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    for i in range(10):
        await main.report_error(f"command /cmd{i}", _boom(f"error {i}"))

    assert channel.send.await_count == main._ERROR_BURST_LIMIT


@pytest.mark.asyncio
async def test_command_errors_report_the_original_not_the_wrapper(
    monkeypatch, _clean_error_state
):
    """CommandInvokeError wraps the real exception; the wrapper is not useful."""
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    original = _boom("the real problem", ValueError)
    wrapper = commands.CommandInvokeError(original)

    await main.report_error("command !thing", wrapper)

    rendered = " ".join(
        f"{f.name} {f.value}"
        for f in channel.send.await_args.kwargs["embeds"][0].fields
    )
    assert "the real problem" in rendered
    assert "ValueError" in rendered


@pytest.mark.asyncio
async def test_a_failing_send_does_not_propagate(monkeypatch, _clean_error_state):
    channel = _text_channel()
    channel.send = AsyncMock(side_effect=RuntimeError("Missing Permissions"))
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    await main.report_error("command /daily", _boom())  # must not raise

    assert main._REPORTING_ERROR is False


@pytest.mark.asyncio
async def test_reporting_is_not_reentrant(monkeypatch, _clean_error_state):
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)
    monkeypatch.setattr(main, "_REPORTING_ERROR", True)

    await main.report_error("command /daily", _boom())

    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_error_no_ops_when_channel_unconfigured(
    monkeypatch, _clean_error_state
):
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 0)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    await main.report_error("command /daily", _boom())

    channel.send.assert_not_awaited()


def test_dedup_entries_are_pruned_so_the_map_cannot_grow_forever(_clean_error_state):
    now = time.time()
    main._error_last_sent["stale"] = now - main._ERROR_DEDUP_SECONDS - 1

    main._should_report_error("fresh", now)

    assert "stale" not in main._error_last_sent


def test_every_background_task_gets_an_error_handler():
    """A tasks.Loop that raises stops looping and only logs — 19 of them exist."""

    class FakeCog:
        @tasks.loop(seconds=60)
        async def my_task(self):
            pass

    cog = FakeCog()
    default_handler = cog.my_task._error

    main.attach_task_error_reporting([cog])

    assert cog.my_task._error is not default_handler


@pytest.mark.asyncio
async def test_a_task_error_handler_reports_the_exception(monkeypatch):
    """discord.py passes (cog, exception) for a bound loop."""
    reported = []

    async def fake_report(source, error):
        reported.append((source, error))

    monkeypatch.setattr(main, "report_error", fake_report)
    handler = main._task_error_handler("task FakeCog.my_task")

    boom = RuntimeError("task died")
    await handler(object(), boom)

    assert reported == [("task FakeCog.my_task", boom)]


# --- severity, explanations and embeds (issue #514) ---
#
# Written before the implementation, from the severity table and explanation
# list agreed in the plan. The mapping is a judgement call, so these assertions
# come from that table rather than from whatever the code ends up doing.


@pytest.mark.parametrize(
    "source, error, expected",
    [
        ("Scam Detection", ImportError("libxcb"), main.CRITICAL),
        ("task QueueDashboard.refresh", RuntimeError("died"), main.CRITICAL),
        ("command /daily", RuntimeError("boom"), main.ERROR),
        ("event on_message", RuntimeError("boom"), main.ERROR),
    ],
)
def test_severity_is_derived_from_the_source(source, error, expected):
    """Something no longer running is Critical; one failed interaction is not."""
    assert main.classify_severity(source, error) is expected


def test_permission_problems_are_a_warning_not_a_bug(monkeypatch):
    """A missing permission is a config problem, and must read differently."""
    forbidden = discord.Forbidden.__new__(discord.Forbidden)
    Exception.__init__(forbidden, "Missing Permissions")

    assert main.classify_severity("command /daily", forbidden) is main.WARNING
    assert main.classify_severity("task Something.loop", forbidden) is main.WARNING


def test_each_severity_has_its_own_colour():
    colours = {
        main.CRITICAL.colour,
        main.ERROR.colour,
        main.WARNING.colour,
        main.INFO.colour,
    }
    assert len(colours) == 4
    assert main.CRITICAL.colour == discord.Color.dark_red()
    assert main.ERROR.colour == discord.Color.red()
    assert main.WARNING.colour == discord.Color.orange()
    assert main.INFO.colour == discord.Color.green()


def test_a_known_error_gets_a_plain_english_explanation():
    explanation = main.explain_error(ModuleNotFoundError("no module named cv2"))
    assert "package" in explanation.lower()
    assert "cv2" not in explanation, "the explanation is generic, not the raw error"


def test_forbidden_is_explained_as_permissions_not_as_a_generic_http_error():
    """discord.Forbidden subclasses HTTPException, so ordering decides this."""
    forbidden = discord.Forbidden.__new__(discord.Forbidden)
    Exception.__init__(forbidden, "Missing Permissions")

    assert "permission" in main.explain_error(forbidden).lower()


def test_an_unknown_error_gets_an_honest_fallback():
    class SomethingNobodyPlannedFor(Exception):
        pass

    explanation = main.explain_error(SomethingNobodyPlannedFor("?"))

    assert "traceback" in explanation.lower() or "unexpected" in explanation.lower()


def test_error_embed_carries_source_explanation_and_original_error():
    embed = main.build_error_embed(
        "task QueueDashboard.refresh", ZeroDivisionError("dashboard blew up")
    )
    rendered = f"{embed.title} {embed.description or ''} " + " ".join(
        f"{f.name} {f.value}" for f in embed.fields
    )

    assert "QueueDashboard.refresh" in rendered
    assert "ZeroDivisionError" in rendered
    assert "dashboard blew up" in rendered, "the original error must survive"
    assert "bug" in rendered.lower(), "and be explained in plain English"
    assert embed.color == main.CRITICAL.colour


@pytest.mark.asyncio
async def test_healthy_boot_sends_one_info_embed_and_no_attachment(monkeypatch):
    channel = _text_channel()
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES.clear()

    await main.report_startup_to_discord(loaded=17, synced=72)

    kwargs = channel.send.await_args.kwargs
    assert len(kwargs["embeds"]) == 1
    assert kwargs["embeds"][0].color == main.INFO.colour
    assert kwargs["file"] is None


@pytest.mark.asyncio
async def test_boot_with_failures_sends_a_summary_plus_one_embed_each(monkeypatch):
    channel = _text_channel()
    _bot_logs(monkeypatch, channel)
    main.STARTUP_FAILURES[:] = [
        main.StartupFailure(
            "Scam Detection", "features.scam_detection", "ImportError('x')", "tb"
        ),
        main.StartupFailure(
            "Tournaments", "features.tourney", "RuntimeError('y')", "tb"
        ),
    ]

    await main.report_startup_to_discord(loaded=15, synced=72)

    kwargs = channel.send.await_args.kwargs
    assert len(kwargs["embeds"]) == 3, "summary + one per failure"
    assert kwargs["file"].filename == "startup_failures.txt"


@pytest.mark.asyncio
async def test_runtime_error_is_sent_as_an_embed(monkeypatch, _clean_error_state):
    channel = _text_channel()
    monkeypatch.setattr(main, "BOT_LOGS_CHANNEL_ID", 12345)
    monkeypatch.setattr(main.bot, "get_channel", lambda _id: channel)

    await main.report_error("command /daily", _boom("kaboom"))

    kwargs = channel.send.await_args.kwargs
    assert kwargs.get("content") in (None, "")
    assert len(kwargs["embeds"]) == 1
    assert kwargs["file"].filename == "error.txt"


@pytest.mark.asyncio
async def test_task_attachment_survives_an_awkward_cog():
    """It walks real cog attributes, so a descriptor that raises must not abort."""

    class AwkwardCog:
        @property
        def explodes(self):
            raise RuntimeError("do not touch me")

        @tasks.loop(seconds=60)
        async def my_task(self):
            pass

    cog = AwkwardCog()
    main.attach_task_error_reporting([cog])

    assert cog.my_task._error.__name__ == "handler"
