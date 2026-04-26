"""Tests for pick_weighted_item in features/brawl/drops.py."""

import random
from unittest.mock import patch

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
