"""Tests for pure functions in features/booster_shoutout.py."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import database.mongo as mongo
from database.mongo import claim_booster_shoutout_month
from features.booster_shoutout import (
    _extract_opener_id,
    _is_new_boost,
    _strip_status_prefix,
    _active_ticket_name,
    _closed_ticket_name,
    _current_month_key,
)


# --- _is_new_boost ---


def test_new_boost_none_to_datetime():
    assert _is_new_boost(None, datetime(2026, 7, 17)) is True


def test_no_boost_none_to_none():
    assert _is_new_boost(None, None) is False


def test_no_boost_datetime_to_datetime():
    assert _is_new_boost(datetime(2026, 6, 1), datetime(2026, 6, 1)) is False


def test_boost_ended_datetime_to_none():
    assert _is_new_boost(datetime(2026, 6, 1), None) is False


# --- _current_month_key ---


def test_current_month_key_format():
    key = _current_month_key()
    assert len(key) == 7
    year, month = key.split("-")
    assert year.isdigit() and month.isdigit()
    assert 1 <= int(month) <= 12


def test_current_month_key_matches_utcnow():
    assert _current_month_key() == datetime.utcnow().strftime("%Y-%m")


# --- _extract_opener_id ---


def test_extract_opener_id_simple():
    assert _extract_opener_id("booster-opener:123456789") == 123456789


def test_extract_opener_id_with_type_suffix():
    assert (
        _extract_opener_id("booster-opener:987654321|type:booster_shoutout")
        == 987654321
    )


def test_extract_opener_id_none_topic():
    assert _extract_opener_id(None) is None


def test_extract_opener_id_empty_string():
    assert _extract_opener_id("") is None


def test_extract_opener_id_key_missing():
    assert _extract_opener_id("support-opener:123|type:issues") is None


def test_extract_opener_id_non_numeric_value():
    assert _extract_opener_id("booster-opener:notanumber") is None


# --- name helpers ---


def test_strip_active_prefix():
    assert _strip_status_prefix("「❗」shoutout-001") == "shoutout-001"


def test_strip_closed_prefix():
    assert _strip_status_prefix("「👍」shoutout-001") == "shoutout-001"


def test_strip_no_prefix():
    assert _strip_status_prefix("shoutout-001") == "shoutout-001"


def test_active_ticket_name_from_closed():
    assert _active_ticket_name("「👍」shoutout-001") == "「❗」shoutout-001"


def test_closed_ticket_name_from_active():
    assert _closed_ticket_name("「❗」shoutout-001") == "「👍」shoutout-001"


def test_active_and_closed_are_inverses():
    original = "shoutout-042"
    assert _strip_status_prefix(_active_ticket_name(original)) == original
    assert _strip_status_prefix(_closed_ticket_name(original)) == original


# --- claim_booster_shoutout_month (atomic month-slot claim) ---


def _fake_users_db(find_one_and_update_return):
    """A db whose users.find_one returns an existing doc (so get_user_data doesn't
    insert) and whose find_one_and_update returns the given BEFORE doc / None."""
    db = MagicMock()
    db.users.find_one = AsyncMock(
        return_value={"_id": "u1", "brawlers": {"shelly": {"level": 1}}}
    )
    db.users.find_one_and_update = AsyncMock(return_value=find_one_and_update_return)
    return db


async def test_claim_month_won_returns_previous(monkeypatch):
    # find_one_and_update returns the BEFORE doc -> we claimed; prev surfaces for rollback.
    db = _fake_users_db({"_id": "u1", "booster_shoutout_month": "2026-07"})
    monkeypatch.setattr(mongo, "db", db)
    won, previous = await claim_booster_shoutout_month("u1", "2026-08")
    assert won is True
    assert previous == "2026-07"


async def test_claim_month_lost_when_already_claimed(monkeypatch):
    # None -> the $ne predicate excluded the doc -> already claimed this month.
    db = _fake_users_db(None)
    monkeypatch.setattr(mongo, "db", db)
    won, previous = await claim_booster_shoutout_month("u1", "2026-08")
    assert won is False
    assert previous is None


async def test_claim_month_uses_ne_predicate(monkeypatch):
    db = _fake_users_db({"_id": "u1"})
    monkeypatch.setattr(mongo, "db", db)
    await claim_booster_shoutout_month("u1", "2026-08")
    query, update = db.users.find_one_and_update.call_args.args
    assert query["booster_shoutout_month"] == {"$ne": "2026-08"}
    assert update["$set"]["booster_shoutout_month"] == "2026-08"
