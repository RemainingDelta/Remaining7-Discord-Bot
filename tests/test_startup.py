"""Tests for the cog-load and command-sync behaviour in main.py (issue #503).

One failing cog used to abort the whole load, and the global sync then deleted
the skipped cogs' commands from Discord.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from discord.ext import commands

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
