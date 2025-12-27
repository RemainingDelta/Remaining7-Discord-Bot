import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Import Tourney Logic (Legacy/Features folder)
from features.tourney.tourney_commands import setup_tourney_commands

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

# --- DEBUG COMMANDS ---

@bot.tree.command(name="audit_emojis", description="Debug: Checks rendering of all configured emojis")
async def audit_emojis(interaction: discord.Interaction):
    """
    Displays all emojis from the config file in batches to verify they render correctly.
    Only visible to the person running the command.
    """
    # 1. Defer response (prevents timeout while building embeds)
    await interaction.response.defer(ephemeral=True)

    # 2. Convert dictionary to list
    emoji_list = list(EMOJIS_BRAWLERS.items())
    total_count = len(emoji_list)
    
    # 3. Process in chunks of 20 to fit in Discord Embeds
    chunk_size = 20
    
    for i in range(0, total_count, chunk_size):
        chunk = emoji_list[i:i + chunk_size]
        
        description_text = ""
        for key, emoji_str in chunk:
            # Format: [Emoji] **key**
            # We also add the raw string in code blocks for debugging IDs
            description_text += f"{emoji_str} **{key}**\n`{emoji_str}`\n\n"
        
        embed = discord.Embed(
            title=f"🧩 Emoji Audit (Batch {i // chunk_size + 1})",
            description=description_text,
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Showing {i+1}-{min(i+chunk_size, total_count)} of {total_count}")
        
        # Send as followup
        await interaction.followup.send(embed=embed, ephemeral=True)

    await interaction.followup.send(f"✅ **Audit Complete.** Checked {total_count} emojis.", ephemeral=True)


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
        await bot.load_extension("features.economy")
        print("✅ Loaded Feature: Economy")
        
        await bot.load_extension("features.event")
        print("✅ Loaded Feature: Event")

        # Load Security/Hacked Feature
        await bot.load_extension("features.security")
        print("✅ Loaded Feature: Security (Hacked)")
        
        await bot.load_extension("features.brawl.commands")
        print("✅ Loaded Feature: Brawl (Drops)")
        
    except Exception as e:
        print(f"❌ Error loading features: {e}")

    # 3. Load Tourney System
    try:
        setup_tourney_commands(bot)
        print("✅ Loaded Feature: Tournaments")
        
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
    MODE = os.getenv('BOT_MODE', 'TEST').upper()
    token = os.getenv("DISCORD_TOKEN") if MODE == "REAL" else os.getenv("FAKE_TOKEN")
    if token:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ Runtime Error: {e}")
    else:
        print("❌ DISCORD_TOKEN not found in .env file.")