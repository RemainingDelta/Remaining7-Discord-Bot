"""Tests for issue #481: removal of dead DB helpers and write-only settings.

Derived from the Acceptance Criteria: the dead helpers must no longer exist,
the always-zero `gems` currency must be gone, and the write-only redeem-count
machinery (including the orphan `pin_redeemed_count`) must be removed.
"""

import inspect

import database.mongo as mongo
import features.economy as economy


# --- AC: dead DB helpers no longer exist ---


def test_set_booster_discount_month_removed():
    assert not hasattr(mongo, "set_booster_discount_month")


def test_deduct_coins_removed():
    assert not hasattr(mongo, "deduct_coins")


def test_add_brawl_gems_removed():
    assert not hasattr(mongo, "add_brawl_gems")


def test_kept_siblings_still_present():
    # The live siblings that share prefixes must survive the removal.
    assert hasattr(mongo, "get_booster_discount_month")
    assert hasattr(mongo, "deduct_credits")
    assert hasattr(mongo, "add_brawl_coins")
    assert hasattr(mongo, "add_credits")


# --- AC: gems currency is gone (no longer an always-zero field) ---


def test_gems_not_in_currency_defaults():
    src = inspect.getsource(mongo)
    assert "gems" not in src


# --- AC: redeem-count write machinery removed ---


def test_increment_redeem_counter_removed():
    assert not hasattr(economy, "_increment_redeem_counter")


def test_redeemed_count_keys_gone():
    src = inspect.getsource(economy)
    assert "redeemed_count" not in src
