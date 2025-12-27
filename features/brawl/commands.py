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

class BrawlerShopSelect(discord.ui.Select):
    def __init__(self, user_id, rarity, brawlers_to_buy, price):
        self.user_id = user_id
        self.price = price
        # Create select options only for brawlers the user doesn't own
        options = [
            discord.SelectOption(
                label=b.name, 
                value=b.id, 
                description=f"Unlock {b.name} for {price} Credits"
            )
            for b in brawlers_to_buy[:25] # Discord select limit
        ]
        super().__init__(placeholder=f"Pick a {rarity} Brawler to buy...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("You can't use someone else's shop!", ephemeral=True)

        brawler_id = self.values[0]
        from database.mongo import deduct_credits, add_brawler_to_user
        
        # Double check credits and deduct
        success = await deduct_credits(self.user_id, self.price)
        if not success:
            return await interaction.response.send_message(f"❌ You need {self.price} Credits to buy this brawler!", ephemeral=True)

        await add_brawler_to_user(self.user_id, brawler_id)
        
        # Find brawler name for the success message
        b_name = next(b.name for b in BRAWLER_ROSTER if b.id == brawler_id)
        await interaction.response.send_message(f"🎉 Success! You've unlocked **{b_name}** for **{self.price}** Credits!")

class BuyBrawlerView(discord.ui.View):
    def __init__(self, user_id, owned_ids):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.owned_ids = owned_ids

    async def open_rarity_shop(self, interaction: discord.Interaction, rarity: str):
        from features.config import BRAWLER_PRICES
        price = BRAWLER_PRICES.get(rarity, 0)
        
        # Filter: Only brawlers of this rarity NOT in user's owned list
        available = [b for b in BRAWLER_ROSTER if b.rarity == rarity and b.id.lower() not in self.owned_ids]
        
        if not available:
            return await interaction.response.send_message(f"✨ Impressive! You already own all {rarity} brawlers.", ephemeral=True)

        view = discord.ui.View()
        view.add_item(BrawlerShopSelect(self.user_id, rarity, available, price))
        
        embed = discord.Embed(
            title=f"🛒 {rarity} Brawler Shop", 
            description=f"Each brawler here costs **{price} Credits**.\nSelect one below to purchase.", 
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Rare", style=discord.ButtonStyle.success)
    async def buy_rare(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_rarity_shop(interaction, "Rare")

    @discord.ui.button(label="Super Rare", style=discord.ButtonStyle.primary)
    async def buy_super_rare(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_rarity_shop(interaction, "Super Rare")

    @discord.ui.button(label="Epic", style=discord.ButtonStyle.secondary)
    async def buy_epic(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_rarity_shop(interaction, "Epic")

    @discord.ui.button(label="Mythic", style=discord.ButtonStyle.danger)
    async def buy_mythic(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_rarity_shop(interaction, "Mythic")

    @discord.ui.button(label="Legendary", style=discord.ButtonStyle.gray)
    async def buy_legendary(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_rarity_shop(interaction, "Legendary")
        
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
        
    @app_commands.command(name="profile", description="View your Brawl Stars profile and currencies")
    async def profile(self, interaction: discord.Interaction, user: discord.User = None):
        await interaction.response.defer()
        
        # Use mentioned user or the person running the command
        target_user = user or interaction.user
        user_id = str(target_user.id)
        
        # 1. Fetch Currency Data
        from database.mongo import get_brawl_currencies, get_user_brawlers
        currencies = await get_brawl_currencies(user_id)
        
        # 2. Fetch Brawler Progress
        owned_list = await get_user_brawlers(user_id)
        total_brawlers = len(BRAWLER_ROSTER)
        owned_count = len(owned_list)
        
        # 3. Get Emojis from Config
        from features.config import EMOJIS_CURRENCY
        c_emoji = EMOJIS_CURRENCY.get("coins", "💰")
        pp_emoji = EMOJIS_CURRENCY.get("power_points", "⚡")
        cr_emoji = EMOJIS_CURRENCY.get("credits", "💳")
        gem_emoji = EMOJIS_CURRENCY.get("gems", "💎")

        embed = discord.Embed(
            title=f"👤 {target_user.name}'s Profile",
            color=discord.Color.green()
        )
        
        # Display Brawler Progress
        embed.add_field(
            name="🗃️ Brawlers Unlocked", 
            value=f"**{owned_count} / {total_brawlers}**", 
            inline=False
        )
        
        # Display Currencies
        currency_text = (
            f"{c_emoji} **Coins:** {currencies.get('coins', 0):,}\n"
            f"{pp_emoji} **Power Points:** {currencies.get('power_points', 0):,}\n"
            f"{cr_emoji} **Credits:** {currencies.get('credits', 0):,}\n"
        )
        embed.add_field(name="💰 Currencies", value=currency_text, inline=True)

        if target_user.avatar:
            embed.set_thumbnail(url=target_user.avatar.url)
            
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="buy_brawler", description="Purchase specific brawlers using your Credits")
    async def buy_brawler(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        # Fetch the current list of owned brawlers
        owned_ids = await get_user_brawlers(user_id)
        
        # Initialize the view with lowercase IDs for easier matching
        view = BuyBrawlerView(user_id, [id.lower() for id in owned_ids])
        
        embed = discord.Embed(
            title="🛒 Brawler Shop",
            description="Pick a rarity to see brawlers you haven't unlocked yet!",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view)
    

        
# This function is required for main.py to load this file as an extension
async def setup(bot):
    await bot.add_cog(BrawlCommands(bot))