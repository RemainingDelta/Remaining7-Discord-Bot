import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import random
from typing import Optional
import asyncio

from database.mongo import (
    get_user_balance, update_user_balance, 
    get_leveling_data, update_leveling_data,
    add_item_token, get_item_count, remove_item_token,
    get_setting, set_setting,
    get_leaderboard_page, get_total_users, get_user_rank,
    get_levels_page, get_user_level_rank
)

# --- CONFIGURATION ---
from features.config import (
    ADMIN_ROLE_ID,
    GENERAL_CHANNEL_ID,
    SHOP_DATA
)

shop_choices = [
    app_commands.Choice(name=data['display'].replace("**", ""), value=key)
    for key, data in SHOP_DATA.items()
]

allowed_users = set()

# Helper 
async def shop_item_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = []
    for key, data in SHOP_DATA.items():
        if current.lower() in key.lower() or current.lower() in data['display'].lower():
            choices.append(app_commands.Choice(name=data['display'], value=key))
    return choices[:25]

# --- VIEWS ---

class LeaderboardView(discord.ui.View):
    def __init__(self, author: discord.User):
        super().__init__(timeout=60)
        self.page = 0
        self.author = author # This is now correctly a User object
        self.per_page = 10

    async def generate_embed(self) -> discord.Embed:

        offset = self.page * self.per_page
        entries = await get_leaderboard_page(offset, self.per_page)
        
        embed = discord.Embed(
            title="🏆 **R7 Token Leaderboard** 🏆",
            color=discord.Color.gold()
        )
        
        if entries:
            description_lines = []
            for index, user_doc in enumerate(entries, start=offset+1):
                uid = user_doc["_id"]
                bal = user_doc["balance"]
                
                if index == 1: rank = "🥇"
                elif index == 2: rank = "🥈"
                elif index == 3: rank = "🥉"
                else: rank = f"**#{index}**"
                
                # Format: 🥇 <@User> - 💰 **Balance**
                line = f"{rank} <@{uid}> - 💰 **{bal}**"
                description_lines.append(line)
            
            embed.description = "\n".join(description_lines)
        else:
            embed.description = "No entries to display."
            
        # Ensure we pass the ID as a String to the database
        user_rank = await get_user_rank(str(self.author.id))
        
        embed.set_footer(text=f"Page {self.page + 1} | Your Rank: {user_rank}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = await self.generate_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        total = await get_total_users()
        max_page = (total - 1) // self.per_page
        if self.page < max_page:
            self.page += 1
            embed = await self.generate_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

class LevelsLeaderboardView(discord.ui.View):
    def __init__(self, author: discord.User):
        super().__init__(timeout=60)
        self.page = 0
        self.author = author
        self.per_page = 10

    async def generate_embed(self) -> discord.Embed:
        offset = self.page * self.per_page
        entries = await get_levels_page(offset, self.per_page)
        
        embed = discord.Embed(
            title="🏆 **Server Level Leaderboard** 🏆",
            description="Top members by level and experience",
            color=discord.Color.gold()
        )
        
        if entries:
            for index, user_doc in enumerate(entries, start=offset+1):
                uid = user_doc["_id"]
                lvl = user_doc["level"]
                exp = user_doc["exp"]
                
                if index == 1: rank_emoji = "👑 "
                elif index == 2: rank_emoji = "🥈 "
                elif index == 3: rank_emoji = "🥉 "
                else: rank_emoji = f"**#{index}** "
                
                embed.add_field(
                    name=f"{rank_emoji}<@{uid}>",
                    value=f"Level {lvl} | {exp} EXP",
                    inline=False
                )
        else:
            embed.description = "No leveled users yet!"
            
        user_rank = await get_user_level_rank(str(self.author.id))
        embed.set_footer(text=f"Page {self.page + 1} | Your Rank: #{user_rank}")
        return embed

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.blurple)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = await self.generate_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.blurple)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        total = await get_total_users()
        max_page = (total - 1) // self.per_page
        if self.page < max_page:
            self.page += 1
            embed = await self.generate_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

class DropView(discord.ui.View):
    def __init__(self, amount):
        super().__init__(timeout=1800) # 30 mins
        self.amount = amount
        self.claimed = False

    @discord.ui.button(label="Claim Supply Drop", style=discord.ButtonStyle.green, emoji="🎁")
    async def claim_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if self.claimed:
            await interaction.followup.send("❌ Already claimed!", ephemeral=True)
            return
        
        self.claimed = True
        
        # 1. Update Database
        uid = str(interaction.user.id)
        current_bal = await get_user_balance(uid)
        await update_user_balance(uid, current_bal + self.amount)
        
        # 2. Update Button to "Claimed"
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        button.style = discord.ButtonStyle.secondary
        
        # 3. Edit Message
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.light_grey()
        embed.description = f"**📦 CLAIMED!**\n\n**{interaction.user.mention}** grabbed **{self.amount} Tokens**!"
        
        await interaction.edit_original_response(embed=embed, view=self)
        await interaction.followup.send(f"🎉 **+{self.amount} Tokens** added to your account!", ephemeral=True)

# --- COG ---

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supply_drop_task.start()

    def cog_unload(self):
        self.supply_drop_task.cancel()

    # --- AUTO DROP TASK ---
    @tasks.loop(hours=6)
    async def supply_drop_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(random.randint(0, 45600))
        
        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel: return

        amount = random.randint(100, 300)
        embed = discord.Embed(
            title="🪂 Supply Drop Incoming!",
            description=f"A crate containing **{amount} R7 Tokens** has landed!\n\n**Click FAST to claim it!**",
            color=discord.Color.red()
        )
        await channel.send(embed=embed, view=DropView(amount))
        print(f"🪂 Auto-Drop sent: {amount} tokens")

    # --- MANUAL DROP COMMAND ---
    @app_commands.command(name="drop", description="ADMIN: Force a supply drop.")
    async def drop(self, interaction: discord.Interaction, amount: int):
        if not await self.has_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied", ephemeral=True)
            return

        target_channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not target_channel:
            await interaction.response.send_message("❌ Error: Could not find the General channel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🪂 Admin Supply Drop!",
            description=f"Admin summoned **{amount} R7 Tokens**!",
            color=discord.Color.gold()
        )
        view = DropView(amount)
        await target_channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Drop sent to {target_channel.mention}!", ephemeral=True)

    async def has_permission(self, interaction: discord.Interaction):
        if isinstance(interaction.user, discord.Member):
            if interaction.user.get_role(ADMIN_ROLE_ID):
                return True
        if interaction.user.id in allowed_users:
            return True
        return False

    # --- SHOP & REDEMPTION COMMANDS ---

    @app_commands.command(name="shop", description="View the R7 token shop.")
    async def shop(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🛒 **R7 Token Shop** 🛒", color=discord.Color.blue())
        for key, info in SHOP_DATA.items():
            embed.add_field(name=info['display'], value=f"{info['desc']}\n**Price:** {info['price']} R7 tokens", inline=False)
        embed.set_footer(text="Use /buy <item> to purchase!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Purchase an item from the shop.")
    @app_commands.describe(item="Select the item you want to buy.")
    @app_commands.choices(item=shop_choices) 
    async def buy(self, interaction: discord.Interaction, item: str):
        user_id = str(interaction.user.id)
        if item not in SHOP_DATA:
            await interaction.response.send_message("❌ Error: Item not found.", ephemeral=True)
            return

        item_info = SHOP_DATA[item]
        price = item_info['price']
        balance = await get_user_balance(user_id)

        if balance < price:
            embed = discord.Embed(
                title="❌ **Insufficient Balance**",
                description=f"You need **{price - balance} more R7 tokens** to purchase **{item_info['display']}**.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        new_balance = balance - price
        await update_user_balance(user_id, new_balance)
        await add_item_token(user_id, item)

        embed = discord.Embed(
            title="✅ **Purchase Successful**",
            description=f"You have purchased **{item_info['display']}**!\nPlease use `/redeem` to claim it.",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Your new balance: {new_balance} R7 tokens")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="redeem", description="Redeem an item you own.")
    @app_commands.describe(item="Select the item you want to redeem.")
    @app_commands.choices(item=shop_choices)
    async def redeem(self, interaction: discord.Interaction, item: str):
        user_id = str(interaction.user.id)
        if item not in SHOP_DATA:
            await interaction.response.send_message("❌ Error: Item data not found.", ephemeral=True)
            return
            
        item_info = SHOP_DATA[item]
        qty = await get_item_count(user_id, item)
        if qty < 1:
            embed = discord.Embed(
                title="❌ **Redemption Failed**", 
                description=f"You do not own **{item_info['display']}**.\nPurchase it first with `/buy`.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await remove_item_token(user_id, item)

        tracking_keys = {
            "brawl pass": "brawlpass_redeemed_count",
            "nitro": "nitro_redeemed_count",
            "paypal": "paypal_redeemed_count",
            "shoutout": "shoutout_redeemed_count"
        }
        if item in tracking_keys:
            key = tracking_keys[item]
            current = int(await get_setting(key, "0"))
            await set_setting(key, str(current + 1))

        try:
            ch = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}")
            await ch.set_permissions(interaction.guild.default_role, read_messages=False)
            await ch.set_permissions(interaction.user, read_messages=True, send_messages=True)
            
            from features.config import ADMIN_ROLE_ID 
            staff_role = interaction.guild.get_role(ADMIN_ROLE_ID)
            if staff_role:
                await ch.set_permissions(staff_role, read_messages=True, send_messages=True, manage_messages=True)

            instructions = "- Provide necessary details."
            if "brawl pass" in item: instructions = "- Provide your in-game ID and a link to add you."
            elif "nitro" in item: instructions = "- Provide the Discord account you'd like the Nitro gifted to."
            elif "paypal" in item: instructions = "- Provide your PayPal email address."
            elif "shoutout" in item: instructions = "- Provide the message you want to be shouted out."

            embed = discord.Embed(
                title="✅ **Redemption Successful**",
                description=f"A ticket has been created in {ch.mention}.\nPlease provide the following details to redeem your **{item_info['display']}**:\n{instructions}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            ticket_embed = discord.Embed(
                title=f"🎫 **{item.title()} Redemption Ticket**",
                description=f"{interaction.user.mention}, please provide the following details in this ticket channel:\n\n{instructions}",
                color=discord.Color.blue()
            )
            await ch.send(embed=ticket_embed)

        except Exception as e:
            await interaction.response.send_message(f"❌ **Error** Failed to create ticket: {e}", ephemeral=True)

    @app_commands.command(name="daily", description="Claim your daily R7 tokens!")
    async def daily(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        now = datetime.utcnow()
        last_daily_str = await get_setting(f"daily_{user_id}")
        if last_daily_str:
            last_daily = datetime.utcfromtimestamp(float(last_daily_str))
            time_since = now - last_daily
            if time_since < timedelta(days=1):
                remaining = timedelta(days=1) - time_since
                hours, remainder = divmod(remaining.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                embed = discord.Embed(
                    title="⏳ Daily Reward Cooldown",
                    description=f"{interaction.user.mention}, please wait **{int(hours)} hours, {int(minutes)} minutes** before claiming your daily tokens again.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return

        daily_tokens = random.randint(80, 160)
        level, _ = await get_leveling_data(user_id)
        bonus_multiplier = 1 + (level - 1) * 0.05
        final_tokens = int(daily_tokens * bonus_multiplier)

        current_balance = await get_user_balance(user_id)
        new_balance = current_balance + final_tokens
        await update_user_balance(user_id, new_balance)
        await set_setting(f"daily_{user_id}", str(now.timestamp()))

        embed = discord.Embed(
            title="🎉 Daily Reward Claimed!",
            description=(
                f"{interaction.user.mention} received **{final_tokens} R7 tokens** (including level bonus)!\n"
                f"New balance: **{new_balance} R7 tokens**.\n"
                f"Current level: **{level}**."
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Come back in 24 hours for more rewards!")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="balance", description="Check your or another user's R7 token balance.")
    @app_commands.describe(user="The user whose balance you want to check (leave blank for your own balance).")
    async def balance(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        await interaction.response.defer()
        target = user or interaction.user
        balance = await get_user_balance(str(target.id))
        embed = discord.Embed(
            title="💰 **R7 Token Balance**",
            description=f"<@{target.id}> has **{balance} R7 tokens**.",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the server's R7 token leaderboard.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # FIX: Pass interaction.user, NOT interaction
        view = LeaderboardView(interaction.user) 
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="level", description="Check your or another user's level and progress.")
    @app_commands.describe(user="The user whose level you want to check")
    async def level(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        user = user or interaction.user
        user_id = str(user.id)
        level, exp = await get_leveling_data(user_id)
        BASE_EXP = 100
        EXP_GROWTH_PHASE_CUTOFF = 20
        if level <= EXP_GROWTH_PHASE_CUTOFF:
            next_level_exp = int(BASE_EXP * (1.5 ** (level - 1)))
        else:
            level_20_exp = int(BASE_EXP * (1.5 ** (EXP_GROWTH_PHASE_CUTOFF - 1)))
            next_level_exp = level_20_exp + 5000 * (level - EXP_GROWTH_PHASE_CUTOFF)
            
        progress_percentage = (exp / next_level_exp) * 100 if next_level_exp > 0 else 0
        progress_bar_length = 10
        filled_length = min(progress_bar_length, int(progress_bar_length * (exp / next_level_exp)))
        progress_bar = "🟩" * filled_length + "⬜" * (progress_bar_length - filled_length)

        embed = discord.Embed(title=f"📊 {user.display_name}'s Level Progress", color=discord.Color.blue())
        embed.add_field(name="📈 Level", value=f"**{level}**", inline=True)
        embed.add_field(name="⚡ EXP", value=f"{exp}/{next_level_exp}", inline=True)
        embed.add_field(name="📊 Progress", value=f"{progress_bar} `{progress_percentage:.1f}%`", inline=False)
        
        if level < 10: footer = "Keep chatting to level up! You're doing great!"
        elif level < 20: footer = "Nice progress! The challenges are getting tougher."
        else: footer = "Legendary status! Each level is a real achievement now!"
        embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="levels_leaderboard", description="View the server's level leaderboard")
    async def levels_leaderboard(self, interaction: discord.Interaction):
        view = LevelsLeaderboardView(interaction.user)
        embed = await view.generate_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="checkbudget", description="Check the remaining budget for redemptions.")
    async def check_budget(self, interaction: discord.Interaction):
        budget_str = await get_setting("monthly_budget", "50.00")
        try: TOTAL_BUDGET = float(budget_str)
        except: TOTAL_BUDGET = 50.00
        
        bp_c = int(await get_setting("brawlpass_redeemed_count", "0"))
        ni_c = int(await get_setting("nitro_redeemed_count", "0"))
        pi_c = int(await get_setting("pin_redeemed_count", "0"))
        manual_spent = await get_setting("manual_total_spent")
        if manual_spent:
            total_spent = float(manual_spent)
        else:
            total_spent = (bp_c * 10) + (ni_c * 10) + (pi_c * 5)
        
        remaining = TOTAL_BUDGET - total_spent
        embed = discord.Embed(title="💰 **Budget Status**", color=discord.Color.blue())
        embed.description = (
            f"**Total Monthly Budget:** ${TOTAL_BUDGET:.2f}\n"
            f"**Total Spent on Redemptions:** ${total_spent:.2f}\n"
            f"**Remaining Budget:** ${remaining:.2f}\n\n"
            f"**Redemptions This Month:**\n"
            f"- Brawl Pass: {bp_c}\n- Nitro: {ni_c}\n- Matcherino Pin: {pi_c}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="give", description="Give resources to a user.")
    @app_commands.describe(user="The user to give resources to", resource_type="Type", amount="Amount")
    @app_commands.choices(resource_type=[
        app_commands.Choice(name="R7 Tokens", value="tokens"),
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="Levels", value="levels")
    ])
    async def give(self, interaction: discord.Interaction, user: discord.User, resource_type: str, amount: int):
        if not await self.has_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied", ephemeral=True)
            return
        
        uid = str(user.id)
        if resource_type == "tokens":
            cur = await get_user_balance(uid)
            await update_user_balance(uid, cur + amount)
            msg = f"Gave **{amount} tokens** to {user.mention}."
        elif resource_type == "xp":
            lvl, exp = await get_leveling_data(uid)
            await update_leveling_data(uid, lvl, exp + amount)
            msg = f"Gave **{amount} XP** to {user.mention}."
        elif resource_type == "levels":
            lvl, exp = await get_leveling_data(uid)
            await update_leveling_data(uid, lvl + amount, exp)
            msg = f"Gave **{amount} Levels** to {user.mention}."
        await interaction.response.send_message(embed=discord.Embed(title="✅ Given", description=msg, color=discord.Color.green()))

    @app_commands.command(name="setbalance", description="Set a user's R7 token balance.")
    async def setbalance(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if not await self.has_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied", ephemeral=True)
            return
        await update_user_balance(str(user.id), amount)
        await interaction.response.send_message(embed=discord.Embed(title="✅ Balance Set", description=f"Set {user.mention} to {amount} tokens.", color=discord.Color.green()))

    @app_commands.command(name="perm", description="Grant or revoke bot command permissions.")
    @app_commands.describe(member="The user to modify permissions for", action="Add or Remove permission")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove")
    ])
    async def perm(self, interaction: discord.Interaction, member: discord.Member, action: str):
        if not await self.has_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied.", ephemeral=True)
            return
        if action == "add":
            allowed_users.add(member.id)
            await interaction.response.send_message(f"✅ **Added:** {member.mention} has been granted bot command permissions.")
        else:
            if member.id in allowed_users:
                allowed_users.remove(member.id)
                await interaction.response.send_message(f"🗑️ **Removed:** {member.mention} has been revoked bot command permissions.")
            else:
                await interaction.response.send_message(f"⚠️ {member.mention} did not have special permissions.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Economy(bot))