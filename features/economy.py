import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import random
from typing import Optional
import asyncio

from database.mongo import (
    get_user_balance,
    update_user_balance,
    get_leveling_data,
    update_leveling_data,
    add_item_token,
    get_item_count,
    remove_item_token,
    get_setting,
    set_setting,
    get_leaderboard_page,
    get_total_users,
    get_user_rank,
    get_levels_page,
    get_user_level_rank,
)

# --- CONFIGURATION ---
from features.config import (
    ADMIN_ROLE_ID,
    BOTS_CATEGORY_ID,
    GENERAL_CHANNEL_ID,
    EVENT_ANNOUNCEMENTS_CHANNEL_ID,
    SHOP_DATA,
    MODERATOR_ROLE_ID,
    REDEMPTION_TICKET_CATEGORY_ID,
    TRIAL_MODERATOR_ROLE_ID,
    PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS,
)

shop_choices = [
    app_commands.Choice(name=data["display"].replace("**", ""), value=key)
    for key, data in SHOP_DATA.items()
]

allowed_users = set()

DEFAULT_MONTHLY_BUDGET = 50.0

# Dollar impact for rewards that consume the monthly redemption budget.
REDEMPTION_BUDGET_COSTS = {
    "brawl pass": 10.0,
    "brawl pass+": 15.0,
    "coc gold pass": 7.0,
    "cr diamond pass": 12.0,
    "nitro": 10.0,
    "paypal": 15.0,
    "matcherino pin": 5.0,
    "pin": 5.0,
    "shoutout": 0.0,
}


def _budget_month_key() -> str:
    return datetime.utcnow().strftime("%Y-%m")


async def ensure_monthly_budget_state() -> None:
    """Reset monthly budget trackers when the calendar month changes."""
    current_key = _budget_month_key()
    stored_key = await get_setting("budget_month_key")
    if stored_key == current_key:
        return

    await set_setting("budget_month_key", current_key)
    await set_setting("monthly_budget", f"{DEFAULT_MONTHLY_BUDGET:.2f}")
    await set_setting("manual_total_spent", "0.00")

    # Keep legacy counters aligned with month rollover.
    for key in (
        "brawlpass_redeemed_count",
        "brawlpass+_redeemed_count",
        "nitro_redeemed_count",
        "paypal_redeemed_count",
        "shoutout_redeemed_count",
        "pin_redeemed_count",
    ):
        await set_setting(key, "0")


async def get_budget_totals() -> tuple[float, float, float]:
    await ensure_monthly_budget_state()

    budget_str = await get_setting("monthly_budget", f"{DEFAULT_MONTHLY_BUDGET:.2f}")
    try:
        total_budget = float(budget_str)
    except Exception:
        total_budget = DEFAULT_MONTHLY_BUDGET

    spent_str = await get_setting("manual_total_spent", "0.00")
    try:
        total_spent = float(spent_str)
    except Exception:
        total_spent = 0.0

    remaining = total_budget - total_spent
    return total_budget, total_spent, remaining


async def add_budget_spent(amount: float) -> float:
    await ensure_monthly_budget_state()
    spent_str = await get_setting("manual_total_spent", "0.00")
    try:
        current_spent = float(spent_str)
    except Exception:
        current_spent = 0.0

    updated = current_spent + max(amount, 0.0)
    await set_setting("manual_total_spent", f"{updated:.2f}")
    return updated


def _budget_cost_for_item(item_name: str) -> float:
    return REDEMPTION_BUDGET_COSTS.get(item_name.lower(), 0.0)


def _token_price_for_item(item_name: str) -> int:
    item_cfg = SHOP_DATA.get(item_name)
    if not item_cfg:
        return 0
    try:
        return int(item_cfg.get("price", 0))
    except Exception:
        return 0


def _extract_topic_value(topic: str | None, key: str) -> str | None:
    if not topic:
        return None
    for part in topic.split("|"):
        k, _, v = part.partition(":")
        if k == key:
            return v
    return None


def _is_redemption_staff(member: discord.abc.User | discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    return any(role.id in {ADMIN_ROLE_ID, MODERATOR_ROLE_ID} for role in member.roles)


def _is_redemption_ticket_channel(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if (
        not isinstance(REDEMPTION_TICKET_CATEGORY_ID, int)
        or REDEMPTION_TICKET_CATEGORY_ID <= 0
    ):
        return False
    return channel.category_id == REDEMPTION_TICKET_CATEGORY_ID


async def close_redemption_ticket_channel(
    channel: discord.TextChannel, actor: discord.Member
) -> bool:
    if not _is_redemption_staff(actor) or not _is_redemption_ticket_channel(channel):
        return False

    opener_raw = _extract_topic_value(channel.topic, "redemption-opener")
    if opener_raw and opener_raw.isdigit():
        opener = channel.guild.get_member(int(opener_raw))
        if opener is not None and not _is_redemption_staff(opener):
            await channel.set_permissions(
                opener,
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                use_application_commands=True,
            )

    await channel.send(
        f"Ticket closed by {actor.name}.",
        view=RedemptionClosedOptionsView(),
    )
    return True


async def reopen_redemption_ticket_channel(
    channel: discord.TextChannel, actor: discord.Member
) -> bool:
    if not _is_redemption_staff(actor) or not _is_redemption_ticket_channel(channel):
        return False

    opener_raw = _extract_topic_value(channel.topic, "redemption-opener")
    if opener_raw and opener_raw.isdigit():
        opener = channel.guild.get_member(int(opener_raw))
        if opener is not None:
            await channel.set_permissions(
                opener,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                use_application_commands=True,
            )

    await channel.send(f"✅ Ticket reopened by {actor.name}.")
    return True


async def close_redemption_ticket_via_command(ctx: commands.Context) -> None:
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a redemption ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_redemption_staff(
        ctx.author
    ):
        await ctx.reply("You don't have permission to close this ticket.")
        return

    ok = await close_redemption_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply(
            "This command can only be used inside redemption ticket channels."
        )


async def reopen_redemption_ticket_via_command(ctx: commands.Context) -> None:
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a redemption ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_redemption_staff(
        ctx.author
    ):
        await ctx.reply("You don't have permission to reopen this ticket.")
        return

    ok = await reopen_redemption_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply(
            "This command can only be used inside redemption ticket channels."
        )


async def handle_redemption_delete_attempt(ctx: commands.Context) -> None:
    await ctx.reply(
        "`!delete` is disabled for redemption tickets. Use `!close` and choose one of the delete options."
    )


class RedemptionClosedOptionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Reopen",
        style=discord.ButtonStyle.success,
        custom_id="redeem_reopen_ticket",
    )
    async def reopen_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Only server members can use this.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This only works in redemption tickets.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        ok = await reopen_redemption_ticket_channel(
            interaction.channel, interaction.user
        )
        if ok:
            await interaction.followup.send("Ticket reopened.", ephemeral=True)
        else:
            await interaction.followup.send(
                "This button can only be used in redemption tickets by staff.",
                ephemeral=True,
            )

    @discord.ui.button(
        label="Give back tokens and delete",
        style=discord.ButtonStyle.primary,
        custom_id="redeem_refund_delete",
    )
    async def refund_delete_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Only server members can use this.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This only works in redemption tickets.", ephemeral=True
            )
            return
        if not _is_redemption_staff(
            interaction.user
        ) or not _is_redemption_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "This button can only be used in redemption tickets by staff.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        opener_raw = _extract_topic_value(
            interaction.channel.topic, "redemption-opener"
        )
        item = _extract_topic_value(interaction.channel.topic, "item")
        if opener_raw and opener_raw.isdigit() and item:
            refund_amount = _token_price_for_item(item)
            if refund_amount > 0:
                current_balance = await get_user_balance(opener_raw)
                await update_user_balance(opener_raw, current_balance + refund_amount)

        await interaction.channel.delete(
            reason=f"Redemption ticket refunded and deleted by {interaction.user}"
        )

    @discord.ui.button(
        label="Reduce from budget and delete",
        style=discord.ButtonStyle.danger,
        custom_id="redeem_budget_delete",
    )
    async def budget_delete_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Only server members can use this.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This only works in redemption tickets.", ephemeral=True
            )
            return
        if not _is_redemption_staff(
            interaction.user
        ) or not _is_redemption_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "This button can only be used in redemption tickets by staff.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        item = _extract_topic_value(interaction.channel.topic, "item") or ""
        budget_raw = _extract_topic_value(interaction.channel.topic, "budget_usd")
        try:
            cost = (
                float(budget_raw)
                if budget_raw is not None
                else _budget_cost_for_item(item)
            )
        except ValueError:
            cost = _budget_cost_for_item(item)

        await add_budget_spent(cost)
        await interaction.channel.delete(
            reason=f"Redemption fulfilled and deleted by {interaction.user}"
        )


# Helper
async def shop_item_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    choices = []
    for key, data in SHOP_DATA.items():
        if current.lower() in key.lower() or current.lower() in data["display"].lower():
            choices.append(app_commands.Choice(name=data["display"], value=key))
    return choices[:25]


# --- VIEWS ---


class LeaderboardView(discord.ui.View):
    def __init__(self, author: discord.User):
        super().__init__(timeout=60)
        self.page = 0
        self.author = author  # This is now correctly a User object
        self.per_page = 10

    async def generate_embed(self) -> discord.Embed:
        offset = self.page * self.per_page
        entries = await get_leaderboard_page(offset, self.per_page)

        embed = discord.Embed(
            title="🏆 **R7 Token Leaderboard** 🏆", color=discord.Color.gold()
        )

        if entries:
            description_lines = []
            for index, user_doc in enumerate(entries, start=offset + 1):
                uid = user_doc["_id"]
                bal = user_doc["balance"]

                if index == 1:
                    rank = "🥇"
                elif index == 2:
                    rank = "🥈"
                elif index == 3:
                    rank = "🥉"
                else:
                    rank = f"**#{index}**"

                # Format: 🥇 <@User> - 💰 **Balance**
                line = f"{rank} <@{uid}> - 💰 **{int(bal)}**"
                description_lines.append(line)

            embed.description = "\n".join(description_lines)
        else:
            embed.description = "No entries to display."

        # Ensure we pass the ID as a String to the database
        user_rank = await get_user_rank(str(self.author.id))

        embed.set_footer(text=f"Page {self.page + 1} | Your Rank: {user_rank}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def previous(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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
            title="🏆 **Server Level Leaderboard** 🏆", color=discord.Color.gold()
        )

        if entries:
            description_lines = []
            for index, user_doc in enumerate(entries, start=offset + 1):
                uid = user_doc["_id"]
                lvl = user_doc["level"]
                exp = user_doc["exp"]

                # Match emojis to the Token Leaderboard
                if index == 1:
                    rank = "🥇"
                elif index == 2:
                    rank = "🥈"
                elif index == 3:
                    rank = "🥉"
                else:
                    rank = f"**#{index}**"

                # Format: 🥇 <@User> - Level **10** | **500** EXP
                line = f"{rank} <@{uid}> - Level **{lvl}** | **{exp}** EXP"
                description_lines.append(line)

            embed.description = "\n".join(description_lines)
        else:
            embed.description = "No leveled users yet!"

        user_rank = await get_user_level_rank(str(self.author.id))
        embed.set_footer(text=f"Page {self.page + 1} | Your Rank: #{user_rank}")
        return embed

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.blurple)
    async def previous(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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


class ShopPaginationView(discord.ui.View):
    def __init__(self, data: dict, items_per_page: int = 4):
        super().__init__(timeout=60)
        self.data = list(data.items())
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.data) - 1) // items_per_page + 1

    def create_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.data[start:end]

        embed = discord.Embed(
            title="🛒 **R7 Token Shop** 🛒", color=discord.Color.blue()
        )
        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} | Use /buy <item> to purchase!"
        )

        for key, info in page_items:
            embed.add_field(
                name=info["display"],
                value=f"{info['desc']}\n**Price:** {info['price']} R7 tokens",
                inline=False,
            )
        return embed

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1

    @discord.ui.button(
        label="◀ Previous", style=discord.ButtonStyle.blurple, disabled=True
    )
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.blurple,
    )
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


class DropView(discord.ui.View):
    def __init__(self, amount):
        super().__init__(timeout=None)
        self.amount = amount
        self.claimed = False

    @discord.ui.button(
        label="Claim Supply Drop", style=discord.ButtonStyle.green, emoji="🎁"
    )
    async def claim_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        if any(role.id == MODERATOR_ROLE_ID for role in interaction.user.roles):
            await interaction.followup.send(
                "❌ Staff cannot claim supply drops!", ephemeral=False
            )
            return

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
        await interaction.followup.send(
            f"🎉 **+{self.amount} Tokens** added to your account!", ephemeral=True
        )


# --- COG ---


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supply_drop_task.start()

    async def cog_load(self):
        self.bot.add_view(RedemptionClosedOptionsView())

    def cog_unload(self):
        self.supply_drop_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.content.startswith("!"):
            return

        # Skip token rewards for messages in the 'BOTS' category
        if message.channel.category and message.channel.category.id == BOTS_CATEGORY_ID:
            return

        # Skip token/XP rewards for bot command channels
        if message.channel.id in PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS:
            return

        user_id = str(message.author.id)
        current_timestamp = time.time()
        datetime.utcnow().strftime("%Y-%m-%d")

        if message.channel.id == GENERAL_CHANNEL_ID:
            # --- TRACK DAILY MESSAGE COUNT (tied to /daily cooldown window) ---
            # Format: "LAST_DAILY_TIMESTAMP:COUNT" — resets when user claims /daily
            last_daily_str = await get_setting(f"daily_{user_id}")
            window_key = last_daily_str if last_daily_str else "0"

            daily_msg_data = await get_setting(
                f"daily_msg_count_{user_id}", f"{window_key}:0"
            )
            stored_window_key, count = daily_msg_data.split(":", 1)

            if stored_window_key == window_key:
                new_count = int(count) + 1
            else:
                new_count = 1  # User claimed /daily since last message, reset to 1

            await set_setting(f"daily_msg_count_{user_id}", f"{window_key}:{new_count}")

            # --- PART 1: TOKENS (ON 20s COOLDOWN) ---
            last_message_str = await get_setting(f"last_message_{user_id}")
            should_award_tokens = False

            if last_message_str:
                try:
                    last_message_ts = float(last_message_str)
                    time_diff = current_timestamp - last_message_ts

                    # Check for 20s cooldown OR bugged negative timestamps
                    if time_diff >= 20 or time_diff < -3600:
                        should_award_tokens = True
                except ValueError:
                    should_award_tokens = True
            else:
                should_award_tokens = True

            if should_award_tokens:
                earned_tokens = random.randint(2, 5)

                # Booster Bonus: 17.5% Chance (Avg 5% increase)
                SERVER_BOOSTER_ROLE_ID = 647685778255642626
                if message.guild:
                    booster_role = message.guild.get_role(SERVER_BOOSTER_ROLE_ID)
                    if booster_role and booster_role in message.author.roles:
                        if random.random() < 0.175:
                            earned_tokens += 1

                current_balance = await get_user_balance(user_id)
                await update_user_balance(user_id, current_balance + earned_tokens)
                await set_setting(f"last_message_{user_id}", str(current_timestamp))

        # --- PART 2: XP & LEVELING (EVERY MESSAGE) ---
        EXP_PER_MESSAGE = 10
        BASE_EXP = 100

        level, exp = await get_leveling_data(user_id)
        exp += EXP_PER_MESSAGE

        while True:
            required_exp = int(BASE_EXP * (1.5 ** (level - 1)))
            if exp >= required_exp:
                exp -= required_exp
                level += 1

                embed = discord.Embed(
                    title="🎉 Level Up!",
                    description=f"{message.author.mention}, you reached **Level {level}**!",
                    color=discord.Color.green(),
                )
                embed.add_field(
                    name="Bonus",
                    value="Daily rewards increased by **5%**!",
                    inline=False,
                )
                try:
                    await message.channel.send(embed=embed)
                except discord.Forbidden:
                    pass  # Ignore if bot can't send in that channel
            else:
                break

        await update_leveling_data(user_id, level, exp)

    # --- AUTO DROP TASK ---
    @tasks.loop(hours=6)
    async def supply_drop_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(random.randint(0, 45600))

        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not channel:
            return

        amount = random.randint(100, 300)
        embed = discord.Embed(
            title="🪂 Supply Drop Incoming!",
            description=f"A crate containing **{amount} R7 Tokens** has landed!\n\n**Click FAST to claim it!**",
            color=discord.Color.red(),
        )
        await channel.send(embed=embed, view=DropView(amount))
        print(f"🪂 Auto-Drop sent: {amount} tokens")

    # --- MANUAL DROP COMMAND ---
    @app_commands.command(name="drop", description="ADMIN: Force a supply drop.")
    async def drop(self, interaction: discord.Interaction, amount: int):
        if not await self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied", ephemeral=True
            )
            return

        target_channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not target_channel:
            await interaction.response.send_message(
                "❌ Error: Could not find the General channel.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🪂 Admin Supply Drop!",
            description=f"Admin summoned **{amount} R7 Tokens**!",
            color=discord.Color.gold(),
        )
        view = DropView(amount)
        await target_channel.send(embed=embed, view=view)
        await interaction.response.send_message(
            f"✅ Drop sent to {target_channel.mention}!", ephemeral=True
        )

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
        # Create the view with 4 items per page
        view = ShopPaginationView(SHOP_DATA, items_per_page=4)
        view.update_buttons()
        await interaction.response.send_message(embed=view.create_embed(), view=view)

    @app_commands.command(name="buy", description="Purchase an item from the shop.")
    @app_commands.describe(item="Select the item you want to buy.")
    @app_commands.choices(item=shop_choices)
    async def buy(self, interaction: discord.Interaction, item: str):
        forbidden_roles = [TRIAL_MODERATOR_ROLE_ID, MODERATOR_ROLE_ID, ADMIN_ROLE_ID]

        # Check if the user has any of these roles
        if any(role.id in forbidden_roles for role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ **Access Denied:** Staff members cannot purchase shop items.",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        if item not in SHOP_DATA:
            await interaction.response.send_message(
                "❌ Error: Item not found.", ephemeral=True
            )
            return

        item_info = SHOP_DATA[item]
        price = item_info["price"]
        balance = await get_user_balance(user_id)

        if balance < price:
            embed = discord.Embed(
                title="❌ **Insufficient Balance**",
                description=f"You need **{int(price - balance)} more R7 tokens** to purchase **{item_info['display']}**.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        new_balance = balance - price
        await update_user_balance(user_id, new_balance)
        await add_item_token(user_id, item)

        embed = discord.Embed(
            title="✅ **Purchase Successful**",
            description=f"You have purchased **{item_info['display']}**!\nPlease use `/redeem` to claim it.",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Your new balance: {int(new_balance)} R7 tokens")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="redeem", description="Redeem an item you own.")
    @app_commands.describe(item="Select the item you want to redeem.")
    @app_commands.choices(item=shop_choices)
    async def redeem(self, interaction: discord.Interaction, item: str):
        forbidden_roles = [TRIAL_MODERATOR_ROLE_ID, MODERATOR_ROLE_ID, ADMIN_ROLE_ID]

        # Check if the user has any of these roles
        if any(role.id in forbidden_roles for role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ **Access Denied:** Staff members cannot redeem shop rewards.",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        if item not in SHOP_DATA:
            await interaction.response.send_message(
                "❌ Error: Item data not found.", ephemeral=True
            )
            return

        item_info = SHOP_DATA[item]
        qty = await get_item_count(user_id, item)
        if qty < 1:
            embed = discord.Embed(
                title="❌ **Redemption Failed**",
                description=f"You do not own **{item_info['display']}**.\nPurchase it first with `/buy`.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Budget guard: block redemption when monthly budget cannot cover this item.
        budget_cost = _budget_cost_for_item(item)
        if budget_cost > 0:
            _, _, remaining_budget = await get_budget_totals()
            if budget_cost > remaining_budget:
                embed = discord.Embed(
                    title="❌ **Budget Limit Reached**",
                    description=(
                        f"This redemption requires **${budget_cost:.2f}**, but only "
                        f"**${remaining_budget:.2f}** remains in the monthly budget."
                    ),
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        await interaction.response.defer()

        try:
            if (
                not isinstance(REDEMPTION_TICKET_CATEGORY_ID, int)
                or REDEMPTION_TICKET_CATEGORY_ID <= 0
            ):
                await interaction.followup.send(
                    "❌ Redemption category is not configured.",
                    ephemeral=True,
                )
                return

            category = interaction.guild.get_channel(REDEMPTION_TICKET_CATEGORY_ID)
            if not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send(
                    "❌ Configured redemption category channel was not found.",
                    ephemeral=True,
                )
                return

            balance_before = await get_user_balance(user_id)

            await remove_item_token(user_id, item)

            tracking_keys = {
                "brawl pass": "brawlpass_redeemed_count",
                "brawl pass+": "brawlpass+_redeemed_count",
                "nitro": "nitro_redeemed_count",
                "paypal": "paypal_redeemed_count",
                "shoutout": "shoutout_redeemed_count",
            }
            if item in tracking_keys:
                key = tracking_keys[item]
                current = int(await get_setting(key, "0"))
                await set_setting(key, str(current + 1))

            ch = await interaction.guild.create_text_channel(
                f"ticket-{interaction.user.name}",
                category=category,
            )
            await ch.set_permissions(
                interaction.guild.default_role, read_messages=False
            )
            await ch.set_permissions(
                interaction.user, read_messages=True, send_messages=True
            )

            for staff_role_id in (ADMIN_ROLE_ID, MODERATOR_ROLE_ID):
                staff_role = interaction.guild.get_role(staff_role_id)
                if staff_role:
                    await ch.set_permissions(
                        staff_role,
                        read_messages=True,
                        send_messages=True,
                        manage_messages=True,
                    )

            await ch.edit(
                topic=(
                    f"redemption-opener:{interaction.user.id}"
                    f"|item:{item}|budget_usd:{budget_cost:.2f}"
                ),
                reason="Store redemption ticket metadata",
            )

            instructions = "- Provide necessary details."
            if "brawl pass" in item:
                instructions = "- Provide your in-game ID and a link to add you."
            elif "brawl pass" in item:
                instructions = "- Provide your in-game ID and a link to add you."
            elif "nitro" in item:
                instructions = (
                    "- Provide the Discord account you'd like the Nitro gifted to."
                )
            elif "paypal" in item:
                instructions = "- Provide your PayPal email address."
            elif "shoutout" in item:
                instructions = "- Provide the message you want to be shouted out."

            embed = discord.Embed(
                title="✅ **Redemption Successful**",
                description=f"A ticket has been created in {ch.mention}.\nPlease provide the following details to redeem your **{item_info['display']}**:\n{instructions}",
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=embed)
            item_price = item_info["price"]
            balance_after = balance_before
            balance_display_before = balance_before + item_price
            ticket_embed = discord.Embed(
                title=f"🎫 **{item.title()} Redemption Ticket**",
                description=f"{interaction.user.mention}, please provide the following details in this ticket channel:\n\n{instructions}",
                color=discord.Color.blue(),
            )
            ticket_embed.add_field(
                name="Item Price", value=f"{item_price:,} R7 tokens", inline=True
            )
            ticket_embed.add_field(
                name="Balance Before",
                value=f"{balance_display_before:,} R7 tokens",
                inline=True,
            )
            ticket_embed.add_field(
                name="Balance After", value=f"{balance_after:,} R7 tokens", inline=True
            )
            await ch.send(embed=ticket_embed)

        except Exception as e:
            await add_item_token(user_id, item, quantity=1)
            await interaction.followup.send(
                f"❌ **Error** Failed to create ticket: {e}", ephemeral=True
            )

    @app_commands.command(name="daily", description="Claim your daily R7 tokens!")
    async def daily(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        now = datetime.utcnow()

        # 1. FETCH DATA
        last_daily_str = await get_setting(f"daily_{user_id}")
        window_key = last_daily_str if last_daily_str else "0"

        daily_msg_data = await get_setting(
            f"daily_msg_count_{user_id}", f"{window_key}:0"
        )
        stored_window_key, count = daily_msg_data.split(":", 1)
        msg_count = int(count) if stored_window_key == window_key else 0

        cooldown_remaining = None
        if last_daily_str:
            last_daily = datetime.utcfromtimestamp(float(last_daily_str))
            time_since = now - last_daily
            if time_since < timedelta(days=1):
                cooldown_remaining = timedelta(days=1) - time_since

        # 2. COMBINED CHECK (MESSAGES OR COOLDOWN)
        if msg_count < 5 or cooldown_remaining:
            # Prepare the status strings
            msg_status = (
                "✅ **Complete** (5/5)"
                if msg_count >= 5
                else f"❌ **Incomplete** ({msg_count}/5)"
            )

            if cooldown_remaining:
                h, r = divmod(cooldown_remaining.total_seconds(), 3600)
                m, _ = divmod(r, 60)
                time_status = f"❌ **Cooldown:** {int(h)}h {int(m)}m remaining"
            else:
                time_status = "✅ **Ready to claim!**"

            embed = discord.Embed(
                title="🔒 Daily Reward Status",
                description="You must complete both requirements to claim your tokens:",
                color=discord.Color.orange(),
            )
            embed.add_field(name="Chat Activity", value=msg_status, inline=False)
            embed.add_field(name="Time Requirement", value=time_status, inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        # 3. GRANT REWARD (If both checks pass)
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
                f"You received **{final_tokens} R7 tokens**!\n"
                f"New balance: **{int(new_balance)}** | Level: **{level}**"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="balance", description="Check your or another user's R7 token balance."
    )
    @app_commands.describe(
        user="The user whose balance you want to check (leave blank for your own balance)."
    )
    async def balance(
        self, interaction: discord.Interaction, user: Optional[discord.User] = None
    ):
        await interaction.response.defer()
        target = user or interaction.user
        balance = await get_user_balance(str(target.id))
        embed = discord.Embed(
            title="💰 **R7 Token Balance**",
            description=f"<@{target.id}> has **{int(balance)} R7 tokens**.",
            color=discord.Color.blue(),
        )
        embed.set_footer(
            text=f"Requested by {interaction.user.name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="leaderboard", description="View the server's R7 token leaderboard."
    )
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # FIX: Pass interaction.user, NOT interaction
        view = LeaderboardView(interaction.user)
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="level", description="Check your or another user's level and progress."
    )
    @app_commands.describe(user="The user whose level you want to check")
    async def level(
        self, interaction: discord.Interaction, user: Optional[discord.Member] = None
    ):
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
        filled_length = min(
            progress_bar_length, int(progress_bar_length * (exp / next_level_exp))
        )
        progress_bar = "🟩" * filled_length + "⬜" * (
            progress_bar_length - filled_length
        )

        embed = discord.Embed(
            title=f"📊 {user.display_name}'s Level Progress", color=discord.Color.blue()
        )
        embed.add_field(name="📈 Level", value=f"**{level}**", inline=True)
        embed.add_field(name="⚡ EXP", value=f"{exp}/{next_level_exp}", inline=True)
        embed.add_field(
            name="📊 Progress",
            value=f"{progress_bar} `{progress_percentage:.1f}%`",
            inline=False,
        )

        if level < 10:
            footer = "Keep chatting to level up! You're doing great!"
        elif level < 20:
            footer = "Nice progress! The challenges are getting tougher."
        else:
            footer = "Legendary status! Each level is a real achievement now!"
        embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="levels-leaderboard", description="View the server's level leaderboard"
    )
    async def levels_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = LevelsLeaderboardView(interaction.user)
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="check-budget", description="Check the remaining budget for redemptions."
    )
    async def check_budget(self, interaction: discord.Interaction):
        total_budget, total_spent, remaining = await get_budget_totals()

        int(await get_setting("brawlpass_redeemed_count", "0"))
        int(await get_setting("nitro_redeemed_count", "0"))
        int(await get_setting("pin_redeemed_count", "0"))

        now = datetime.now(timezone.utc)
        if now.month == 12:
            reset_date = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            reset_date = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        reset_timestamp = int(reset_date.timestamp())

        embed = discord.Embed(title="💰 **Budget Status**", color=discord.Color.blue())
        embed.description = (
            f"**Total Monthly Budget:** ${total_budget:.2f}\n"
            f"**Total Spent on Redemptions:** ${total_spent:.2f}\n"
            f"**Remaining Budget:** ${remaining:.2f}\n"
            f"**Budget Resets:** <t:{reset_timestamp}:R> (<t:{reset_timestamp}:F>)"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="set-budget",
        description="Set the current remaining redemption budget in dollars.",
    )
    async def set_budget(self, interaction: discord.Interaction, amount: float):
        if not await self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied", ephemeral=True
            )
            return
        if amount < 0:
            await interaction.response.send_message(
                "❌ Budget must be 0 or higher.", ephemeral=True
            )
            return

        await ensure_monthly_budget_state()
        budget_str = await get_setting(
            "monthly_budget", f"{DEFAULT_MONTHLY_BUDGET:.2f}"
        )
        try:
            total_budget = float(budget_str)
        except Exception:
            total_budget = DEFAULT_MONTHLY_BUDGET

        if amount > total_budget:
            await interaction.response.send_message(
                f"❌ Current budget cannot exceed total monthly budget (${total_budget:.2f}).",
                ephemeral=True,
            )
            return

        new_spent = total_budget - amount
        await set_setting("manual_total_spent", f"{new_spent:.2f}")

        _, spent, remaining = await get_budget_totals()
        embed = discord.Embed(title="✅ Budget Updated", color=discord.Color.green())
        embed.description = (
            f"**Total Monthly Budget:** ${total_budget:.2f}\n"
            f"**Current Budget Set To:** ${amount:.2f}\n"
            f"**Already Spent:** ${spent:.2f}\n"
            f"**Remaining:** ${remaining:.2f}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="give", description="Give resources to a user.")
    @app_commands.describe(
        user="The user to give resources to", resource_type="Type", amount="Amount"
    )
    @app_commands.choices(
        resource_type=[
            app_commands.Choice(name="R7 Tokens", value="tokens"),
            app_commands.Choice(name="XP", value="xp"),
            app_commands.Choice(name="Levels", value="levels"),
        ]
    )
    async def give(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        resource_type: str,
        amount: int,
    ):
        if not await self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied", ephemeral=True
            )
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
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Given", description=msg, color=discord.Color.green()
            )
        )

    @app_commands.command(
        name="set-balance", description="Set a user's R7 token balance."
    )
    async def setbalance(
        self, interaction: discord.Interaction, user: discord.User, amount: int
    ):
        if not await self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied", ephemeral=True
            )
            return
        await update_user_balance(str(user.id), amount)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Balance Set",
                description=f"Set {user.mention} to {amount} tokens.",
                color=discord.Color.green(),
            )
        )

    @app_commands.command(
        name="perm", description="Grant or revoke bot command permissions."
    )
    @app_commands.describe(
        member="The user to modify permissions for", action="Add or Remove permission"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Add", value="add"),
            app_commands.Choice(name="Remove", value="remove"),
        ]
    )
    async def perm(
        self, interaction: discord.Interaction, member: discord.Member, action: str
    ):
        if not await self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied.", ephemeral=True
            )
            return
        if action == "add":
            allowed_users.add(member.id)
            await interaction.response.send_message(
                f"✅ **Added:** {member.mention} has been granted bot command permissions."
            )
        else:
            if member.id in allowed_users:
                allowed_users.remove(member.id)
                await interaction.response.send_message(
                    f"🗑️ **Removed:** {member.mention} has been revoked bot command permissions."
                )
            else:
                await interaction.response.send_message(
                    f"⚠️ {member.mention} did not have special permissions.",
                    ephemeral=True,
                )

    @app_commands.command(
        name="economy-help", description="A complete guide to the R7 Token economy."
    )
    async def economy_help(self, interaction: discord.Interaction):
        # Channel mentions for better UX
        general_ch = f"<#{GENERAL_CHANNEL_ID}>"
        event_ch = f"<#{EVENT_ANNOUNCEMENTS_CHANNEL_ID}>"

        # --- EMBED 1: WELCOME & EARNING ---
        earn_embed = discord.Embed(
            title="💰 **R7 Economy: How to Earn**",
            description=(
                "Welcome to the R7 Token system! Participate in the community to earn tokens "
                "and unlock rewards. **The reward budget resets every month!**"
            ),
            color=discord.Color.gold(),
        )
        earn_text = (
            f"💬 **Chatting:** Earn **2-5 Tokens** every message in {general_ch}! (20s cooldown)\n"
            "📅 **Daily Rewards:** Use `/daily` to claim tokens every 24h. "
            f"*Requires 5 messages sent in {general_ch} since your last `/daily` claim.*\n"
            f"🪂 **Supply Drops:** Random crates appear in {general_ch}! Click the button to claim.\n"
            f"🏆 **Events:** Earn massive token rewards in {event_ch}.\n"
            "🚀 **Booster Bonus:** Server Boosters receive a **5% increase** in coins on average."
        )
        earn_embed.add_field(name="📈 Earning Methods", value=earn_text, inline=False)
        earn_embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # --- EMBED 2: HOW TO SPEND ---
        spend_embed = discord.Embed(
            title="🛒 **R7 Economy: How to Spend**",
            description="Turn your tokens into real-world rewards.",
            color=discord.Color.blue(),
        )
        spend_text = (
            "🛒 **The Shop:** Use `/shop` to browse rewards like Brawl Pass, Discord Nitro, and PayPal.\n"
            "💳 **Purchasing:** Use `/buy <item>` to spend your tokens on an item.\n"
            "🎟️ **Redeeming:** Use `/redeem <item>` to open a ticket and claim your reward from staff."
        )
        spend_embed.add_field(name="🛍️ Shopping Flow", value=spend_text, inline=False)

        # --- EMBED 3: COMMAND REFERENCE ---
        cmd_embed = discord.Embed(
            title="📜 **Quick Command Reference**", color=discord.Color.light_grey()
        )
        cmd_text = (
            "**Standard Commands:**\n"
            "`/balance` - View your token total\n"
            "`/daily` - Claim daily tokens & check progress\n"
            "`/quests` - View active daily and weekly quests\n"
            "`/leaderboard` - See top token holders\n"
            "`/level` - Check your rank & XP progress\n"
            "`/levels-leaderboard` - See top server levels\n"
            "`/shop` - Browse the token store\n"
            "`/buy` - Purchase an item from the shop\n"
            "`/redeem` - Claim your purchased rewards\n\n"
            "**Utility:**\n"
            "`/check-budget` - See remaining monthly reward budget"
        )
        cmd_embed.description = cmd_text

        # Sending all three embeds in a single interaction response
        await interaction.response.send_message(
            embeds=[earn_embed, spend_embed, cmd_embed]
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
