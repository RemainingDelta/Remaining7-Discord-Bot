"""Tests for the user-document helpers in database/mongo.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import database.mongo as mongo


def _fake_db(existing=None):
    db = MagicMock()
    db.users.find_one = AsyncMock(return_value=existing)
    db.users.insert_one = AsyncMock()
    db.users.update_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_a_new_user_starts_with_exactly_coins_power_points_and_credits():
    # #481: gems was initialised but could never be earned, so it is not created.
    db = _fake_db()
    with patch.object(mongo, "db", db):
        user = await mongo.get_user_data("42")

    inserted = db.users.insert_one.await_args.args[0]
    assert inserted["currencies"] == {"coins": 100, "power_points": 0, "credits": 0}
    assert user == inserted


@pytest.mark.asyncio
@pytest.mark.parametrize("currency", ["coins", "power_points", "credits"])
async def test_add_currency_increments_that_currency(currency):
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.add_currency("42", currency, 250)

    db.users.update_one.assert_awaited_once_with(
        {"_id": "42"}, {"$inc": {f"currencies.{currency}": 250}}
    )


@pytest.mark.asyncio
async def test_add_currency_can_deduct():
    db = _fake_db()
    with patch.object(mongo, "db", db):
        await mongo.add_currency("42", "credits", -100)

    db.users.update_one.assert_awaited_once_with(
        {"_id": "42"}, {"$inc": {"currencies.credits": -100}}
    )


@pytest.mark.asyncio
async def test_add_currency_rejects_an_unknown_currency_without_writing():
    db = _fake_db()
    with patch.object(mongo, "db", db), pytest.raises(ValueError, match="gems"):
        await mongo.add_currency("42", "gems", 10)

    db.users.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_currency_is_a_no_op_without_a_database():
    with patch.object(mongo, "db", None):
        await mongo.add_currency("42", "coins", 10)
