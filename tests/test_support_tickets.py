"""Tests for features/support_tickets.py."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from database import mongo
from features import support_tickets
from features.support_tickets import (
    _extract_opener_id,
    _strip_status_prefix,
    _active_ticket_name,
    _closed_ticket_name,
)


# --- _extract_opener_id ---


def test_extract_opener_id_simple():
    assert _extract_opener_id("support-opener:123456789") == 123456789


def test_extract_opener_id_with_type_prefix():
    assert _extract_opener_id("type:issues|support-opener:987654321") == 987654321


def test_extract_opener_id_opener_first():
    assert _extract_opener_id("support-opener:111|type:server_support") == 111


def test_extract_opener_id_none_topic():
    assert _extract_opener_id(None) is None


def test_extract_opener_id_empty_string():
    assert _extract_opener_id("") is None


def test_extract_opener_id_key_missing():
    assert _extract_opener_id("type:issues|other:stuff") is None


def test_extract_opener_id_non_numeric_value():
    assert _extract_opener_id("support-opener:notanumber") is None


# --- _strip_status_prefix ---


def test_strip_active_prefix():
    assert _strip_status_prefix("「❗」ticket-001") == "ticket-001"


def test_strip_closed_prefix():
    assert _strip_status_prefix("「👍」ticket-001") == "ticket-001"


def test_strip_no_prefix():
    assert _strip_status_prefix("ticket-001") == "ticket-001"


def test_strip_custom_prefix():
    assert _strip_status_prefix("「🔒」ticket-042") == "ticket-042"


def test_strip_preserves_channel_name_with_numbers():
    assert _strip_status_prefix("「❗」ticket-123") == "ticket-123"


# --- _active_ticket_name ---


def test_active_ticket_name_from_closed():
    assert _active_ticket_name("「👍」ticket-001") == "「❗」ticket-001"


def test_active_ticket_name_no_prefix():
    assert _active_ticket_name("ticket-001") == "「❗」ticket-001"


def test_active_ticket_name_already_active_is_idempotent():
    # Applying active to an already-active name strips and re-applies
    assert _active_ticket_name("「❗」ticket-001") == "「❗」ticket-001"


# --- _closed_ticket_name ---


def test_closed_ticket_name_from_active():
    assert _closed_ticket_name("「❗」ticket-001") == "「👍」ticket-001"


def test_closed_ticket_name_no_prefix():
    assert _closed_ticket_name("ticket-001") == "「👍」ticket-001"


def test_closed_ticket_name_already_closed_is_idempotent():
    assert _closed_ticket_name("「👍」ticket-001") == "「👍」ticket-001"


def test_active_and_closed_are_inverses():
    original = "ticket-042"
    assert _strip_status_prefix(_active_ticket_name(original)) == original
    assert _strip_status_prefix(_closed_ticket_name(original)) == original


# --- get_next_support_ticket_number (issue #503) ---


@pytest.mark.asyncio
async def test_support_counter_returns_one_when_the_database_errors(monkeypatch):
    """A None here reaches an f-string format spec and raises TypeError before
    the ticket channel is created, so the error path must still yield an int."""
    fake_db = MagicMock()
    fake_db.support_ticket_counters.find_one_and_update = AsyncMock(
        side_effect=RuntimeError("connection reset")
    )
    monkeypatch.setattr(mongo, "db", fake_db)

    assert await mongo.get_next_support_ticket_number("issues") == 1


@pytest.mark.asyncio
async def test_support_counter_result_formats_into_a_channel_name(monkeypatch):
    """Guards the exact crash from #503: f"...{n:03d}" on the error path."""
    fake_db = MagicMock()
    fake_db.support_ticket_counters.find_one_and_update = AsyncMock(
        side_effect=RuntimeError("connection reset")
    )
    monkeypatch.setattr(mongo, "db", fake_db)

    number = await mongo.get_next_support_ticket_number("issues")

    assert f"「❗」ticket-{number:03d}" == "「❗」ticket-001"


# --- SupportTicketSelect.callback (issue #503) ---


def _select_interaction():
    """A selection that should reach channel creation."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.client = MagicMock()
    interaction.client.user = MagicMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 987654321

    category = MagicMock(spec=discord.CategoryChannel)
    category.channels = []

    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    channel.mention = "#ticket-001"

    guild = MagicMock(spec=discord.Guild)
    guild.get_channel = MagicMock(return_value=category)
    guild.get_role = MagicMock(return_value=None)
    guild.default_role = MagicMock()
    guild.create_text_channel = AsyncMock(return_value=channel)
    interaction.guild = guild

    return interaction, guild, channel


async def _run_callback(monkeypatch, interaction, value="issues"):
    monkeypatch.setattr(
        support_tickets, "get_next_support_ticket_number", AsyncMock(return_value=1)
    )
    select = support_tickets.SupportTicketSelect(MagicMock())
    monkeypatch.setattr(type(select), "values", property(lambda self: [value]))
    await select.callback(interaction)
    return select


@pytest.mark.asyncio
async def test_ticket_callback_defers_before_any_network_call(monkeypatch):
    """The 3s deadline: three round-trips used to run before the first ACK."""
    interaction, guild, _ = _select_interaction()
    order = []

    async def track_defer(*args, **kwargs):
        order.append("defer")

    async def track_counter(*args, **kwargs):
        order.append("counter")
        return 1

    async def track_create(*args, **kwargs):
        order.append("create_channel")
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        channel.mention = "#ticket-001"
        return channel

    interaction.response.defer = AsyncMock(side_effect=track_defer)
    monkeypatch.setattr(
        support_tickets,
        "get_next_support_ticket_number",
        AsyncMock(side_effect=track_counter),
    )
    guild.create_text_channel = AsyncMock(side_effect=track_create)

    select = support_tickets.SupportTicketSelect(MagicMock())
    monkeypatch.setattr(type(select), "values", property(lambda self: ["issues"]))
    await select.callback(interaction)

    assert order == ["defer", "counter", "create_channel"]


@pytest.mark.asyncio
async def test_ticket_channel_is_created_with_its_topic_in_one_call(monkeypatch):
    """A separate topic edit can fail and orphan the channel with no opener
    marker, hiding it from the duplicate check and breaking close/reopen."""
    interaction, guild, channel = _select_interaction()

    await _run_callback(monkeypatch, interaction)

    kwargs = guild.create_text_channel.await_args.kwargs
    assert kwargs["topic"] == "support-opener:987654321|type:issues"
    channel.edit.assert_not_called()


@pytest.mark.asyncio
async def test_ticket_callback_confirms_via_followup_not_response(monkeypatch):
    """After a defer the token is spent; send_message would raise."""
    interaction, _, _ = _select_interaction()

    await _run_callback(monkeypatch, interaction)

    interaction.followup.send.assert_awaited_once()
    assert "#ticket-001" in interaction.followup.send.await_args.args[0]
    interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfigured_category_replies_without_deferring(monkeypatch):
    """Cache-only rejections answer instantly and must not burn the defer."""
    interaction, guild, _ = _select_interaction()
    guild.get_channel = MagicMock(return_value=None)

    await _run_callback(monkeypatch, interaction)

    interaction.response.send_message.assert_awaited_once()
    interaction.response.defer.assert_not_awaited()
    guild.create_text_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_open_ticket_blocks_without_deferring(monkeypatch):
    interaction, guild, _ = _select_interaction()
    existing = MagicMock(spec=discord.TextChannel)
    existing.topic = "support-opener:987654321|type:issues"
    existing.name = "「❗」ticket-007"
    existing.mention = "#ticket-007"
    guild.get_channel.return_value.channels = [existing]

    await _run_callback(monkeypatch, interaction)

    interaction.response.send_message.assert_awaited_once()
    interaction.response.defer.assert_not_awaited()
    guild.create_text_channel.assert_not_awaited()
