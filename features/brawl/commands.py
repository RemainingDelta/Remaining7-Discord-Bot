import discord
from discord import app_commands
from discord.ext import commands
from features.config import EMOJIS_DROPS, EMOJIS_RARITIES
from .drops import open_mega_box, open_starr_drop

class BrawlCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="megabox", description="Open a Brawl Stars Mega Box!")
    async def megabox(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = str(interaction.user.id)
        
        rewards = await open_mega_box(user_id)
        rewards_text = "\n".join(rewards)
        
        # Use Mega Box emoji from config
        box_emoji = EMOJIS_DROPS.get("mega_box", "🟥")
        
        embed = discord.Embed(
            title=f"{box_emoji} MEGA BOX OPENED!",
            description=rewards_text,
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Opened by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="starrdrop", description="Open a random Starr Drop!")
    async def starrdrop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = str(interaction.user.id)
        
        rarity, reward_text = await open_starr_drop(user_id)
        
        # Colors for Starr Drop rarities
        colors = {
            "Rare": 0x54d35e,
            "Super Rare": 0x3d9df6,
            "Epic": 0xcf4bf6,
            "Mythic": 0xfb3a42,
            "Legendary": 0xfff36d
        }
        
        drop_emoji = EMOJIS_DROPS.get("starr_drop", "⭐")
        rarity_key = rarity.lower().replace(" ", "_")
        rarity_emoji = EMOJIS_RARITIES.get(rarity_key, "")

        embed = discord.Embed(
            title=f"{drop_emoji} {rarity} Starr Drop!",
            description=f"{rarity_emoji} You got: {reward_text}",
            color=colors.get(rarity, 0xffffff)
        )
        await interaction.followup.send(embed=embed)

# This function is required for main.py to load this file as an extension
async def setup(bot):
    await bot.add_cog(BrawlCommands(bot))