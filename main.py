import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Import Tourney Logic (Legacy/Features folder)
from features.tourney.tourney_commands import (
    setup_tourney_commands,
    restore_tourney_panels,
)

# Import startup wiring (extension list, error feedback)
from features.startup import handle_command_error, load_all_extensions

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

# on_ready fires again on every gateway re-IDENTIFY, so the post-connect steps
# below are guarded to run once per process.
_startup_done = False

# --- EVENTS ---


@bot.event
async def setup_hook():
    """Register everything before the gateway connects.

    discord.py awaits this at the end of login(), ahead of connect(), so every
    command exists before Discord can deliver the first message. This used to run
    inside on_ready alongside message handling, which is why a !c typed right after
    a restart silently did nothing (#469).
    """
    # 1. Check Database Connection
    if db is not None:
        print("✅ MongoDB Connected via 'database.mongo'")
    else:
        print("❌ MongoDB Connection Failed (Check .env and MONGO_URI)")

    # 2. Load Features (Cogs) — each one isolated, so a failure cannot skip the rest
    failed = await load_all_extensions(bot)
    if failed:
        print(f"⚠️ {len(failed)} feature(s) failed to load: {', '.join(failed)}")

    # 3. Load Tourney System (registers !c / !close and friends)
    try:
        setup_tourney_commands(bot)
        print("✅ Loaded Feature: Tournaments")
    except Exception as e:
        print(f"⚠️ Tourney Error: {e}")


@bot.event
async def on_ready():
    global _startup_done

    print(f"✅ Logged in as {bot.user}")

    if _startup_done:
        return

    # 4. Restore the ticket panels. Needs the guild cache, so it cannot move into
    #    setup_hook.
    try:
        await restore_tourney_panels(bot)
    except Exception as e:
        print(f"⚠️ Tourney Panel Restore Error: {e}")

    # 5. SYNC COMMANDS (Do this LAST)
    try:
        # This registers /shop, /buy, /tourney, /audit_emojis etc.
        synced = await bot.tree.sync()
        print(f"✅ Slash Commands Synced: {len(synced)} commands available")
    except Exception as e:
        print(f"⚠️ Command Sync Error: {e}")

    _startup_done = True
    print("🚀 Bot Startup Complete!")


@bot.event
async def on_command_error(ctx, error):
    """Reply instead of going silent when a command is not available yet (#469)."""
    await handle_command_error(ctx, error, startup_done=_startup_done)


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
