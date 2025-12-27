import discord
from discord import app_commands
from discord.ext import commands

# Import the logic functions from your drops file
# Note: We use relative imports (.) because they are in the same folder
from .drops import open_mega_box, open_starr_drop

class BrawlCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="megabox", description="Open a Brawl Stars Mega Box!")
    async def megabox(self, interaction: discord.Interaction):
        # 1. Defer response (Mega box logic might take a split second)
        await interaction.response.defer()
        
        user_id = str(interaction.user.id)
        
        # 2. Run the Game Logic
        rewards = await open_mega_box(user_id)
        
        # 3. Format the Output
        # Join the list of rewards into a single string
        rewards_text = "\n".join(rewards)
        
        embed = discord.Embed(
            title="🟥 MEGA BOX OPENED!",
            description=rewards_text,
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Opened by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="starrdrop", description="Open a random Starr Drop!")
    async def starrdrop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        user_id = str(interaction.user.id)
        
        # 2. Run the Game Logic
        rarity, reward_text = await open_starr_drop(user_id)
        
        # 3. Pick a color based on rarity
        colors = {
            "Rare": 0x54d35e,       # Green
            "Super Rare": 0x3d9df6, # Blue
            "Epic": 0xcf4bf6,       # Purple
            "Mythic": 0xfb3a42,     # Red
            "Legendary": 0xfff36d   # Yellow/Gold
        }
        color = colors.get(rarity, 0xffffff)
        
        embed = discord.Embed(
            title=f"⭐ {rarity} Starr Drop!",
            description=f"You got: {reward_text}",
            color=color
        )
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BrawlCommands(bot))