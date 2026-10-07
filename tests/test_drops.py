"""Tests for pick_weighted_item and process_reward in features/brawl/drops.py."""

import random
from unittest.mock import AsyncMock, patch

import pytest

from features.brawl.drops import pick_weighted_item

LOOT_TABLE = [
    {"type": "coins", "amount": 100, "weight": 70},
    {"type": "power_points", "amount": 50, "weight": 25},
    {"type": "brawler", "rarity": "rare", "weight": 5},
]


def test_returns_item_from_table():
    result = pick_weighted_item(LOOT_TABLE)
    assert result in LOOT_TABLE


def test_single_item_table_always_returns_that_item():
    table = [{"type": "coins", "amount": 50, "weight": 1}]
    assert pick_weighted_item(table) == table[0]


def test_respects_weights():
    # With weight 100 vs 0, the heavy item should always win
    table = [
        {"type": "coins", "weight": 100},
        {"type": "brawler", "weight": 0},
    ]
    with patch(
        "features.brawl.drops.random.choices", wraps=random.choices
    ) as mock_choices:
        pick_weighted_item(table)
        _, kwargs = mock_choices.call_args
        assert kwargs["weights"] == [100, 0]


def test_result_has_expected_keys():
    result = pick_weighted_item(LOOT_TABLE)
    assert "type" in result
    assert "weight" in result


# --- process_reward currency writes (#481) ---


@pytest.mark.asyncio
@pytest.mark.parametrize("currency", ["coins", "power_points", "credits"])
async def test_a_currency_reward_credits_that_currency(currency):
    from features.brawl.drops import process_reward

    with patch("features.brawl.drops.add_currency", new=AsyncMock()) as add:
        await process_reward("42", {"type": currency, "amount": 75})

    add.assert_awaited_once_with("42", currency, 75)


@pytest.mark.asyncio
async def test_a_duplicate_brawler_pays_its_fallback_in_credits():
    from features.brawl.drops import process_reward

    with (
        patch(
            "features.brawl.drops.add_brawler_to_user",
            new=AsyncMock(return_value="duplicate"),
        ),
        patch("features.brawl.drops.add_currency", new=AsyncMock()) as add,
    ):
        result = await process_reward(
            "42", {"type": "brawler", "rarity": "rare", "fallback_credits": 120}
        )

    add.assert_awaited_once_with("42", "credits", 120)
    assert "120 Credits" in result


@pytest.mark.asyncio
async def test_an_ability_reward_with_no_eligible_brawler_pays_1000_coins():
    from features.brawl.drops import process_reward

    with (
        patch(
            "features.brawl.drops.get_user_data",
            new=AsyncMock(return_value={"brawlers": {}}),
        ),
        patch("features.brawl.drops.add_currency", new=AsyncMock()) as add,
    ):
        result = await process_reward("42", {"type": "gadget"})

    add.assert_awaited_once_with("42", "coins", 1000)
    assert "1,000 Coins" in result
