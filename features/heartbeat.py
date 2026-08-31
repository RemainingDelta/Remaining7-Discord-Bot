"""Liveness clock, so a restart can be told apart from a quiet minute (#469).

The bot stamps a UTC timestamp into the settings collection every minute. On the
next boot, the gap between that stamp and now is the downtime window: the span in
which Discord delivered messages that no process was alive to receive.
``features/tourney/tourney_recovery.py`` uses that window to find a ``!c`` that was
missed while the bot was down.
"""

import asyncio
import datetime

from discord.ext import commands, tasks

from database.mongo import get_setting, set_setting

LAST_SEEN_KEY = "bot_last_seen"

# Bounds the boot-time history scan. Older than this is not worth replaying, and on
# the 256 MB host it is not worth reading either.
MAX_LOOKBACK = datetime.timedelta(hours=2)

# Below this the bot did not restart; the heartbeat loop simply had not ticked yet.
MIN_GAP = datetime.timedelta(seconds=10)

HEARTBEAT_MINUTES = 1

_window: datetime.datetime | None = None
_window_captured = False
_capture_lock = asyncio.Lock()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def compute_downtime_window(
    raw: str | None,
    now: datetime.datetime,
    max_lookback: datetime.timedelta = MAX_LOOKBACK,
    min_gap: datetime.timedelta = MIN_GAP,
) -> datetime.datetime | None:
    """Return the timestamp to scan channel history from, or None if there is
    nothing to recover.

    Everything here stays timezone-aware UTC. The rest of the tourney code uses
    naive ``utcnow()``, so these values must not be mixed with those.
    """
    if not raw:
        return None
    try:
        last_seen = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None

    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=datetime.timezone.utc)

    if now - last_seen < min_gap:
        return None

    return max(last_seen, now - max_lookback)


async def capture_downtime_window() -> datetime.datetime | None:
    """Read the stored heartbeat once per process and cache the window it implies.

    Both the heartbeat loop and the missed-``!c`` sweep need the pre-restart value,
    and the loop overwrites it. Caching on first read makes the two order-independent.

    The lock matters: both callers start from wait_until_ready() at boot, so without
    it the second one would run while the first is still awaiting the read and would
    see an unpopulated cache — losing the window it needs.
    """
    global _window, _window_captured

    async with _capture_lock:
        if _window_captured:
            return _window

        try:
            _window = compute_downtime_window(
                await get_setting(LAST_SEEN_KEY), _utc_now()
            )
        except Exception as e:
            print(f"⚠️ Heartbeat: could not read {LAST_SEEN_KEY}: {e}")
            _window = None

        _window_captured = True

        if _window is not None:
            print(f"♻️ Downtime detected — messages missed since {_window.isoformat()}.")
        return _window


class Heartbeat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.heartbeat_task.start()

    def cog_unload(self):
        self.heartbeat_task.cancel()

    @tasks.loop(minutes=HEARTBEAT_MINUTES)
    async def heartbeat_task(self):
        await self.bot.wait_until_ready()
        # Snapshot the pre-restart value before the first write clobbers it.
        await capture_downtime_window()
        try:
            await set_setting(LAST_SEEN_KEY, _utc_now().isoformat())
        except Exception as e:
            print(f"⚠️ Heartbeat: could not write {LAST_SEEN_KEY}: {e}")


async def setup(bot):
    await bot.add_cog(Heartbeat(bot))
