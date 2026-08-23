"""Recover a ``!c`` that was typed while the bot was down (#469).

Discord never delivers messages sent while the process is offline, so the only way
to find them is to read channel history afterwards. This scans the two *open*
tourney ticket categories over the downtime window and replays the first ``!c`` it
finds in each channel through the normal command pipeline, so the original staff
member gets the closure credit rather than the bot.

Restricting the scan to the open categories is what makes the replay safe to run on
every boot. A ticket that was already closed has moved to a closed category and is
never revisited. That matters because ``increment_staff_closure`` and
``update_tourney_queue`` are both raw ``$inc``, and the ``!close`` callback runs them
*before* ``close_ticket_via_command`` checks the category — so a replay into an
already-closed ticket would double-credit the staff member and double-decrement the
queue even though the close itself would bail.
"""

import asyncio

import discord

from features.config import PRE_TOURNEY_CATEGORY_ID, TOURNEY_CATEGORY_ID

from .tourney_utils import _is_staff

# The prefix is fixed at "!" in main.py; these are !close and its alias.
CLOSE_TOKENS = ("!c", "!close")

# A !reopen means someone deliberately put the ticket back in an open category, so
# any !c before it is stale and must not be replayed.
REOPEN_TOKENS = ("!reopen",)

# The bot's own close confirmation, from close_ticket_via_command. Its presence means
# a close already completed here.
CLOSE_CONFIRMATION_PREFIX = "Ticket closed by "

# One page is plenty. A ticket with more traffic than this during a restart has a
# live conversation in it, and staff will re-run the close by hand.
HISTORY_LIMIT = 50

# Matches the pacing used elsewhere when walking ticket channels in bulk.
SLEEP_BETWEEN_CHANNELS = 1.5


def _first_token(message) -> str:
    # Only the first token matters: discord.py ignores extra arguments by default,
    # so "!c all done" really does close the ticket.
    tokens = (message.content or "").strip().split()
    return tokens[0].lower() if tokens else ""


def is_missed_close_message(message) -> bool:
    """True if this message is a ``!c`` / ``!close`` the bot never got to process."""
    if getattr(message.author, "bot", False):
        return False

    return _first_token(message) in CLOSE_TOKENS


def is_settling_message(message) -> bool:
    """True if this message means the ticket's state was already decided, so any
    earlier ``!c`` in the window is stale.

    Two cases: a ``!reopen`` (someone put a closed ticket back deliberately, which
    is why it is in a scanned category at all), and the bot's own close
    confirmation (a close already ran to completion here).
    """
    if getattr(message.author, "bot", False):
        return (message.content or "").startswith(CLOSE_CONFIRMATION_PREFIX)

    return _first_token(message) in REOPEN_TOKENS


async def sweep_missed_closes(
    bot,
    window_start,
    *,
    history_limit: int = HISTORY_LIMIT,
    sleep_between: float = SLEEP_BETWEEN_CHANNELS,
) -> int:
    """Replay the missed ``!c`` in each still-open tourney ticket.

    Returns the number of tickets closed.
    """
    replayed = 0

    for category_id in (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID):
        category = bot.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            continue

        for channel in category.text_channels:
            try:
                if await _replay_channel(bot, channel, window_start, history_limit):
                    replayed += 1
                    if sleep_between:
                        await asyncio.sleep(sleep_between)
            except Exception as e:
                print(f"⚠️ Missed-close sweep failed for #{channel.name}: {e}")

    return replayed


async def _find_missed_close(channel, window_start, history_limit):
    """Newest-first, so the most recent lifecycle signal in the window wins.

    Stopping at the first settling message is what prevents re-closing a ticket that
    was closed and then deliberately reopened: !reopen puts it back in a scanned
    category, leaving the old !c sitting in the window looking unprocessed.
    """
    async for message in channel.history(
        after=window_start, limit=history_limit, oldest_first=False
    ):
        if is_settling_message(message):
            return None
        if is_missed_close_message(message):
            return message

    return None


async def _replay_channel(bot, channel, window_start, history_limit) -> bool:
    missed = await _find_missed_close(channel, window_start, history_limit)
    if missed is None:
        return False

    # close_command increments the staff closure count and decrements the queue
    # before close_ticket_via_command checks permissions, so replaying a non-staff
    # !c would move both counters before being rejected.
    if not _is_staff(missed.author):
        return False

    ctx = await bot.get_context(missed)
    if not ctx.valid or ctx.command is None or ctx.command.qualified_name != "close":
        return False

    await bot.invoke(ctx)
    print(f"♻️ Replayed a !c missed during downtime in #{channel.name}.")
    return True
