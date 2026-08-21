"""Tests for the pure Hall of Fame prizepool retry state machine (issue #443).

Everything here is Discord-free and Mongo-free on purpose, so the retry,
persistence and supersede rules can be tested without a Discord harness (the
repo has none). The cog is a thin shell over these functions.
"""

import asyncio
import json

import pytest

from features.tourney.hall_of_fame import (
    HOF_MAX_ATTEMPTS,
    HOF_RETRY_INTERVAL_SECONDS,
    fresh_marker,
    has_attempts_remaining,
    hof_marker_dumps,
    hof_marker_loads,
    marker_after_failed_attempt,
    next_hof_retry_at,
    should_supersede,
)

T0 = 1_700_000_000.0


# --- next_hof_retry_at: always anchored to the ORIGINAL warning ---


def test_first_retry_is_one_interval_after_the_original_warning():
    assert next_hof_retry_at(T0, 1) == T0 + HOF_RETRY_INTERVAL_SECONDS


def test_second_retry_is_two_intervals_after_the_original_warning():
    assert next_hof_retry_at(T0, 2) == T0 + 2 * HOF_RETRY_INTERVAL_SECONDS


def test_retry_time_does_not_drift_with_wall_clock():
    # Anchoring to first_alerted_at (not to "now") is the whole requirement:
    # the hour must not move just because someone clicked, or the bot rebooted.
    assert next_hof_retry_at(T0, 1) == next_hof_retry_at(T0, 1)
    assert next_hof_retry_at(T0, 2) - next_hof_retry_at(T0, 1) == (
        HOF_RETRY_INTERVAL_SECONDS
    )


def test_interval_is_one_hour():
    assert HOF_RETRY_INTERVAL_SECONDS == 3600


# --- attempt budget: 3 total (the original + 2 retries) ---


def test_three_attempts_total():
    assert HOF_MAX_ATTEMPTS == 3


def test_attempts_remain_after_first_and_second():
    assert has_attempts_remaining(1) is True
    assert has_attempts_remaining(2) is True


def test_no_attempts_remain_after_the_third():
    assert has_attempts_remaining(3) is False
    assert has_attempts_remaining(4) is False


def test_marker_after_failure_increments_attempt():
    m = fresh_marker("183089", 1, 2, 3, now=T0)
    nxt = marker_after_failed_attempt(m)
    assert nxt is not None
    assert nxt["attempt"] == 2
    assert nxt["first_alerted_at"] == T0  # anchor never moves


def test_marker_after_failure_gives_up_on_the_last_attempt():
    m = fresh_marker("183089", 1, 2, 3, now=T0)
    m["attempt"] = HOF_MAX_ATTEMPTS
    assert marker_after_failed_attempt(m) is None


def test_full_retry_sequence_terminates():
    m = fresh_marker("183089", 1, 2, 3, now=T0)
    seen = []
    while m is not None:
        seen.append(
            (m["attempt"], next_hof_retry_at(m["first_alerted_at"], m["attempt"]))
        )
        m = marker_after_failed_attempt(m)
    assert [a for a, _ in seen] == [1, 2, 3]
    assert seen[0][1] == T0 + 3600
    assert seen[1][1] == T0 + 7200


# --- fresh_marker ---


def test_fresh_marker_starts_at_attempt_one_anchored_to_now():
    m = fresh_marker(
        "183089", guild_id=11, alert_channel_id=22, alert_message_id=33, now=T0
    )
    assert m["matcherino_id"] == "183089"
    assert m["guild_id"] == 11
    assert m["alert_channel_id"] == 22
    assert m["alert_message_id"] == 33
    assert m["attempt"] == 1
    assert m["first_alerted_at"] == T0


# --- marker round-trip and malformed input ---


def test_marker_round_trip():
    m = fresh_marker("183089", 11, 22, 33, now=T0)
    assert hof_marker_loads(hof_marker_dumps(m)) == m


def test_marker_dumps_is_json_text():
    # The settings collection is string-typed (database/mongo.py set_setting).
    raw = hof_marker_dumps(fresh_marker("1", 2, 3, 4, now=T0))
    assert isinstance(raw, str)
    assert json.loads(raw)["matcherino_id"] == "1"


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "not json", "{", "[]", '"a string"', "null"]
)
def test_marker_loads_tolerates_junk(raw):
    # The existing pending-winner reconcile has to survive an empty marker; so
    # must this one, or a bad settings doc wedges the bot at boot.
    assert hof_marker_loads(raw) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"matcherino_id": "1"},
        {"matcherino_id": "1", "attempt": 1},
        {"attempt": 1, "first_alerted_at": T0},
    ],
)
def test_marker_loads_rejects_incomplete_payloads(payload):
    assert hof_marker_loads(json.dumps(payload)) is None


def test_marker_loads_coerces_numeric_types():
    raw = json.dumps(
        {
            "matcherino_id": 183089,
            "guild_id": "11",
            "alert_channel_id": "22",
            "alert_message_id": "33",
            "attempt": "2",
            "first_alerted_at": "1700000000",
        }
    )
    m = hof_marker_loads(raw)
    assert m is not None
    assert m["matcherino_id"] == "183089"
    assert m["attempt"] == 2
    assert m["first_alerted_at"] == T0


# --- supersede ---


def test_no_supersede_when_nothing_is_pending():
    assert should_supersede(None, "183089") is False


def test_supersede_when_a_marker_exists_for_the_same_tourney():
    m = fresh_marker("183089", 11, 22, 33, now=T0)
    assert should_supersede(m, "183089") is True


def test_supersede_when_a_marker_exists_for_a_different_tourney():
    # One pending Hall of Fame at a time; a new run always wins.
    m = fresh_marker("183089", 11, 22, 33, now=T0)
    assert should_supersede(m, "999999") is True


def test_superseding_resets_the_attempt_count_and_reanchors():
    old = fresh_marker("183089", 11, 22, 33, now=T0)
    old["attempt"] = 3
    later = T0 + 5000
    new = fresh_marker("183089", 11, 22, 44, now=later)
    assert new["attempt"] == 1
    assert new["first_alerted_at"] == later
    assert next_hof_retry_at(new["first_alerted_at"], new["attempt"]) == later + 3600


# --- cancel_task_slot: a running task must not cancel itself ---


async def test_cancel_task_slot_cancels_a_pending_task():
    from features.tourney.hall_of_fame import cancel_task_slot

    async def sleeper():
        await asyncio.sleep(60)

    task = asyncio.create_task(sleeper())
    slot = [task]
    await asyncio.sleep(0)
    cancel_task_slot(slot)
    assert slot[0] is None
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancel_task_slot_is_a_noop_on_an_empty_slot():
    from features.tourney.hall_of_fame import cancel_task_slot

    slot = [None]
    cancel_task_slot(slot)
    assert slot[0] is None


async def test_cancel_task_slot_does_not_cancel_the_calling_task():
    """The retry loop clears its own slot on the way out. If that cancelled the
    running task, CancelledError would fire at the next await and skip the
    remaining cleanup (closing the alert, dropping the marker)."""
    from features.tourney.hall_of_fame import cancel_task_slot

    reached_the_end = False

    async def self_clearing():
        nonlocal reached_the_end
        cancel_task_slot(slot)
        await asyncio.sleep(0)  # would raise here if we had cancelled ourselves
        reached_the_end = True

    slot = [None]
    task = asyncio.create_task(self_clearing())
    slot[0] = task
    await task
    assert reached_the_end is True
    assert slot[0] is None


async def test_cancel_task_slot_ignores_an_already_finished_task():
    from features.tourney.hall_of_fame import cancel_task_slot

    async def done_quick():
        return 1

    task = asyncio.create_task(done_quick())
    await task
    slot = [task]
    cancel_task_slot(slot)
    assert slot[0] is None
    assert task.result() == 1
