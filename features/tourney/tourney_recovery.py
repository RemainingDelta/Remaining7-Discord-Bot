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

# The prefix is fixed at "!" in main.py; these are !close and its alias.
CLOSE_TOKENS = ("!c", "!close")

# One page is plenty. A ticket with more traffic than this during a restart has a
# live conversation in it, and staff will re-run the close by hand.
HISTORY_LIMIT = 50

# Matches the pacing used elsewhere when walking ticket channels in bulk.
SLEEP_BETWEEN_CHANNELS = 1.5


def is_missed_close_message(message) -> bool:
    """True if this message is a ``!c`` / ``!close`` the bot never got to process."""
    if getattr(message.author, "bot", False):
        return False

    tokens = (message.content or "").strip().split()
    if not tokens:
        return False

    # Only the first token matters: discord.py ignores extra arguments by default,
    # so "!c all done" really does close the ticket.
    return tokens[0].lower() in CLOSE_TOKENS


async def sweep_missed_closes(
    bot,
    window_start,
    *,
    history_limit: int = HISTORY_LIMIT,
    sleep_between: float = SLEEP_BETWEEN_CHANNELS,
) -> int:
    """Replay the first missed ``!c`` in each still-open tourney ticket.

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


async def _replay_channel(bot, channel, window_start, history_limit) -> bool:
    missed = None
    async for message in channel.history(
        after=window_start, limit=history_limit, oldest_first=True
    ):
        if is_missed_close_message(message):
            missed = message
            break

    if missed is None:
        return False

    ctx = await bot.get_context(missed)
    if not ctx.valid or ctx.command is None or ctx.command.qualified_name != "close":
        return False

    await bot.invoke(ctx)
    print(f"♻️ Replayed a !c missed during downtime in #{channel.name}.")
    return True
