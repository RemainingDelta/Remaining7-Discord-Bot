import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Import Tourney Logic (Legacy/Features folder)
from features.tourney.tourney_commands import setup_tourney_commands

# Import Database connection check (optional but good for debugging startup)
from database.mongo import db

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
        # Load the massive Economy/Shop/Leveling feature we just created
        await bot.load_extension("features.economy")
        print("✅ Loaded Feature: Economy (Shop, Levels, Admin Cmds)")
        
        await bot.load_extension("features.event")
        print("✅ Loaded Feature: Event (Cleanup & Alerts)")
        
    except Exception as e:
        print(f"❌ Error loading features: {e}")

    # 3. Load Tourney System
    try:
        setup_tourney_commands(bot)
        print("✅ Loaded Feature: Tournaments")
        
        # Sync Slash Commands (This registers /shop, /buy, /tourney, etc. with Discord)
        synced = await bot.tree.sync()
        print(f"✅ Slash Commands Synced: {len(synced)} commands available")
        
    except Exception as e:
        print(f"⚠️ Command Sync Error: {e}")

    # 4. Cache Invites (Optional - if you want invite tracking logic here or in a cog)
    # You can move your on_invite_create/delete listeners to a 'features/invites.py' cog later
    print("🚀 Bot Startup Complete!")

# --- START ---
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ Runtime Error: {e}")
    else:
        print("❌ DISCORD_TOKEN not found in .env file.")