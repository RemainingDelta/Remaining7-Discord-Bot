"""Tests for issue #460: /perm grants must survive a bot restart.

Derived from the Acceptance Criteria, not the implementation:
- A user granted via `/perm add` still passes has_permission after a restart.
- A user revoked via `/perm remove` stays revoked after a restart.
- Grants are stored in a MongoDB-backed setting and reloaded on startup.
- Revocation removes the persisted record, not just the in-memory entry.

A "restart" is simulated by clearing the in-memory ``allowed_users`` set and
reloading it from the (mocked) MongoDB settings store, exactly as a fresh
process would when the cog loads.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

import discord

import features.economy as economy
from features.economy import Economy, allowed_users


@pytest.fixture(autouse=True)
def clear_allowed_users():
    """Keep the module-level grant set from leaking between tests."""
    allowed_users.clear()
    yield
    allowed_users.clear()


@pytest.fixture
def settings_store(monkeypatch):
    """A fake persistent settings store shared across simulated restarts."""
    store = {}

    async def fake_get(key, default=None):
        return store.get(key, default)

    async def fake_set(key, value):
        store[key] = value

    monkeypatch.setattr(economy, "get_setting", fake_get)
    monkeypatch.setattr(economy, "set_setting", fake_set)
    return store


def _make_cog():
    cog = Economy.__new__(Economy)  # skip __init__ so task loops don't start
    cog.bot = MagicMock()
    return cog


def _make_admin_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 1
    interaction.user.get_role = MagicMock(return_value=MagicMock())  # holds ADMIN role
    return interaction


def _make_target_member(user_id):
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.mention = f"<@{user_id}>"
    return member


def _make_target_interaction(user_id):
    """An interaction whose invoking user is the granted/revoked member and who
    does NOT hold the admin role (so access can only come from a /perm grant)."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = user_id
    interaction.user.get_role = MagicMock(return_value=None)
    return interaction


async def _simulate_restart(cog):
    """Drop all in-memory state and rehydrate from the settings store, exactly
    as the cog does on startup."""
    allowed_users.clear()
    await economy._load_allowed_users()


async def test_grant_survives_restart(settings_store):
    cog = _make_cog()
    target = _make_target_member(555)

    await Economy.perm.callback(cog, _make_admin_interaction(), target, "add")

    await _simulate_restart(cog)

    assert await cog.has_permission(_make_target_interaction(555)) is True


async def test_revocation_survives_restart(settings_store):
    cog = _make_cog()
    target = _make_target_member(555)

    await Economy.perm.callback(cog, _make_admin_interaction(), target, "add")
    await Economy.perm.callback(cog, _make_admin_interaction(), target, "remove")

    await _simulate_restart(cog)

    assert await cog.has_permission(_make_target_interaction(555)) is False


async def test_grant_is_persisted_to_settings(settings_store):
    cog = _make_cog()
    target = _make_target_member(555)

    await Economy.perm.callback(cog, _make_admin_interaction(), target, "add")

    # Some setting now records the grant persistently.
    assert any("555" in str(value) for value in settings_store.values())


async def test_revocation_removes_persisted_record(settings_store):
    cog = _make_cog()
    target = _make_target_member(555)

    await Economy.perm.callback(cog, _make_admin_interaction(), target, "add")
    # The grant was persisted...
    assert any("555" in str(value) for value in settings_store.values())

    await Economy.perm.callback(cog, _make_admin_interaction(), target, "remove")
    # ...and revocation removes the persisted record, not just the memory entry.
    assert all("555" not in str(value) for value in settings_store.values())


async def test_load_populates_in_memory_set(settings_store):
    cog = _make_cog()
    target = _make_target_member(777)

    await Economy.perm.callback(cog, _make_admin_interaction(), target, "add")

    await _simulate_restart(cog)

    assert 777 in allowed_users
