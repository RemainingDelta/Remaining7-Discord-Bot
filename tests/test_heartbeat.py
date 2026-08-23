"""Tests for the downtime window in features/heartbeat.py (#469).

Derived from #469's second acceptance criterion: a !c sent while the bot was down
has to be recoverable afterwards, which means knowing when the bot was last alive.
Boundaries are tested at the edge because the whole point of the minimum gap is to
tell "the bot restarted" apart from "the heartbeat loop just ticked".
"""

import asyncio
import datetime

import features.heartbeat as heartbeat
from features.heartbeat import MAX_LOOKBACK, MIN_GAP, compute_downtime_window

NOW = datetime.datetime(2026, 8, 22, 22, 0, 0, tzinfo=datetime.timezone.utc)
SECOND = datetime.timedelta(seconds=1)


def _stored(gap):
    return (NOW - gap).isoformat()


def test_no_stored_heartbeat_means_no_window():
    """First ever boot. There is no downtime to recover and scanning arbitrary
    history would replay closes that were already handled."""
    assert compute_downtime_window(None, NOW) is None
    assert compute_downtime_window("", NOW) is None


def test_unparseable_heartbeat_means_no_window():
    assert compute_downtime_window("not-a-timestamp", NOW) is None


def test_gap_just_below_the_minimum_is_not_downtime():
    assert compute_downtime_window(_stored(MIN_GAP - SECOND), NOW) is None


def test_gap_just_above_the_minimum_is_downtime():
    gap = MIN_GAP + SECOND
    assert compute_downtime_window(_stored(gap), NOW) == NOW - gap


def test_window_just_inside_the_lookback_cap_is_not_capped():
    gap = MAX_LOOKBACK - datetime.timedelta(minutes=1)
    assert compute_downtime_window(_stored(gap), NOW) == NOW - gap


def test_window_is_capped_at_the_lookback_limit():
    """A week of downtime must not become a week of channel-history reads on a
    256 MB host."""
    assert compute_downtime_window(_stored(datetime.timedelta(days=7)), NOW) == (
        NOW - MAX_LOOKBACK
    )


def test_stored_timestamp_without_a_timezone_is_read_as_utc():
    """Guards the naive/aware mix: the rest of the tourney code uses naive UTC."""
    gap = datetime.timedelta(minutes=5)
    naive = (NOW - gap).replace(tzinfo=None).isoformat()

    assert compute_downtime_window(naive, NOW) == NOW - gap


def test_a_heartbeat_from_the_future_is_not_downtime():
    """Clock skew must not produce a window that scans forward."""
    assert compute_downtime_window(_stored(-datetime.timedelta(minutes=5)), NOW) is None


async def test_the_stored_heartbeat_is_only_read_once(monkeypatch):
    """The heartbeat writer and the missed-!c sweep both need the pre-restart value.
    Whichever runs second must not see the value the writer has already overwritten."""
    monkeypatch.setattr(heartbeat, "_window", None)
    monkeypatch.setattr(heartbeat, "_window_captured", False)

    reads = []

    async def fake_get_setting(key, default=None):
        reads.append(key)
        return _stored(datetime.timedelta(minutes=5))

    monkeypatch.setattr(heartbeat, "get_setting", fake_get_setting)

    first = await heartbeat.capture_downtime_window()
    second = await heartbeat.capture_downtime_window()

    assert reads == [heartbeat.LAST_SEEN_KEY]
    assert first is not None
    assert first == second


async def test_concurrent_callers_both_get_the_window(monkeypatch):
    """The heartbeat loop and the sweep both wake from wait_until_ready at boot, so
    they can call this at the same time. Neither may come back empty-handed."""
    monkeypatch.setattr(heartbeat, "_window", None)
    monkeypatch.setattr(heartbeat, "_window_captured", False)

    async def slow_get_setting(key, default=None):
        await asyncio.sleep(0)  # yield, so the second caller runs mid-read
        return _stored(datetime.timedelta(minutes=5))

    monkeypatch.setattr(heartbeat, "get_setting", slow_get_setting)

    first, second = await asyncio.gather(
        heartbeat.capture_downtime_window(),
        heartbeat.capture_downtime_window(),
    )

    assert first is not None
    assert second is not None
    assert first == second
