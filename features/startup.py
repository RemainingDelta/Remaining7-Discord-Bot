"""Bot startup wiring: what to load, and how to fail loudly (#469).

Extension loading and the tourney prefix-command registration live in
``Client.setup_hook``, which discord.py awaits at the end of ``login()`` and
therefore before ``connect()`` opens the gateway. That ordering is the fix for
#469: every command exists before Discord can deliver the first message. All of
this used to run inside ``on_ready``, concurrently with message handling, so a
``!c`` typed during the window raised ``CommandNotFound`` with no handler
registered and produced silence.
"""

import traceback

from discord.ext import commands

# Order matters for a few of these; see docs/SETUP.md. The heartbeat goes first so
# the downtime clock is running as early as possible.
EXTENSIONS: tuple[str, ...] = (
    "features.heartbeat",
    "features.general",
    "features.economy",
    "features.event",
    "features.security",
    "features.scam_detection",
    "features.brawl.commands",
    "features.quests",
    "features.translation",
    "features.support_tickets",
    "features.booster_shoutout",
    "features.github_tickets",
    "features.sticky",
    "features.counting",
    "features.story",
    "features.message_mirror",
    "features.tourney.tourney_reports",
)

STARTING_UP_MESSAGE = (
    "⏳ The bot is still starting up — try that again in a few seconds."
)


async def load_all_extensions(bot: commands.Bot) -> list[str]:
    """Load every extension and return the names that failed.

    Each load is isolated deliberately. They used to share a single try/except, so
    one bad cog silently skipped every cog after it — including the one that
    registers ``!c`` (#469).
    """
    failed: list[str] = []
    for name in EXTENSIONS:
        try:
            await bot.load_extension(name)
            print(f"✅ Loaded Feature: {name}")
        except Exception as e:
            failed.append(name)
            print(f"❌ Failed to load {name}: {e}")
    return failed


async def handle_command_error(ctx, error, *, startup_done: bool) -> None:
    """Say something instead of nothing when a command is not available yet.

    An unknown command before startup finishes means the cog that registers it has
    not loaded, or failed to — the #469 symptom. Once startup is done, stay silent
    on unknown commands so unrelated ``!chatter`` is not answered.
    """
    if isinstance(error, commands.CommandNotFound):
        if not startup_done:
            try:
                await ctx.reply(STARTING_UP_MESSAGE)
            except Exception:
                pass
        return

    traceback.print_exception(type(error), error, error.__traceback__)
