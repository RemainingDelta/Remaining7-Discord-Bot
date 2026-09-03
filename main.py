import discord
from discord.ext import commands
import os
import traceback
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


async def load_features() -> list[str]:
    """Load every feature cog independently; return the labels that failed."""
    failed: list[str] = []
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
            print(f"❌ Failed to load {label} ({module}): {e!r}")
            traceback.print_exc()
    return failed


async def sync_commands(failed: list[str]) -> None:
    """Publish the command tree, but never let a partial load delete commands.

    tree.sync() is authoritative: it replaces Discord's command list with
    whatever the tree currently holds, so syncing after a cog failed to load
    silently deletes that cog's commands. When anything failed, only sync if
    the result would be purely additive.
    """
    if failed:
        try:
            remote = {c.name for c in await bot.tree.fetch_commands()}
        except Exception as e:
            print(f"⚠️ Skipping command sync: cannot read current commands ({e!r}).")
            return

        local = {c.name for c in bot.tree.get_commands()}
        would_delete = remote - local
        if would_delete:
            print(
                "⚠️ Skipping command sync: it would delete "
                f"{sorted(would_delete)} because these features failed to load: "
                f"{', '.join(failed)}. Fix them and restart."
            )
            return

    try:
        synced = await bot.tree.sync()
        print(f"✅ Slash Commands Synced: {len(synced)} commands available")
    except Exception as e:
        print(f"⚠️ Command Sync Error: {e!r}")


# --- EVENTS ---


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

    # 3. Load Tourney System. Registers its own top-level commands, so a failure
    #    here also has to block a destructive sync.
    try:
        setup_tourney_commands(bot)
        print("✅ Loaded Feature: Tournaments")
        await restore_tourney_panels(bot)
    except Exception as e:
        failed.append("Tournaments")
        print(f"⚠️ Tourney Error: {e!r}")
        traceback.print_exc()

    # 4. Repost the privacy policy so the channel reflects the current wording
    try:
        await repost_privacy_policy(bot)
    except Exception as e:
        print(f"⚠️ Privacy Policy Repost Error: {e!r}")
        traceback.print_exc()

    # 5. SYNC COMMANDS (Do this LAST)
    await sync_commands(failed)

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
