"""Tests for pure functions in features/economy.py."""

from datetime import datetime

from features.economy import (
    _budget_month_key,
    _budget_cost_for_item,
    _token_price_for_item,
    _extract_topic_value,
)


# --- _budget_month_key ---


def test_budget_month_key_is_valid_format():
    key = _budget_month_key()
    datetime.strptime(key, "%Y-%m")  # raises ValueError if format is wrong


def test_budget_month_key_matches_current_month():
    key = _budget_month_key()
    expected = datetime.utcnow().strftime("%Y-%m")
    assert key == expected


# --- _budget_cost_for_item ---


def test_budget_cost_brawl_pass():
    assert _budget_cost_for_item("brawl pass") == 10.0


def test_budget_cost_brawl_pass_plus():
    assert _budget_cost_for_item("brawl pass+") == 15.0


def test_budget_cost_nitro():
    assert _budget_cost_for_item("nitro") == 10.0


def test_budget_cost_paypal():
    assert _budget_cost_for_item("paypal") == 15.0


def test_budget_cost_shoutout_is_free():
    assert _budget_cost_for_item("shoutout") == 0.0


def test_budget_cost_case_insensitive():
    assert _budget_cost_for_item("Brawl Pass") == 10.0
    assert _budget_cost_for_item("NITRO") == 10.0


def test_budget_cost_unknown_item_returns_zero():
    assert _budget_cost_for_item("nonexistent item xyz") == 0.0


# --- _token_price_for_item ---


def test_token_price_unknown_item_returns_zero():
    assert _token_price_for_item("this item does not exist") == 0


# --- _extract_topic_value ---


def test_extract_topic_value_single_key():
    assert (
        _extract_topic_value("redemption-opener:12345", "redemption-opener") == "12345"
    )


def test_extract_topic_value_with_multiple_parts():
    topic = "redemption-opener:12345|item:brawl pass|type:redemption"
    assert _extract_topic_value(topic, "item") == "brawl pass"
    assert _extract_topic_value(topic, "redemption-opener") == "12345"
    assert _extract_topic_value(topic, "type") == "redemption"


def test_extract_topic_value_key_not_present():
    assert _extract_topic_value("redemption-opener:12345", "missing") is None


def test_extract_topic_value_none_topic():
    assert _extract_topic_value(None, "key") is None


def test_extract_topic_value_empty_topic():
    assert _extract_topic_value("", "key") is None


def test_extract_topic_value_empty_value():
    # key is present but value is empty string
    assert _extract_topic_value("key:", "key") == ""
