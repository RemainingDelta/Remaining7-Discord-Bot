"""Pure state machine for the Hall of Fame prizepool retry (#443).

When Matcherino's tournament page doesn't yield a prize pool, the bot must not
publish the Hall of Fame post -- doing so is what produced the permanent public
"$0.00" embeds this issue is about. Instead it alerts #tourney-admin, offers a
manual override, and retries.

Everything in this module is kept free of Discord and Mongo so the retry,
persistence and supersede rules can be unit-tested in isolation -- the same
convention as `validate_story_word` in features/story.py. The cog is a thin
shell over these functions.

Attempt accounting: `attempt` is the number of attempts made so far, starting
at 1 for the query that triggered the alert. Retry N is scheduled at
`first_alerted_at + HOF_RETRY_INTERVAL_SECONDS * (N - 1)`, i.e. always anchored
to the original warning -- never to a button click or a restart -- so the
schedule is identical whether staff acknowledge it or ignore it.
"""

import asyncio
import json

from features.config import HOF_MAX_ATTEMPTS, HOF_RETRY_INTERVAL_SECONDS

__all__ = [
    "HOF_MAX_ATTEMPTS",
    "cancel_task_slot",
    "HOF_RETRY_INTERVAL_SECONDS",
    "PENDING_HOF_KEY",
    "fresh_marker",
    "has_attempts_remaining",
    "hof_marker_dumps",
    "hof_marker_loads",
    "marker_after_failed_attempt",
    "next_hof_retry_at",
    "should_supersede",
]

# Settings-collection key holding the pending-alert marker. The marker is the
# source of truth so a restart can re-arm the retry (the in-process asyncio task
# is lost on reboot), mirroring PENDING_WINNER_KEY in tourney_commands.
PENDING_HOF_KEY = "pending_hall_of_fame"

# Keys every persisted marker must carry to be usable after a restart.
_REQUIRED_KEYS = (
    "matcherino_id",
    "guild_id",
    "alert_channel_id",
    "alert_message_id",
    "attempt",
    "first_alerted_at",
)


def next_hof_retry_at(first_alerted_at: float, attempt: int) -> float:
    """Absolute timestamp of the next retry after `attempt` attempts.

    Anchored to `first_alerted_at`, so the deadline does not drift when a button
    is clicked or the bot restarts mid-wait.
    """
    return first_alerted_at + HOF_RETRY_INTERVAL_SECONDS * attempt


def has_attempts_remaining(attempt: int) -> bool:
    """True while another retry is still allowed after `attempt` attempts."""
    return attempt < HOF_MAX_ATTEMPTS


def fresh_marker(
    matcherino_id: str,
    guild_id: int,
    alert_channel_id: int,
    alert_message_id: int,
    now: float,
) -> dict:
    """A first-alert marker: attempt 1, anchored to `now`."""
    return {
        "matcherino_id": str(matcherino_id),
        "guild_id": int(guild_id),
        "alert_channel_id": int(alert_channel_id),
        "alert_message_id": int(alert_message_id),
        "attempt": 1,
        "first_alerted_at": float(now),
    }


def marker_after_failed_attempt(marker: dict) -> dict | None:
    """Marker for the next retry, or None when the attempt budget is spent.

    The anchor is deliberately carried through unchanged.
    """
    attempt = int(marker["attempt"])
    if not has_attempts_remaining(attempt):
        return None
    return {**marker, "attempt": attempt + 1}


def should_supersede(existing: dict | None, new_matcherino_id: str) -> bool:
    """Whether a new Hall of Fame run must retire a pending alert.

    Always true when anything is pending, including for a different tournament:
    there is only ever one pending Hall of Fame, and the newest run wins.
    """
    return existing is not None


def hof_marker_dumps(marker: dict) -> str:
    """Serialise a marker for the string-typed settings store."""
    return json.dumps(marker)


def hof_marker_loads(raw: str | None) -> dict | None:
    """Parse a persisted marker, returning None for anything unusable.

    Tolerates a missing, blank, malformed or incomplete value so a bad settings
    doc can't wedge the boot reconcile. Numeric fields are coerced because a
    hand-edited doc may hold them as strings.
    """
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if any(key not in data for key in _REQUIRED_KEYS):
        return None
    try:
        return {
            "matcherino_id": str(data["matcherino_id"]),
            "guild_id": int(data["guild_id"]),
            "alert_channel_id": int(data["alert_channel_id"]),
            "alert_message_id": int(data["alert_message_id"]),
            "attempt": int(data["attempt"]),
            "first_alerted_at": float(data["first_alerted_at"]),
        }
    except (ValueError, TypeError):
        return None


def cancel_task_slot(slot: list) -> None:
    """Clear a single-slot task holder, cancelling the task unless it is the caller.

    The retry loop clears its own slot on the way out. Cancelling the running
    task there would raise CancelledError at its next suspension point and skip
    the remaining cleanup -- closing the alert message and dropping the marker --
    so a self-clearing task only empties the slot and returns normally.
    """
    task = slot[0]
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()
    slot[0] = None
