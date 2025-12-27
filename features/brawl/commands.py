import discord
from discord import app_commands
from discord.ext import commands
from features.config import EMOJIS_BRAWLERS, EMOJIS_RARITIES, EMOJIS_DROPS
from .brawlers import BRAWLER_ROSTER
from .drops import open_mega_box, open_starr_drop
from database.mongo import get_user_brawlers

class BrawlerPagination(discord.ui.View):
    """View class to handle switching between Page 1 and Page 2 using buttons."""
    def __init__(self, user_name: str, owned_ids: list):
        super().__init__(timeout=60)
        self.user_name = user_name
        # Force all owned IDs to lowercase and strip spaces for safety
        self.owned_ids = [str(i).lower().strip() for i in owned_ids]

    def create_embed(self, page: int):
        if page == 1:
            rarity_order = ["Starting", "Rare", "Super Rare", "Epic"]
            title_suffix = "(Common - Epic)"
        else:
            rarity_order = ["Mythic", "Legendary", "Ultra Legendary", "Chromatic"]
            title_suffix = "(Mythic - Ultra)"

        categories = {}
        for b in BRAWLER_ROSTER:
            if b.rarity not in categories:
                categories[b.rarity] = []
            categories[b.rarity].append(b)

        embed = discord.Embed(
            title=f"👤 {self.user_name}'s Collection {title_suffix}",
            color=discord.Color.blue()
        )

        for rarity_name in rarity_order:
            if rarity_name not in categories:
                continue
                
            brawlers_in_rarity = categories[rarity_name]
            rarity_key = rarity_name.lower().replace(" ", "_")
            r_emoji = EMOJIS_RARITIES.get(rarity_key, "⚪")
            
            field_value = ""
            part = 1
            
            for b in brawlers_in_rarity:
                # Compare lowercase ID from JSON to lowercase IDs from DB
                b_id_lower = b.id.lower().strip()
                b_emoji = EMOJIS_BRAWLERS.get(b_id_lower, "❓")
                
                # Check ownership
                is_owned = b_id_lower in self.owned_ids
                status_icon = "✅" if is_owned else "🔒"
                
                line = f"{b_emoji} {b.name} {status_icon}\n"

                if len(field_value) + len(line) > 1000:
                    f_name = f"{r_emoji} {rarity_name}" + (f" (Part {part})" if part > 1 else "")
                    embed.add_field(name=f_name, value=field_value, inline=True)
                    field_value = line
                    part += 1
                else:
                    field_value += line

            if field_value:
                f_name = f"{r_emoji} {rarity_name}" + (f" (Part {part})" if part > 1 else "")
                embed.add_field(name=f_name, value=field_value, inline=True)

        embed.set_footer(text=f"Page {page}/2 • Total Owned: {len(self.owned_ids)}")
        return embed

    @discord.ui.button(label="Page 1", style=discord.ButtonStyle.primary)
    async def page_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed(1), view=self)

    @discord.ui.button(label="Page 2", style=discord.ButtonStyle.primary)
    async def page_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.create_embed(2), view=self)
        
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
        
    @app_commands.command(name="brawlers", description="View your collection with buttons")
    async def brawlers(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        user_id = str(interaction.user.id)
        # Fetch data from mongo.py
        raw_owned = await get_user_brawlers(user_id)
        
        # Extract keys if raw_owned is a dictionary, otherwise use as list
        if isinstance(raw_owned, dict):
            owned_ids = list(raw_owned.keys())
        else:
            owned_ids = raw_owned
            
        view = BrawlerPagination(interaction.user.name, owned_ids)
        embed = view.create_embed(1) # Start on Page 1
        
        await interaction.followup.send(embed=embed, view=view)
        
# This function is required for main.py to load this file as an extension
async def setup(bot):
    await bot.add_cog(BrawlCommands(bot))