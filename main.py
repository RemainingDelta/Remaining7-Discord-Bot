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
    """Something that raised during startup, kept for the Discord report."""

    label: str
    source: str
    error: str
    traceback: str


# Detail for the current startup. Kept separate from the failed-label list
# that sync_commands() consumes, so that contract stays unchanged.
STARTUP_FAILURES: list[StartupFailure] = []

# on_ready re-fires on every gateway reconnect, so the report is guarded to
# once per process. Without this a flaky connection reposts it repeatedly.
_STARTUP_REPORTED = False


def record_failure(label: str, source: str, exc: Exception) -> None:
    """Capture a startup failure for the Discord report."""
    STARTUP_FAILURES.append(
        StartupFailure(label, source, repr(exc), traceback.format_exc())
    )


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
    lines = [
        f"✅ **Bot online** — {BOT_VERSION}",
        f"Features: {loaded}/{total} loaded",
        f"Commands: {synced if synced is not None else 'not synced'}",
    ]

    file = None
    if STARTUP_FAILURES:
        lines.append("")
        lines.append(f"⚠️ **{len(STARTUP_FAILURES)} failure(s) during startup**")
        for failure in STARTUP_FAILURES:
            lines.append(f"• **{failure.label}** (`{failure.source}`)")
            lines.append(f"```{failure.error}```")
        detail = "\n\n".join(
            f"=== {f.label} ({f.source}) ===\n{f.traceback}" for f in STARTUP_FAILURES
        )
        file = discord.File(
            io.BytesIO(detail.encode("utf-8")), filename="startup_failures.txt"
        )

    try:
        await channel.send(content="\n".join(lines), file=file)
        _STARTUP_REPORTED = True
    except Exception as e:
        # Reporting must never be the thing that breaks startup. The flag stays
        # unset so a later reconnect retries a send that never succeeded.
        print(f"⚠️ Could not report startup to Discord: {e!r}")


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
            content=f"❌ **Runtime error** — `{source}`\n```{type(error).__name__}: {error}```",
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
