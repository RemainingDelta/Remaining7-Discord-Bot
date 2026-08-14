"""Tests for the atomic Brawl purchase helpers (418-Bug).

`purchase_brawler_ability` and `purchase_brawler` each fold the currency deduct
and the item grant into a SINGLE `db.users.update_one`, mirroring
`upgrade_brawler_level`, so a crash between the two former writes can no longer
spend currency without granting the item. These tests assert exactly that: one
update carries both the currency `$inc` and the grant, and that an unaffordable
purchase writes nothing.
"""

from unittest.mock import AsyncMock, MagicMock

import database.mongo as mongo
from database.mongo import purchase_brawler, purchase_brawler_ability


def _patch(monkeypatch, user_doc):
    """Point mongo at a mock db and a stubbed get_user_data returning user_doc."""
    db = MagicMock()
    db.users.update_one = AsyncMock()
    monkeypatch.setattr(mongo, "db", db)
    monkeypatch.setattr(mongo, "get_user_data", AsyncMock(return_value=user_doc))
    return db


# --- purchase_brawler_ability ---


async def test_ability_gadget_deducts_and_grants_in_one_write(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"coins": 5000}})

    ok = await purchase_brawler_ability("u1", "shelly", "gadget", "Fast Forward", 2000)

    assert ok is True
    db.users.update_one.assert_awaited_once()
    _, update = db.users.update_one.await_args.args
    # Same update document carries both the deduct and the grant → atomic.
    assert update["$inc"] == {"currencies.coins": -2000}
    assert update["$addToSet"] == {"brawlers.shelly.gadgets": "Fast Forward"}


async def test_ability_star_power_uses_addtoset(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"coins": 5000}})

    ok = await purchase_brawler_ability("u1", "colt", "star_power", "Slick Boots", 2000)

    assert ok is True
    _, update = db.users.update_one.await_args.args
    assert update["$inc"] == {"currencies.coins": -2000}
    assert update["$addToSet"] == {"brawlers.colt.star_powers": "Slick Boots"}


async def test_ability_hypercharge_uses_set(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"coins": 5000}})

    ok = await purchase_brawler_ability(
        "u1", "colt", "hypercharge", "Bullet Storm", 4000
    )

    assert ok is True
    _, update = db.users.update_one.await_args.args
    assert update["$inc"] == {"currencies.coins": -4000}
    assert update["$set"] == {"brawlers.colt.hypercharge": "Bullet Storm"}


async def test_ability_insufficient_coins_writes_nothing(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"coins": 100}})

    ok = await purchase_brawler_ability("u1", "shelly", "gadget", "Fast Forward", 2000)

    assert ok is False
    db.users.update_one.assert_not_awaited()


async def test_ability_unknown_type_writes_nothing(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"coins": 5000}})

    ok = await purchase_brawler_ability("u1", "shelly", "banana", "Nope", 100)

    assert ok is False
    db.users.update_one.assert_not_awaited()


# --- purchase_brawler ---


async def test_brawler_new_deducts_and_grants_in_one_write(monkeypatch):
    db = _patch(
        monkeypatch, {"currencies": {"credits": 500}, "brawlers": {"shelly": {}}}
    )

    result = await purchase_brawler("u1", "colt", 100)

    assert result == "new"
    db.users.update_one.assert_awaited_once()
    _, update = db.users.update_one.await_args.args
    assert update["$inc"] == {"currencies.credits": -100}
    assert update["$set"]["brawlers.colt"]["level"] == 1


async def test_brawler_duplicate_grants_power_points(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"credits": 500}, "brawlers": {"colt": {}}})

    result = await purchase_brawler("u1", "colt", 100)

    assert result == "duplicate"
    _, update = db.users.update_one.await_args.args
    # One write both deducts credits and grants the +15 PP fallback.
    assert update["$inc"] == {"currencies.credits": -100, "currencies.power_points": 15}


async def test_brawler_insufficient_credits_writes_nothing(monkeypatch):
    db = _patch(monkeypatch, {"currencies": {"credits": 50}, "brawlers": {}})

    result = await purchase_brawler("u1", "colt", 100)

    assert result is False
    db.users.update_one.assert_not_awaited()
