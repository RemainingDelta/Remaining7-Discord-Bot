import discord
from discord import app_commands
from discord.ext import commands, tasks
import io
import os
import sys
import time
import traceback
from collections import deque
from typing import NamedTuple

import aiohttp
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

# Import Tourney Logic (Legacy/Features folder)
from features.tourney.tourney_commands import (
    setup_tourney_commands,
    restore_tourney_panels,
)

# Import the privacy policy repost (keeps the privacy channel current on restart)
from features.privacy_policy import repost_privacy_policy

# Import Database connection check
from database.mongo import db

# Startup reporting posts here, where an admin will actually see it
from features.config import BOT_LOGS_CHANNEL_ID, BOT_VERSION


load_dotenv()

# --- CONFIGURATION ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.invites = True

# Initialize Bot
bot = commands.Bot(command_prefix="!", intents=intents)

# Feature cogs, in load order. Each one loads independently: a cog that raises
# must not stop the cogs listed after it from loading.
FEATURE_EXTENSIONS = [
    ("features.general", "General"),
    ("features.economy", "Economy"),
    ("features.event", "Event"),
    ("features.security", "Security (Hacked)"),
    ("features.scam_detection", "Scam Detection"),
    ("features.brawl.commands", "Brawl (Drops)"),
    ("features.quests", "Quests"),
    ("features.translation", "Translation"),
    ("features.support_tickets", "Support Tickets"),
    ("features.booster_shoutout", "Booster Shoutout"),
    ("features.github_tickets", "GitHub Tickets"),
    ("features.sticky", "Sticky Messages"),
    ("features.counting", "Counting"),
    ("features.story", "Story"),
    ("features.message_mirror", "Message Mirror"),
    ("features.tourney.tourney_reports", "Tourney Reports"),
    ("features.privacy_policy", "Privacy Policy"),
]


class StartupFailure(NamedTuple):
    """Something that raised during startup, kept for the Discord report.

    The exception itself is kept, not its repr: the report classifies severity
    and explains the error from its type, which a string cannot support.
    """

    label: str
    source: str
    exception: BaseException
    traceback: str


# Detail for the current startup. Kept separate from the failed-label list
# that sync_commands() consumes, so that contract stays unchanged.
STARTUP_FAILURES: list[StartupFailure] = []

# on_ready re-fires on every gateway reconnect, so the report is guarded to
# once per process. Without this a flaky connection reposts it repeatedly.
_STARTUP_REPORTED = False


def record_failure(label: str, source: str, exc: Exception) -> None:
    """Capture a startup failure for the Discord report."""
    STARTUP_FAILURES.append(StartupFailure(label, source, exc, traceback.format_exc()))


async def load_features() -> list[str]:
    """Load every feature cog independently; return the labels that failed."""
    failed: list[str] = []
    STARTUP_FAILURES.clear()
    for module, label in FEATURE_EXTENSIONS:
        try:
            await bot.load_extension(module)
            print(f"✅ Loaded Feature: {label}")
        except commands.ExtensionAlreadyLoaded:
            # on_ready fires again on every reconnect, so this is the normal
            # case after the first connect — not a failure.
            pass
        except Exception as e:
            failed.append(label)
            record_failure(label, module, e)
            print(f"❌ Failed to load {label} ({module}): {e!r}")
            traceback.print_exc()
    return failed


async def sync_commands(failed: list[str]) -> int | None:
    """Publish the command tree, but never let a partial load delete commands.

    tree.sync() is authoritative: it replaces Discord's command list with
    whatever the tree currently holds, so syncing after a cog failed to load
    silently deletes that cog's commands. When anything failed, only sync if
    the result would be purely additive. Returns the number of commands
    synced, or None if the sync was skipped or failed.
    """
    if failed:
        try:
            remote = {c.name for c in await bot.tree.fetch_commands()}
        except Exception as e:
            print(f"⚠️ Skipping command sync: cannot read current commands ({e!r}).")
            return None

        local = {c.name for c in bot.tree.get_commands()}
        would_delete = remote - local
        if would_delete:
            print(
                "⚠️ Skipping command sync: it would delete "
                f"{sorted(would_delete)} because these features failed to load: "
                f"{', '.join(failed)}. Fix them and restart."
            )
            return None

    try:
        synced = await bot.tree.sync()
        print(f"✅ Slash Commands Synced: {len(synced)} commands available")
        return len(synced)
    except Exception as e:
        print(f"⚠️ Command Sync Error: {e!r}")
        return None


async def report_startup_to_discord(loaded: int, synced: int | None) -> None:
    """Post one startup report per process to the bot logs channel.

    The host's logs silently drop lines beginning with a warning or cross emoji,
    so a failing feature is invisible there - that is why #503 and #513 both went
    undiagnosed for days. Discord is the surface an admin can actually read, so
    the boot summary and any failure go here, with tracebacks attached rather
    than inlined so Discord's 2000-character limit cannot truncate them.
    """
    global _STARTUP_REPORTED
    if _STARTUP_REPORTED:
        return
    if not isinstance(BOT_LOGS_CHANNEL_ID, int) or BOT_LOGS_CHANNEL_ID <= 0:
        return

    channel = bot.get_channel(BOT_LOGS_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    total = len(FEATURE_EXTENSIONS)
    severity = CRITICAL if STARTUP_FAILURES else INFO
    summary = discord.Embed(
        title=f"{severity.emoji} Bot online — {BOT_VERSION}",
        colour=severity.colour,
        timestamp=discord.utils.utcnow(),
    )
    summary.add_field(name="Features", value=f"{loaded}/{total} loaded", inline=True)
    summary.add_field(
        name="Commands",
        value=str(synced) if synced is not None else "not synced",
        inline=True,
    )
    summary.set_footer(text="Remaining 7 Bot")

    embeds = [summary]
    file = None
    if STARTUP_FAILURES:
        # Discord allows 10 embeds per message, so the summary plus nine failures.
        shown = STARTUP_FAILURES[:9]
        if len(STARTUP_FAILURES) > len(shown):
            summary.add_field(
                name="Note",
                value=f"{len(STARTUP_FAILURES) - len(shown)} further failure(s) in the attachment.",
                inline=False,
            )
        for failure in shown:
            embeds.append(
                build_error_embed(
                    f"{failure.label} ({failure.source})", failure.exception
                )
            )
        detail = "\n\n".join(
            f"=== {f.label} ({f.source}) ===\n{f.traceback}" for f in STARTUP_FAILURES
        )
        file = discord.File(
            io.BytesIO(detail.encode("utf-8")), filename="startup_failures.txt"
        )

    try:
        await channel.send(embeds=embeds, file=file)
        _STARTUP_REPORTED = True
    except Exception as e:
        # Reporting must never be the thing that breaks startup. The flag stays
        # unset so a later reconnect retries a send that never succeeded.
        print(f"⚠️ Could not report startup to Discord: {e!r}")


# --- SEVERITY AND EXPLANATIONS ---


class Severity(NamedTuple):
    """How bad a report is, and how it renders."""

    label: str
    emoji: str
    colour: discord.Colour


# Critical means something is no longer running at all - a feature that failed to
# load, or a background task that stopped. Error means one interaction failed and
# the bot is otherwise healthy. Warning separates a permission or configuration
# problem from a code bug, because they are different jobs to fix.
CRITICAL = Severity("Critical", "🔴", discord.Color.dark_red())
ERROR = Severity("Error", "🟠", discord.Color.red())
WARNING = Severity("Warning", "🟡", discord.Color.orange())
INFO = Severity("Info", "🟢", discord.Color.green())

# Ordered most specific first: Forbidden and NotFound both subclass HTTPException,
# so the generic entry has to come last or it would swallow them.
_EXPLANATIONS: tuple[tuple[type[BaseException], str], ...] = (
    (
        ModuleNotFoundError,
        "A Python package the bot needs is not installed on the server.",
    ),
    (
        ImportError,
        "A library failed to load — usually a missing or broken package on the server.",
    ),
    (
        discord.Forbidden,
        "Discord refused the action — the bot is missing a permission in that channel or server.",
    ),
    (
        discord.NotFound,
        "The channel, message or user no longer exists.",
    ),
    (
        discord.HTTPException,
        "Discord rejected the request.",
    ),
    (
        PyMongoError,
        "The database was unreachable or rejected the query.",
    ),
    (
        aiohttp.ClientError,
        "A request to an external service failed.",
    ),
    (
        TimeoutError,
        "Something took too long to respond and gave up.",
    ),
    (
        ZeroDivisionError,
        "A calculation divided by zero — a bug in the bot's code.",
    ),
    (
        KeyError,
        "The bot expected a value that was not there — a bug in the bot's code.",
    ),
    (
        AttributeError,
        "The bot used something that does not exist — a bug in the bot's code.",
    ),
    (
        TypeError,
        "The bot passed the wrong kind of value — a bug in the bot's code.",
    ),
    (
        ValueError,
        "The bot was given a value it could not use — a bug in the bot's code.",
    ),
)

_UNEXPLAINED = "Unexpected error — see the attached traceback."


def explain_error(error: BaseException) -> str:
    """Say what an exception means in plain English, for someone not reading code."""
    for error_type, explanation in _EXPLANATIONS:
        if isinstance(error, error_type):
            return explanation
    return _UNEXPLAINED


def classify_severity(source: str, error: BaseException) -> Severity:
    """Pick a severity from what failed and why.

    Derived rather than passed in, so every call site classifies the same way.
    """
    if isinstance(error, (discord.Forbidden, discord.NotFound)):
        return WARNING
    if source.startswith("command ") or source.startswith("event "):
        return ERROR
    return CRITICAL


def build_error_embed(source: str, error: BaseException) -> discord.Embed:
    """One embed shape for startup failures and runtime errors alike."""
    severity = classify_severity(source, error)
    embed = discord.Embed(
        title=f"{severity.emoji} {severity.label}",
        colour=severity.colour,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Source", value=f"`{source}`", inline=False)
    embed.add_field(name="What happened", value=explain_error(error), inline=False)
    embed.add_field(
        name="Error",
        value=f"```{type(error).__name__}: {error}```"[:1024],
        inline=False,
    )
    embed.set_footer(text="Remaining 7 Bot")
    return embed


# --- RUNTIME ERROR REPORTING ---

# Rate limited on two axes: the same error is not reposted within the dedup
# window (a background task failing every minute would otherwise post 1,440
# messages a day), and no more than a short burst is posted per window.
_ERROR_DEDUP_SECONDS = 300
_ERROR_BURST_LIMIT = 5
_ERROR_BURST_WINDOW = 60

_error_last_sent: dict[str, float] = {}
_error_recent_sends: deque[float] = deque()

# A failure inside reporting must not trigger another report.
_REPORTING_ERROR = False


def _should_report_error(fingerprint: str, now: float) -> bool:
    """Whether this error is new enough and rare enough to be worth posting."""
    for key, sent in list(_error_last_sent.items()):
        if now - sent > _ERROR_DEDUP_SECONDS:
            del _error_last_sent[key]

    last = _error_last_sent.get(fingerprint)
    if last is not None and now - last < _ERROR_DEDUP_SECONDS:
        return False

    while _error_recent_sends and now - _error_recent_sends[0] > _ERROR_BURST_WINDOW:
        _error_recent_sends.popleft()
    if len(_error_recent_sends) >= _ERROR_BURST_LIMIT:
        return False

    _error_last_sent[fingerprint] = now
    _error_recent_sends.append(now)
    return True


def _unwrap(error: BaseException) -> BaseException:
    """Command errors wrap the real exception; the wrapper is not the useful bit."""
    return getattr(error, "original", None) or error


async def report_error(source: str, error: BaseException) -> None:
    """Post a runtime error to the bot logs channel, rate limited.

    Startup failures go through report_startup_to_discord. This covers
    everything after: commands, listeners and background tasks, none of which
    had any handler at all before, and whose console output the host drops.
    """
    global _REPORTING_ERROR
    if _REPORTING_ERROR:
        return
    if not isinstance(BOT_LOGS_CHANNEL_ID, int) or BOT_LOGS_CHANNEL_ID <= 0:
        return

    error = _unwrap(error)
    fingerprint = f"{source}|{type(error).__name__}|{error}"[:200]
    if not _should_report_error(fingerprint, time.time()):
        return

    channel = bot.get_channel(BOT_LOGS_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )

    _REPORTING_ERROR = True
    try:
        await channel.send(
            embeds=[build_error_embed(source, error)],
            file=discord.File(io.BytesIO(detail.encode("utf-8")), filename="error.txt"),
        )
    except Exception as e:
        print(f"⚠️ Could not report runtime error to Discord: {e!r}")
    finally:
        _REPORTING_ERROR = False


def attach_task_error_reporting(cogs=None) -> None:
    """Route every cog background task's unhandled exception to the log channel.

    A tasks.Loop that raises stops looping and only logs, so a dead scheduler
    is silent. Attaching programmatically covers every loop without editing
    each cog, and re-attaching on reconnect simply replaces the handler.
    """
    for cog in bot.cogs.values() if cogs is None else cogs:
        for name in dir(type(cog)):
            if isinstance(getattr(type(cog), name, None), tasks.Loop):
                loop = getattr(cog, name)
                loop.error(_task_error_handler(f"task {type(cog).__name__}.{name}"))


def _task_error_handler(label: str):
    async def handler(*args) -> None:
        # discord.py passes (cog, exception) for a bound loop, (exception,) otherwise.
        await report_error(label, args[-1])

    return handler


# --- EVENTS ---


@bot.event
async def on_error(event_method: str, /, *args, **kwargs) -> None:
    """Unhandled exception inside a listener. discord.py only logs these."""
    traceback.print_exc()
    error = sys.exc_info()[1]
    if error is not None:
        await report_error(f"event {event_method}", error)


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    """Unhandled prefix command error.

    User mistakes are not bugs and are left alone: an unknown command, a failed
    permission check, or bad arguments should not page anyone.
    """
    if isinstance(
        error,
        (commands.CommandNotFound, commands.CheckFailure, commands.UserInputError),
    ):
        return
    print(f"❌ Command error in !{ctx.command}: {error!r}")
    traceback.print_exception(type(error), error, error.__traceback__)
    await report_error(f"command !{ctx.command}", error)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """Unhandled slash command error, replacing discord.py's log-only default."""
    if isinstance(error, app_commands.CheckFailure):
        return
    name = interaction.command.name if interaction.command else "unknown"
    print(f"❌ Command error in /{name}: {error!r}")
    traceback.print_exception(type(error), error, error.__traceback__)
    await report_error(f"command /{name}", error)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    # 1. Check Database Connection
    if db is not None:
        print("✅ MongoDB Connected via 'database.mongo'")
    else:
        print("❌ MongoDB Connection Failed (Check .env and MONGO_URI)")

    # 2. Load Features (Cogs)
    failed = await load_features()
    loaded = len(FEATURE_EXTENSIONS) - len(failed)

    # 3. Load Tourney System. Registers its own top-level commands, so a failure
    #    here also has to block a destructive sync.
    try:
        setup_tourney_commands(bot)
        print("✅ Loaded Feature: Tournaments")
        await restore_tourney_panels(bot)
    except Exception as e:
        failed.append("Tournaments")
        record_failure("Tournaments", "features.tourney.tourney_commands", e)
        print(f"⚠️ Tourney Error: {e!r}")
        traceback.print_exc()

    # 4. Repost the privacy policy so the channel reflects the current wording
    try:
        await repost_privacy_policy(bot)
    except Exception as e:
        # Reported but not added to `failed`: the repost registers no
        # commands, so it must not block the sync.
        record_failure("Privacy Policy Repost", "features.privacy_policy", e)
        print(f"⚠️ Privacy Policy Repost Error: {e!r}")
        traceback.print_exc()

    # 5. SYNC COMMANDS (Do this LAST)
    synced = await sync_commands(failed)

    # 6. Route background task failures to the log channel too
    attach_task_error_reporting()

    # 7. Report the boot to Discord, where the host's logs cannot swallow it
    await report_startup_to_discord(loaded, synced)

    if failed:
        print(
            f"⚠️ Startup finished with {len(failed)} failed feature(s): {', '.join(failed)}"
        )
    print("🚀 Bot Startup Complete!")


if __name__ == "__main__":
    MODE = os.getenv("BOT_MODE", "DEV").upper()
    token = os.getenv("PROD_TOKEN") if MODE == "PROD" else os.getenv("DEV_TOKEN")
    if token:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ Runtime Error: {e}")
    else:
        print("❌ Token not found in .env file. Set PROD_TOKEN or DEV_TOKEN.")
