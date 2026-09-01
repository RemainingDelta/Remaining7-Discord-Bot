"""Tests for the `/brawler` single-brawler detail command (462-Feature).

Derived from the issue's Acceptance Criteria:
- `/brawler <name>` returns an embed listing that brawler's rarity and all of
  its gadgets, star powers, and hypercharge.
- For a brawler the caller owns, the embed shows the caller's current level and
  owned abilities; for an unowned brawler it clearly shows "not owned".
- An invalid/unknown brawler name returns an ephemeral error and does not raise.
- Autocomplete suggests brawler names sourced from `brawlers.json`.
"""

from unittest.mock import AsyncMock

import database.mongo as mongo
from features.brawl.brawlers import BRAWLER_ROSTER
from features.brawl.commands import BrawlCommands


def _embed_text(embed):
    """Flatten an embed's title, description, and all field name/values."""
    parts = [embed.title or "", embed.description or ""]
    for field in embed.fields:
        parts.append(field.name or "")
        parts.append(field.value or "")
    return "\n".join(parts)


def _colt():
    return next(b for b in BRAWLER_ROSTER if b.id == "colt")


# --- AC 1: rarity + all abilities are listed ---


async def test_brawler_lists_rarity_and_all_abilities(
    monkeypatch, mock_bot, mock_interaction
):
    colt = _colt()
    monkeypatch.setattr(
        mongo, "get_user_data", AsyncMock(return_value={"brawlers": {}})
    )

    cog = BrawlCommands(mock_bot)
    await cog.brawler_details.callback(cog, mock_interaction, "Colt")

    mock_interaction.followup.send.assert_awaited_once()
    embed = mock_interaction.followup.send.await_args.kwargs["embed"]
    text = _embed_text(embed)

    assert colt.rarity in text
    for gadget in colt.gadgets:
        assert gadget in text
    for sp in colt.star_powers:
        assert sp in text
    assert colt.hypercharge in text


# --- AC 2a: owned brawler shows level and owned abilities ---


async def test_owned_brawler_shows_level_and_owned_abilities(
    monkeypatch, mock_bot, mock_interaction
):
    colt = _colt()
    owned_gadget = colt.gadgets[0]
    unowned_gadget = colt.gadgets[1]
    monkeypatch.setattr(
        mongo,
        "get_user_data",
        AsyncMock(
            return_value={
                "brawlers": {
                    "colt": {
                        "level": 9,
                        "gadgets": [owned_gadget],
                        "star_powers": [],
                        "hypercharge": "",
                    }
                }
            }
        ),
    )

    cog = BrawlCommands(mock_bot)
    await cog.brawler_details.callback(cog, mock_interaction, "colt")

    embed = mock_interaction.followup.send.await_args.kwargs["embed"]
    text = _embed_text(embed)

    # Current level is shown.
    assert "9" in text
    # Both abilities are listed, but only the owned one is marked owned.
    owned_line = next(
        line for line in text.splitlines() if owned_gadget in line and "▫" not in line
    )
    assert "✅" in owned_line
    unowned_line = next(line for line in text.splitlines() if unowned_gadget in line)
    assert "✅" not in unowned_line


# --- AC 2b: unowned brawler clearly shows "not owned" ---


async def test_unowned_brawler_shows_not_owned(monkeypatch, mock_bot, mock_interaction):
    monkeypatch.setattr(
        mongo, "get_user_data", AsyncMock(return_value={"brawlers": {"shelly": {}}})
    )

    cog = BrawlCommands(mock_bot)
    await cog.brawler_details.callback(cog, mock_interaction, "Colt")

    embed = mock_interaction.followup.send.await_args.kwargs["embed"]
    text = _embed_text(embed).lower()
    assert "not owned" in text


# --- AC 3: invalid name -> ephemeral error, no raise ---


async def test_unknown_brawler_returns_ephemeral_error(
    monkeypatch, mock_bot, mock_interaction
):
    # get_user_data must never be reached for an unknown name.
    called = AsyncMock()
    monkeypatch.setattr(mongo, "get_user_data", called)

    cog = BrawlCommands(mock_bot)
    await cog.brawler_details.callback(cog, mock_interaction, "NotARealBrawler")

    mock_interaction.response.send_message.assert_awaited_once()
    kwargs = mock_interaction.response.send_message.await_args.kwargs
    assert kwargs.get("ephemeral") is True
    mock_interaction.followup.send.assert_not_awaited()
    called.assert_not_awaited()


# --- AC 4: autocomplete suggests names from brawlers.json ---


async def test_autocomplete_suggests_roster_names(mock_bot, mock_interaction):
    cog = BrawlCommands(mock_bot)
    choices = await cog.brawler_roster_autocomplete(mock_interaction, "col")

    names = [c.name for c in choices]
    assert "Colt" in names
    # Every suggestion must correspond to a real roster brawler.
    roster_names = {b.name for b in BRAWLER_ROSTER}
    assert all(name in roster_names for name in names)


async def test_autocomplete_is_capped_at_25(mock_bot, mock_interaction):
    cog = BrawlCommands(mock_bot)
    choices = await cog.brawler_roster_autocomplete(mock_interaction, "")
    assert len(choices) <= 25


async def test_autocomplete_matches_by_name_substring(mock_bot, mock_interaction):
    cog = BrawlCommands(mock_bot)
    choices = await cog.brawler_roster_autocomplete(mock_interaction, "shel")
    assert "Shelly" in [c.name for c in choices]
