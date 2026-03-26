import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Import Tourney Logic (Legacy/Features folder)
from features.tourney.tourney_commands import (
    setup_tourney_commands,
    restore_tourney_panels,
)

# Import Database connection check
from database.mongo import db

from features.config import EMOJIS_BRAWLERS

load_dotenv()

# --- CONFIGURATION ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.invites = True

# Initialize Bot
bot = commands.Bot(command_prefix="!", intents=intents)

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
    try:
        # Load General Feature
        await bot.load_extension("features.general")
        print("✅ Loaded Feature: General")

        await bot.load_extension("features.economy")
        print("✅ Loaded Feature: Economy")

        await bot.load_extension("features.event")
        print("✅ Loaded Feature: Event")

        # Load Security/Hacked Feature
        await bot.load_extension("features.security")
        print("✅ Loaded Feature: Security (Hacked)")

        await bot.load_extension("features.brawl.commands")
        print("✅ Loaded Feature: Brawl (Drops)")

        # Load Quests Feature
        await bot.load_extension("features.quests")
        print("✅ Loaded Feature: Quests")

        # Load Translation Feature
        await bot.load_extension("features.translation")
        print("✅ Loaded Feature: Translation")

        await bot.load_extension("features.support_tickets")
        print("✅ Loaded Feature: Support Tickets")

    except Exception as e:
        print(f"❌ Error loading features: {e}")

    # 3. Load Tourney System
    try:
        setup_tourney_commands(bot)
        print("✅ Loaded Feature: Tournaments")
        await restore_tourney_panels(bot)
    except Exception as e:
        print(f"⚠️ Tourney Error: {e}")

    # 4. SYNC COMMANDS (Do this LAST)
    try:
        # This registers /shop, /buy, /tourney, /audit_emojis etc.
        synced = await bot.tree.sync()
        print(f"✅ Slash Commands Synced: {len(synced)} commands available")
    except Exception as e:
        print(f"⚠️ Command Sync Error: {e}")

    print("🚀 Bot Startup Complete!")


if __name__ == "__main__":
    MODE = os.getenv("BOT_MODE", "TEST").upper()
    token = os.getenv("DISCORD_TOKEN") if MODE == "REAL" else os.getenv("FAKE_TOKEN")
    if token:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ Runtime Error: {e}")
    else:
        print("❌ DISCORD_TOKEN not found in .env file.")
