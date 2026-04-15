"""Tests for features/brawl/brawlers.py."""

from features.brawl.brawlers import Brawler, load_brawlers


def test_load_brawlers_returns_list():
    assert isinstance(load_brawlers(), list)


def test_load_brawlers_not_empty():
    assert len(load_brawlers()) > 0


def test_load_brawlers_returns_brawler_instances():
    assert all(isinstance(b, Brawler) for b in load_brawlers())


def test_shelly_in_roster():
    ids = [b.id for b in load_brawlers()]
    assert "shelly" in ids


def test_all_brawlers_have_string_id():
    assert all(isinstance(b.id, str) and b.id for b in load_brawlers())


def test_all_brawlers_have_string_name():
    assert all(isinstance(b.name, str) and b.name for b in load_brawlers())


def test_all_brawlers_have_rarity():
    assert all(isinstance(b.rarity, str) and b.rarity for b in load_brawlers())


def test_all_brawlers_have_list_gadgets():
    assert all(isinstance(b.gadgets, list) for b in load_brawlers())


def test_all_brawlers_have_list_star_powers():
    assert all(isinstance(b.star_powers, list) for b in load_brawlers())


def test_brawler_ids_are_lowercase():
    # IDs are used as DB keys and must be lowercase (e.g. "shelly", "8bit")
    assert all(b.id == b.id.lower() for b in load_brawlers())


def test_no_duplicate_brawler_ids():
    ids = [b.id for b in load_brawlers()]
    assert len(ids) == len(set(ids))


def test_load_brawlers_called_twice_returns_same_count():
    # Ensures the file read is stable and not stateful
    assert len(load_brawlers()) == len(load_brawlers())
