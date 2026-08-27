import io
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
    get_user_data,
    update_user_balance,
    increment_user_balance,
    claim_daily_reward,
    claim_redemption_closure,
    get_leveling_data,
    update_leveling_data,
    add_item_token,
    get_booster_discount_month,
    get_item_count,
    remove_item_token,
    purchase_item,
    get_setting,
    set_setting,
    claim_drop,
    ensure_drop_claims_ttl_index,
    get_leaderboard_page,
    get_leaderboard_total,
    get_user_rank,
    get_levels_page,
    get_levels_total,
    get_user_level_rank,
    increment_supply_drop_count,
    get_supply_drops_page,
    get_supply_drops_total,
    get_user_supply_drop_rank,
    add_redemption_queue_entry,
    get_redemption_queue,
    remove_redemption_queue_entry,
    claim_redemption_queue_entry,
    claim_redemption_queue_refund,
    apply_queue_refund,
    set_redemption_queue_entry_channel,
    get_stuck_redemption_queue_entries,
    begin_pending_redemption,
    set_pending_redemption_channel,
    clear_pending_redemption,
    get_all_pending_redemptions,
)

# --- CONFIGURATION ---
from features.config import (
    ADMIN_ROLE_ID,
    BOOSTER_CHANNEL_ID,
    BOTS_CATEGORY_ID,
    GENERAL_CHANNEL_ID,
    EVENT_ANNOUNCEMENTS_CHANNEL_ID,
    SHOP_DATA,
    MODERATOR_ROLE_ID,
    REDEMPTION_TICKET_CATEGORY_ID,
    REDEMPTION_TRANSCRIPT_CHANNEL_ID,
    SERVER_BOOSTER_ROLE_ID,
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
    "brawl pass": 9.0,
    "brawl pass+": 13.0,
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


async def get_effective_budget(
    guild: discord.Guild | None,
) -> tuple[float, float, float, float]:
    """Budget totals with pending tickets counted.

    Returns (total_budget, spent, pending_usd, available) where
    available = total_budget - spent - pending_usd.
    """
    total_budget, total_spent, _ = await get_budget_totals()
    pending_usd, _ = _pending_redemptions_total(guild)
    available = total_budget - total_spent - pending_usd
    return total_budget, total_spent, pending_usd, available


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


BOOSTER_DISCOUNT_RATE = 0.10
BOOSTER_DISCOUNT_MIN_BOOST_DAYS = 14


def _discounted_price(price: int) -> int:
    return int(price * (1 - BOOSTER_DISCOUNT_RATE))


def _booster_tenure_eligible(member) -> bool:
    """Booster role held and boosting for at least the minimum streak length.

    premium_since resets to None when a boost lapses, so the 14-day gate
    restarts on every new boost streak.
    """
    get_role = getattr(member, "get_role", None)
    if get_role is None or get_role(SERVER_BOOSTER_ROLE_ID) is None:
        return False
    premium_since = getattr(member, "premium_since", None)
    if premium_since is None:
        return False
    return datetime.now(timezone.utc) - premium_since >= timedelta(
        days=BOOSTER_DISCOUNT_MIN_BOOST_DAYS
    )


async def _booster_discount_available(member) -> bool:
    """Tenure-eligible booster who hasn't used the monthly discount yet."""
    if not _booster_tenure_eligible(member):
        return False
    used_month = await get_booster_discount_month(str(member.id))
    return used_month != _budget_month_key()


def _extract_topic_value(topic: str | None, key: str) -> str | None:
    if not topic:
        return None
    for part in topic.split("|"):
        k, _, v = part.partition(":")
        if k == key:
            return v
    return None


def _pending_redemptions_total(guild: discord.Guild | None) -> tuple[float, int]:
    """Sum the budget cost of open redemption tickets. Returns (total_usd, count)."""
    if guild is None:
        return 0.0, 0
    if (
        not isinstance(REDEMPTION_TICKET_CATEGORY_ID, int)
        or REDEMPTION_TICKET_CATEGORY_ID <= 0
    ):
        return 0.0, 0

    category = guild.get_channel(REDEMPTION_TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return 0.0, 0

    total = 0.0
    count = 0
    for channel in category.text_channels:
        if _extract_topic_value(channel.topic, "redemption-opener") is None:
            continue
        item = _extract_topic_value(channel.topic, "item") or ""
        budget_raw = _extract_topic_value(channel.topic, "budget_usd")
        try:
            cost = (
                float(budget_raw)
                if budget_raw is not None
                else _budget_cost_for_item(item)
            )
        except ValueError:
            cost = _budget_cost_for_item(item)
        if cost > 0:
            total += cost
            count += 1
    return total, count


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


def _redemption_instructions(item: str) -> str:
    if "brawl pass" in item:
        return "- Provide your in-game ID and a link to add you."
    if "nitro" in item:
        return "- Provide the Discord account you'd like the Nitro gifted to."
    if "paypal" in item:
        return "- Provide your PayPal email address."
    if "shoutout" in item:
        return "- Provide the message you want to be shouted out."
    return "- Provide necessary details."


async def _increment_redeem_counter(item: str) -> None:
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


async def create_redemption_ticket(
    guild: discord.Guild,
    member: discord.Member,
    item: str,
    budget_cost: float,
) -> discord.TextChannel:
    """Creates a redemption ticket channel with permissions, topic metadata,
    and the opening embed. Does not consume item tokens."""
    if (
        not isinstance(REDEMPTION_TICKET_CATEGORY_ID, int)
        or REDEMPTION_TICKET_CATEGORY_ID <= 0
    ):
        raise RuntimeError("Redemption category is not configured.")

    category = guild.get_channel(REDEMPTION_TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        raise RuntimeError("Configured redemption category channel was not found.")

    ch = await guild.create_text_channel(
        f"ticket-{member.name}",
        category=category,
    )
    await ch.set_permissions(guild.default_role, read_messages=False)
    await ch.set_permissions(member, read_messages=True, send_messages=True)

    for staff_role_id in (ADMIN_ROLE_ID, MODERATOR_ROLE_ID):
        staff_role = guild.get_role(staff_role_id)
        if staff_role:
            await ch.set_permissions(
                staff_role,
                read_messages=True,
                send_messages=True,
                manage_messages=True,
            )

    await ch.edit(
        topic=(
            f"redemption-opener:{member.id}|item:{item}|budget_usd:{budget_cost:.2f}"
        ),
        reason="Store redemption ticket metadata",
    )

    instructions = _redemption_instructions(item)
    item_price = _token_price_for_item(item)
    balance_after = await get_user_balance(str(member.id))
    balance_display_before = balance_after + item_price

    ticket_embed = discord.Embed(
        title=f"🎫 **{item.title()} Redemption Ticket**",
        description=f"{member.mention}, please provide the following details in this ticket channel:\n\n{instructions}",
        color=discord.Color.blue(),
    )
    ticket_embed.add_field(
        name="Item Price", value=f"{item_price:,} R7 tokens", inline=True
    )
    ticket_embed.add_field(
        name="Balance Before",
        value=f"{int(round(balance_display_before)):,} R7 tokens",
        inline=True,
    )
    ticket_embed.add_field(
        name="Balance After",
        value=f"{int(round(balance_after)):,} R7 tokens",
        inline=True,
    )
    await ch.send(content=member.mention, embed=ticket_embed)
    return ch


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


async def _build_redemption_transcript_text(
    channel: discord.TextChannel,
    item: str,
    token_cost: int,
    balance_before: int,
    balance_after: int,
) -> str:
    opener_raw = _extract_topic_value(channel.topic, "redemption-opener")
    lines: list[str] = [
        f"Channel: {channel.name}",
        f"Opener ID: {opener_raw or 'Unknown'}",
        f"Item: {item}",
        f"Token Cost: {token_cost}",
        f"Balance Before: {balance_before}",
        f"Balance After: {balance_after}",
        "",
    ]
    async for msg in channel.history(limit=None, oldest_first=True):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
        author = f"{msg.author} ({msg.author.id})"
        content = msg.content or ""
        if msg.attachments:
            attachment_list = ", ".join(a.url for a in msg.attachments)
            if content:
                content += " "
            content += f"[Attachments: {attachment_list}]"
        lines.append(f"[{ts}] {author}: {content}")
    if len(lines) <= 7:
        lines.append("No messages in this ticket.")
    return "\n".join(lines)


async def _save_redemption_transcript(
    channel: discord.TextChannel,
    actor: discord.Member,
    item: str,
    token_cost: int,
    balance_before: int,
    balance_after: int,
    outcome: str,
) -> None:
    transcript_text = await _build_redemption_transcript_text(
        channel, item, token_cost, balance_before, balance_after
    )
    transcript_bytes = transcript_text.encode("utf-8")
    filename = f"{channel.name}_transcript.txt"

    opener_raw = _extract_topic_value(channel.topic, "redemption-opener")
    opener_display = f"<@{opener_raw}>" if opener_raw else "unknown"
    item_display = SHOP_DATA.get(item, {}).get("display", item).replace("**", "")

    if outcome == "refunded":
        balance_original = balance_before + token_cost
        outcome_line = f"🔄 **Refunded** | **Balance:** {balance_original:,} → {balance_before:,} → {balance_after:,} R7 tokens"
    else:
        outcome_line = f"✅ **Fulfilled** | **Balance:** {balance_before:,} → {balance_after:,} R7 tokens"

    log_channel = (
        channel.guild.get_channel(REDEMPTION_TRANSCRIPT_CHANNEL_ID)
        if isinstance(REDEMPTION_TRANSCRIPT_CHANNEL_ID, int)
        else None
    )
    if isinstance(log_channel, discord.TextChannel):
        log_file = discord.File(io.BytesIO(transcript_bytes), filename=filename)
        await log_channel.send(
            content=(
                f"📝 Transcript for redemption ticket **#{channel.name}** "
                f"deleted by **{actor.name}** (opener: {opener_display}).\n"
                f"**Item:** {item_display} | **Cost:** {token_cost:,} R7 tokens\n"
                f"{outcome_line}"
            ),
            file=log_file,
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

        # Claim the closure BEFORE any money moves so a crash-then-reclick can't
        # refund twice. If the claim was already taken (a prior attempt paid the
        # refund but died before deleting), skip straight to deleting the channel.
        if await claim_redemption_closure(interaction.channel.id, "refund"):
            opener_raw = _extract_topic_value(
                interaction.channel.topic, "redemption-opener"
            )
            item = _extract_topic_value(interaction.channel.topic, "item") or ""
            token_cost = _token_price_for_item(item) if item else 0
            balance_before = 0
            balance_after = 0
            if opener_raw and opener_raw.isdigit() and item:
                refund_amount = _token_price_for_item(item)
                if refund_amount > 0:
                    balance_before = await get_user_balance(opener_raw)
                    balance_after = balance_before + refund_amount
                    await increment_user_balance(opener_raw, refund_amount)

            await _save_redemption_transcript(
                interaction.channel,
                interaction.user,
                item,
                token_cost,
                balance_before,
                balance_after,
                outcome="refunded",
            )

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

        # Claim the closure BEFORE deducting from budget so a crash-then-reclick can't
        # double-count the spend. If already claimed, skip straight to the delete.
        if await claim_redemption_closure(interaction.channel.id, "budget"):
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

            opener_raw = _extract_topic_value(
                interaction.channel.topic, "redemption-opener"
            )
            token_cost = _token_price_for_item(item) if item else 0
            current_balance = 0
            if opener_raw and opener_raw.isdigit():
                current_balance = await get_user_balance(opener_raw)

            await _save_redemption_transcript(
                interaction.channel,
                interaction.user,
                item,
                token_cost,
                current_balance + token_cost,
                current_balance,
                outcome="fulfilled",
            )
            await add_budget_spent(cost)

        await interaction.channel.delete(
            reason=f"Redemption fulfilled and deleted by {interaction.user}"
        )


class RedemptionQueueConfirmView(discord.ui.View):
    """Asks the user whether to queue an over-budget redemption for next month."""

    def __init__(self, user_id: str, item: str, budget_cost: float):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.item = item
        self.budget_cost = budget_cost

    @discord.ui.button(
        label="Join queue for next month", style=discord.ButtonStyle.success
    )
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This prompt is not for you.", ephemeral=True
            )
            return

        # Re-check ownership so a double /redeem can't queue the same item twice.
        if await get_item_count(self.user_id, self.item) < 1:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ **Queue Failed**",
                    description="You no longer own this item.",
                    color=discord.Color.red(),
                ),
                view=None,
            )
            return

        await remove_item_token(self.user_id, self.item)
        await add_redemption_queue_entry(self.user_id, self.item, self.budget_cost)
        position = len(await get_redemption_queue())

        item_display = SHOP_DATA.get(self.item, {}).get("display", self.item)
        embed = discord.Embed(
            title="📥 **Queued for Next Month**",
            description=(
                f"Your **{item_display}** redemption is queued at position "
                f"**#{position}**.\nA ticket will open automatically once the "
                "budget resets and can cover it. Use `/redemption-queue` to "
                "check your status."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This prompt is not for you.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🚫 **Redemption Cancelled**",
            description="You keep your item — nothing was queued.",
            color=discord.Color.greyple(),
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


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


def _rank_prefix(index: int) -> str:
    """🥇🥈🥉 for the podium, a bold number after it."""
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"**#{index}**")


def _format_token_line(index: int, user_doc: dict) -> str:
    # .get with a default, not [..]: a doc created by get_user_data has no
    # `balance` key at all and used to raise KeyError here.
    balance = user_doc.get("balance", 0)
    return f"{_rank_prefix(index)} <@{user_doc['_id']}> - 💰 **{int(balance)}**"


def _format_level_line(index: int, user_doc: dict) -> str:
    # Defaults match the ones get_leveling_data already applies.
    level = user_doc.get("level", 1)
    exp = user_doc.get("exp", 0)
    return (
        f"{_rank_prefix(index)} <@{user_doc['_id']}> - "
        f"Level **{level}** | **{exp}** EXP"
    )


def _format_supply_drop_line(index: int, user_doc: dict) -> str:
    # .get with defaults: docs that predate drop tracking (or have only one type)
    # are missing these keys and must render as zeroes rather than raise KeyError.
    normal = int(user_doc.get("supply_drops_normal", 0))
    booster = int(user_doc.get("supply_drops_booster", 0))
    total = normal + booster
    return (
        f"{_rank_prefix(index)} <@{user_doc['_id']}> - "
        f"📦 **{total}** total (🪂 {normal} Normal | 🚀 {booster} Booster)"
    )


def _leaderboard_footer(page: int, rank: int) -> str:
    return f"Page {page + 1} | Your Rank: #{rank}"


def _max_page(total: int, per_page: int) -> int:
    return max(0, (total - 1) // per_page)


class BaseLeaderboardView(discord.ui.View):
    """Shared pagination for the token and level boards.

    Both boards used to be separate copies of this logic and had quietly drifted
    apart -- different button labels, a `#` on one footer but not the other.
    Subclasses now supply only the data and the wording.
    """

    title = ""
    empty_text = "No entries to display."

    def __init__(self, author: discord.User):
        super().__init__(timeout=60)
        self.page = 0
        self.author = author
        self.per_page = 10

    async def fetch_page(self, offset: int, limit: int):
        raise NotImplementedError

    async def fetch_total(self) -> int:
        raise NotImplementedError

    async def fetch_viewer_rank(self) -> int:
        raise NotImplementedError

    @staticmethod
    def format_row(index: int, user_doc: dict) -> str:
        raise NotImplementedError

    async def generate_embed(self) -> discord.Embed:
        offset = self.page * self.per_page
        entries = await self.fetch_page(offset, self.per_page)

        embed = discord.Embed(title=self.title, color=discord.Color.gold())
        if entries:
            embed.description = "\n".join(
                self.format_row(index, user_doc)
                for index, user_doc in enumerate(entries, start=offset + 1)
            )
        else:
            embed.description = self.empty_text

        rank = await self.fetch_viewer_rank()
        embed.set_footer(text=_leaderboard_footer(self.page, rank))
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
        total = await self.fetch_total()
        if self.page < _max_page(total, self.per_page):
            self.page += 1
            embed = await self.generate_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()


class LeaderboardView(BaseLeaderboardView):
    title = "🏆 **R7 Token Leaderboard** 🏆"
    empty_text = "No entries to display."

    async def fetch_page(self, offset: int, limit: int):
        return await get_leaderboard_page(offset, limit)

    async def fetch_total(self) -> int:
        return await get_leaderboard_total()

    async def fetch_viewer_rank(self) -> int:
        # Pass the ID as a string; the collection is keyed by string _id.
        return await get_user_rank(str(self.author.id))

    @staticmethod
    def format_row(index: int, user_doc: dict) -> str:
        return _format_token_line(index, user_doc)


class LevelsLeaderboardView(BaseLeaderboardView):
    title = "🏆 **Server Level Leaderboard** 🏆"
    empty_text = "No leveled users yet!"

    async def fetch_page(self, offset: int, limit: int):
        return await get_levels_page(offset, limit)

    async def fetch_total(self) -> int:
        return await get_levels_total()

    async def fetch_viewer_rank(self) -> int:
        return await get_user_level_rank(str(self.author.id))

    @staticmethod
    def format_row(index: int, user_doc: dict) -> str:
        return _format_level_line(index, user_doc)


class SupplyDropsLeaderboardView(BaseLeaderboardView):
    title = "🏆 **Supply Drop Leaderboard** 🏆"
    empty_text = "No supply drops claimed yet!"

    async def fetch_page(self, offset: int, limit: int):
        return await get_supply_drops_page(offset, limit)

    async def fetch_total(self) -> int:
        return await get_supply_drops_total()

    async def fetch_viewer_rank(self) -> int:
        return await get_user_supply_drop_rank(str(self.author.id))

    @staticmethod
    def format_row(index: int, user_doc: dict) -> str:
        return _format_supply_drop_line(index, user_doc)


class ShopPaginationView(discord.ui.View):
    def __init__(
        self, data: dict, items_per_page: int = 4, booster_discount: bool = False
    ):
        super().__init__(timeout=60)
        self.data = list(data.items())
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.data) - 1) // items_per_page + 1
        self.booster_discount = booster_discount

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
            price = info["price"]
            if self.booster_discount and _discounted_price(price) < price:
                price_line = (
                    f"**Price:** ~~{price}~~ **{_discounted_price(price)}** "
                    "R7 tokens (10% booster discount)"
                )
            else:
                price_line = f"**Price:** {price} R7 tokens"
            embed.add_field(
                name=info["display"],
                value=f"{info['desc']}\n{price_line}",
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


class DropClaimButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"drop_claim:(?P<amount>\d+)",
):
    """Persistent claim button for supply/booster/admin drops.

    The token amount rides in the custom_id (`drop_claim:{amount}`) so the button
    survives a restart: registered once via `bot.add_dynamic_items(DropClaimButton)`
    in Economy.cog_load, discord.py rebuilds it from the custom_id for interactions
    on drop messages sent before the restart — which the old plain View (no custom_id,
    never re-registered) could not do, leaving outstanding drops permanently dead.
    """

    def __init__(self, amount: int):
        self.amount = amount
        super().__init__(
            discord.ui.Button(
                label="Claim Supply Drop",
                style=discord.ButtonStyle.green,
                emoji="🎁",
                custom_id=f"drop_claim:{amount}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["amount"]))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if any(role.id == MODERATOR_ROLE_ID for role in interaction.user.roles):
            await interaction.followup.send(
                "❌ Staff cannot claim supply drops!", ephemeral=False
            )
            return

        # Atomic, restart-safe single-claim guard (replaces the in-memory `claimed`
        # flag, which reset on restart and raced across the defer() above).
        message = interaction.message
        if not await claim_drop(str(message.id), str(interaction.user.id)):
            await interaction.followup.send("❌ Already claimed!", ephemeral=True)
            return

        # 1. Pay atomically ($inc) — no read-modify-write.
        await increment_user_balance(str(interaction.user.id), self.amount)

        # 1b. Track the claim for the supply-drop leaderboard. Drops in the
        #     booster channel count as booster drops; everything else (general
        #     random and admin drops) counts as a normal drop.
        is_booster = message.channel.id == BOOSTER_CHANNEL_ID
        await increment_supply_drop_count(
            str(interaction.user.id), is_booster=is_booster
        )

        # 2. Clear the booster-drop marker if this was the live booster drop. The
        #    persistent button has no on_claim closure, so do it here directly.
        if message.channel.id == BOOSTER_CHANNEL_ID:
            if await get_setting("booster_drop_message_id") == str(message.id):
                await set_setting("booster_drop_message_id", "")

        # 3. Update the button to "Claimed" and edit the message.
        self.item.disabled = True
        self.item.label = f"Claimed by {interaction.user.display_name}"
        self.item.style = discord.ButtonStyle.secondary
        view = discord.ui.View(timeout=None)
        view.add_item(self)

        embed = message.embeds[0]
        embed.color = discord.Color.light_grey()
        embed.description = (
            f"**📦 CLAIMED!**\n\n**{interaction.user.mention}** grabbed "
            f"**{self.amount} Tokens**!"
        )
        await interaction.edit_original_response(embed=embed, view=view)
        await interaction.followup.send(
            f"🎉 **+{self.amount} Tokens** added to your account!", ephemeral=True
        )


def build_drop_view(amount: int) -> discord.ui.View:
    """A persistent (timeout=None) view carrying one DropClaimButton."""
    view = discord.ui.View(timeout=None)
    view.add_item(DropClaimButton(amount))
    return view


# --- COG ---


class Economy(commands.Cog):
    # Must be a class attribute: CogMeta collects class-level groups, and Cog.__new__
    # deep-copies this one per instance so `self` binds to the cog inside subcommands.
    leaderboard_group = app_commands.Group(
        name="leaderboard", description="View the server's leaderboards."
    )

    def __init__(self, bot):
        self.bot = bot
        self.supply_drop_task.start()
        self.booster_drop_task.start()
        self.redemption_queue_task.start()
        self.pending_redemption_reconcile_task.start()
        self.booster_drop_reconcile_task.start()

    async def cog_load(self):
        self.bot.add_view(RedemptionClosedOptionsView())
        # Persistent drop-claim button: re-registered so outstanding supply/booster/
        # admin drops stay claimable after a restart (the amount rides in the
        # custom_id). Without this every pre-restart drop button is inert.
        self.bot.add_dynamic_items(DropClaimButton)
        try:
            await ensure_drop_claims_ttl_index()
        except Exception as e:
            print(f"⚠️ Economy: could not create drop_claims TTL index: {e}")

    def cog_unload(self):
        self.supply_drop_task.cancel()
        self.booster_drop_task.cancel()
        self.redemption_queue_task.cancel()
        self.pending_redemption_reconcile_task.cancel()
        self.booster_drop_reconcile_task.cancel()

    # --- BOOSTER DROP MARKER RECONCILE (crash recovery) ---
    @tasks.loop(count=1)
    async def booster_drop_reconcile_task(self):
        """Cold-boot-only. If a crash left a booster_drop_message_id marker set,
        resolve it immediately instead of waiting up to ~4h for the next drop to
        expire it lazily. _expire_previous_booster_drop edits the stale drop to
        EXPIRED (or clears the marker if the message is gone)."""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(BOOSTER_CHANNEL_ID)
        if not channel:
            return
        try:
            await self._expire_previous_booster_drop(channel)
        except Exception as e:
            print(f"❌ Booster drop marker reconcile failed: {e}")

    # --- REDEMPTION QUEUE PROCESSING ---
    @tasks.loop(hours=1)
    async def redemption_queue_task(self):
        await self.bot.wait_until_ready()

        current_key = _budget_month_key()
        processed_key = await get_setting("redemption_queue_processed_month")
        if processed_key == current_key:
            return

        try:
            await self.process_redemption_queue()
        except Exception as e:
            # Leave the month unstamped so the next hourly tick retries.
            print(f"❌ Redemption queue processing failed: {e}")
            return

        await set_setting("redemption_queue_processed_month", current_key)

    # --- PENDING REDEMPTION RECONCILE (crash recovery) ---
    @tasks.loop(count=1)
    async def pending_redemption_reconcile_task(self):
        """Runs once per process, after the bot is ready. A cog is loaded once
        and not re-added on gateway reconnect, so this is cold-boot-only — there
        are no in-flight redemptions to race, hence no stale-age gate is needed."""
        await self.bot.wait_until_ready()
        # Independent try/except so a failure in one reconcile can't skip the
        # other on a given boot.
        try:
            await self.reconcile_pending_redemptions()
        except Exception as e:
            print(f"❌ Pending redemption reconcile failed: {e}")
        try:
            await self.reconcile_redemption_queue()
        except Exception as e:
            print(f"❌ Redemption queue reconcile failed: {e}")

    async def reconcile_pending_redemptions(self):
        """Resolve pending-redemption markers left over from a crash.

        Decidable per marker so it never both keeps a ticket and refunds
        (double value), nor does neither (silent loss):
        - has channel_id  -> the ticket was created -> clear, no refund.
        - no channel_id   -> scan the redemption category by topic; if a matching
          ticket exists (crash landed in the create->persist window) adopt it with
          no refund, otherwise refund the item and clear.
        """
        pending = await get_all_pending_redemptions()
        if not pending:
            return

        category = self.bot.get_channel(REDEMPTION_TICKET_CATEGORY_ID)
        open_tickets = (
            list(category.text_channels)
            if isinstance(category, discord.CategoryChannel)
            else None
        )

        for row in pending:
            user_id = row["user_id"]
            pending_id = row["id"]
            item = row["item"]

            # Ticket was created (channel_id persisted) -> item already delivered
            # to a ticket. Never refund, whether or not the channel still exists.
            if row.get("channel_id") is not None:
                await clear_pending_redemption(user_id, pending_id)
                continue

            # No channel_id: the ticket may still have been created just before
            # the crash. Can't verify without the category -> leave the marker for
            # a later reconcile rather than risk a double refund.
            if open_tickets is None:
                print(
                    "⚠️ Redemption reconcile: category unavailable, deferring "
                    f"pending redemption {pending_id} for {user_id}."
                )
                continue

            ticket_exists = any(
                _extract_topic_value(ch.topic, "redemption-opener") == str(user_id)
                and _extract_topic_value(ch.topic, "item") == item
                for ch in open_tickets
            )

            if ticket_exists:
                # Crash in the create->persist window; ticket is real, no refund.
                await clear_pending_redemption(user_id, pending_id)
            else:
                # Crash before/at ticket creation; the token was consumed with no
                # ticket ever made -> refund it.
                await add_item_token(user_id, item, quantity=1)
                await clear_pending_redemption(user_id, pending_id)
                print(
                    f"↩️ Redemption reconcile: refunded {item} to {user_id} "
                    "(no ticket found for crashed redemption)."
                )

    async def reconcile_redemption_queue(self):
        """Resolve redemption-queue entries claimed but never removed — a crash
        between the claim and the removal in process_redemption_queue (ticket
        creation) or in a refund path (staff remove / member-left drop).

        Decidable per entry so it never both keeps a ticket and refunds (double
        value), nor does neither (silent loss):
        - has refund_kind -> a claimed refund -> pay it idempotently (token or
          item, per kind) and drop the entry; replaying a completed refund is a
          no-op via the per-entry receipt in apply_queue_refund.
        - has channel_id  -> the ticket was created -> drop the entry, no refund.
        - no channel_id   -> scan the redemption category by topic; if a matching
          ticket exists (crash landed in the create->persist window) drop it with
          no refund, otherwise return the item and drop the entry.
        """
        entries = await get_stuck_redemption_queue_entries()
        if not entries:
            return

        category = self.bot.get_channel(REDEMPTION_TICKET_CATEGORY_ID)
        open_tickets = (
            list(category.text_channels)
            if isinstance(category, discord.CategoryChannel)
            else None
        )

        for entry in entries:
            entry_id = str(entry["_id"])
            user_id = entry["user_id"]
            item = entry["item"]

            # Refund claim (staff /redemption-queue-remove or a member-left drop
            # that crashed before paying). Must be handled BEFORE the channel_id /
            # topic-scan ticket logic below: a refund entry has no channel_id and
            # no ticket, so that logic would wrongly return an item — even for a
            # token refund — and without the idempotency receipt. apply_queue_refund
            # is idempotent per entry, so replaying a completed refund is a no-op.
            refund_kind = entry.get("refund_kind")
            if refund_kind is not None:
                if refund_kind == "tokens":
                    refund = _token_price_for_item(item)
                    await apply_queue_refund(user_id, entry_id, tokens=refund)
                    note = f"{refund:,} R7 tokens refunded"
                else:  # "item"
                    await apply_queue_refund(user_id, entry_id, item=item)
                    note = "the item was returned to their inventory"
                await remove_redemption_queue_entry(entry_id)
                transcript_channel = self.bot.get_channel(
                    REDEMPTION_TRANSCRIPT_CHANNEL_ID
                )
                if transcript_channel:
                    await transcript_channel.send(
                        f"↩️ Queued **{item}** redemption refund for <@{user_id}> "
                        f"was completed after a restart — {note}."
                    )
                continue

            # Channel recorded -> the ticket was created. Never refund, whether or
            # not the channel still exists.
            if entry.get("channel_id") is not None:
                await remove_redemption_queue_entry(entry_id)
                continue

            # No channel_id: the ticket may still have been created just before
            # the crash. Can't verify without the category -> leave the entry for
            # a later reconcile rather than risk a double (ticket + refund).
            if open_tickets is None:
                print(
                    "⚠️ Redemption queue reconcile: category unavailable, "
                    f"deferring entry {entry_id} for {user_id}."
                )
                continue

            ticket_exists = any(
                _extract_topic_value(ch.topic, "redemption-opener") == str(user_id)
                and _extract_topic_value(ch.topic, "item") == item
                for ch in open_tickets
            )

            if ticket_exists:
                # Crash in the create->persist window; ticket is real, no refund.
                await remove_redemption_queue_entry(entry_id)
            else:
                # Crash before/at ticket creation; the queued item was consumed
                # with no ticket ever made -> return it to the member's inventory.
                await add_item_token(user_id, item, quantity=1)
                await remove_redemption_queue_entry(entry_id)
                transcript_channel = self.bot.get_channel(
                    REDEMPTION_TRANSCRIPT_CHANNEL_ID
                )
                if transcript_channel:
                    await transcript_channel.send(
                        f"↩️ Queued **{item}** redemption for <@{user_id}> could not "
                        "be completed (bot restarted before the ticket opened) — the "
                        "item was returned to their inventory."
                    )

    async def process_redemption_queue(self):
        """Fulfills queued redemptions FIFO against the new month's budget.

        Entries that don't fit the available budget stay queued and carry
        over to the next month.
        """
        category = self.bot.get_channel(REDEMPTION_TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError("Redemption category channel was not found.")
        guild = category.guild

        for entry in await get_redemption_queue():
            item = entry["item"]
            user_id = entry["user_id"]
            cost = _budget_cost_for_item(item)

            # A claimed entry is a crash leftover (ticket may already exist) — it
            # belongs to the cold-boot reconcile, never reprocess it here.
            if entry.get("claimed_at") is not None:
                continue

            member = guild.get_member(int(user_id))
            if member is None:
                # A cache miss (e.g. right after a restart) does NOT mean the
                # user left. Confirm against the API before dropping/refunding.
                try:
                    member = await guild.fetch_member(int(user_id))
                except discord.NotFound:
                    member = None  # Genuinely left — fall through to refund.
                except discord.HTTPException as e:
                    # Transient error — leave the entry queued, retry next cycle.
                    print(
                        f"⚠️ Redemption queue: fetch_member failed for "
                        f"{user_id}, retrying next cycle: {e}"
                    )
                    continue

            if member is None:
                # Opener left the server — refund tokens and drop the entry.
                # Claim first so a crash between the entry removal and the refund
                # can't lose the tokens: the claimed entry is skipped by the loop
                # above and resolved (idempotently) by the cold-boot reconcile. A
                # lost claim means a racing staff-remove or reconcile owns it.
                eid = str(entry["_id"])
                if await claim_redemption_queue_refund(eid, "tokens") is None:
                    continue
                refund = _token_price_for_item(item)
                await apply_queue_refund(user_id, eid, tokens=refund)
                await remove_redemption_queue_entry(eid)
                transcript_channel = self.bot.get_channel(
                    REDEMPTION_TRANSCRIPT_CHANNEL_ID
                )
                if transcript_channel:
                    await transcript_channel.send(
                        f"📤 Queued **{item}** redemption for <@{user_id}> dropped "
                        f"(user left the server) — {refund:,} R7 tokens refunded."
                    )
                continue

            # Recompute each iteration: tickets created earlier in this run
            # count as pending and reduce what's available.
            _, _, _, available = await get_effective_budget(guild)
            if cost > available:
                continue

            # Claim before creating so a crash between the ticket creation and
            # the entry removal can't double-create on the next run: the claimed
            # entry is skipped above and resolved by the cold-boot reconcile.
            if not await claim_redemption_queue_entry(str(entry["_id"])):
                continue

            try:
                ch = await create_redemption_ticket(guild, member, item, cost)
                await _increment_redeem_counter(item)
                # Record the channel so a crash after this point is decidable on
                # reconcile (channel present → ticket exists → no refund).
                await set_redemption_queue_entry_channel(str(entry["_id"]), ch.id)
            except Exception as e:
                print(f"❌ Failed to open queued redemption for {user_id}: {e}")
                continue  # leave it claimed; cold-boot reconcile resolves it

            await remove_redemption_queue_entry(str(entry["_id"]))

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

        booster_xp_bonus = 0

        if message.channel.id in (GENERAL_CHANNEL_ID, BOOSTER_CHANNEL_ID):
            is_booster = False
            if message.guild:
                booster_role = message.guild.get_role(SERVER_BOOSTER_ROLE_ID)
                is_booster = (
                    booster_role is not None and booster_role in message.author.roles
                )

            # Booster Bonus: 35% Chance of +1 XP per general-channel message
            if is_booster and random.random() < 0.35:
                booster_xp_bonus = 1

            # --- TRACK DAILY MESSAGE COUNT (tied to /daily cooldown window) ---
            # Format: "LAST_DAILY_TIMESTAMP:COUNT" — resets when user claims /daily.
            # The window key is the /daily cooldown, which lives on the user doc
            # (daily_last_claimed). The count itself stays in settings on purpose.
            user_doc = await get_user_data(user_id)
            last_daily_ts = user_doc.get("daily_last_claimed")
            window_key = str(last_daily_ts) if last_daily_ts else "0"

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

                # Booster Bonus: 35% Chance (Avg 10% increase)
                if is_booster and random.random() < 0.35:
                    earned_tokens += 1

                # Stamp the cooldown BEFORE granting so a crash between the two
                # writes loses a tiny 2-6 token reward rather than re-awarding on
                # the next message. (Balance lives on the user doc and the cooldown
                # in settings, so they can't be one atomic write — stamp-first is the
                # crash-safe ordering.) Grant via atomic $inc, no read-modify-write.
                # NOTE: this deliberately reverses #412's paid-first choice; there the
                # reward was large enough to prioritize never-lose over never-double.
                await set_setting(f"last_message_{user_id}", str(current_timestamp))
                await increment_user_balance(user_id, earned_tokens)

            # --- PART 2: XP & LEVELING ---
            EXP_PER_MESSAGE = 10
            BASE_EXP = 100

            level, exp = await get_leveling_data(user_id)
            exp += EXP_PER_MESSAGE + booster_xp_bonus

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
        await channel.send(embed=embed, view=build_drop_view(amount))
        print(f"🪂 Auto-Drop sent: {amount} tokens")

    # --- BOOSTER CHANNEL DROP TASK ---
    # Gap between drops = sleep + ~1s → uniform 0-4h, avg ~2h, hard 4h pity cap.
    @tasks.loop(seconds=1)
    async def booster_drop_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(random.randint(0, 14400))
        try:
            await self._post_booster_drop()
        except Exception as e:
            print(f"❌ Booster drop failed: {e}")

    async def _post_booster_drop(self):
        channel = self.bot.get_channel(BOOSTER_CHANNEL_ID)
        if not channel:
            return

        if not await self._expire_previous_booster_drop(channel):
            return

        amount = random.randint(10, 25)
        embed = discord.Embed(
            title="🚀 Booster Supply Drop!",
            description=f"A booster-exclusive crate with **{amount} R7 Tokens** has landed!\n\n**Click FAST to claim it!**",
            color=discord.Color.fuchsia(),
        )

        # The claim button clears booster_drop_message_id itself (see
        # DropClaimButton.callback) — no on_claim closure needed, which is what
        # lets the button survive a restart as a persistent dynamic item.
        msg = await channel.send(embed=embed, view=build_drop_view(amount))
        await set_setting("booster_drop_message_id", str(msg.id))
        print(f"🚀 Booster drop sent: {amount} tokens")

    async def _expire_previous_booster_drop(self, channel) -> bool:
        """Returns True if it's safe to post a new drop (nothing left un-expired)."""
        prev_id = await get_setting("booster_drop_message_id")
        if not prev_id:
            return True

        try:
            msg = await channel.fetch_message(int(prev_id))
        except (discord.NotFound, ValueError):
            await set_setting("booster_drop_message_id", "")
            return True
        except discord.HTTPException as e:
            print(f"⚠️ Booster drop expiry fetch failed, retrying next cycle: {e}")
            return False

        # Skip drops the claim button already edited to CLAIMED.
        if msg.embeds and "CLAIMED" not in (msg.embeds[0].description or ""):
            embed = msg.embeds[0]
            embed.color = discord.Color.dark_grey()
            embed.description = "**⌛ EXPIRED!**\n\nNobody claimed this drop in time. Keep an eye out — another one is inbound!"
            try:
                await msg.edit(embed=embed, view=None)
            except discord.HTTPException as e:
                print(f"⚠️ Booster drop expiry edit failed, retrying next cycle: {e}")
                return False

        await set_setting("booster_drop_message_id", "")
        return True

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
        view = build_drop_view(amount)
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
        discount_eligible = await _booster_discount_available(interaction.user)
        # Create the view with 4 items per page
        view = ShopPaginationView(
            SHOP_DATA, items_per_page=4, booster_discount=discount_eligible
        )
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
        original_price = price

        # Don't burn the monthly discount on items where 10% saves nothing.
        discount_applied = _discounted_price(
            price
        ) < price and await _booster_discount_available(interaction.user)
        if discount_applied:
            price = _discounted_price(price)

        balance = await get_user_balance(user_id)

        if balance < price:
            embed = discord.Embed(
                title="❌ **Insufficient Balance**",
                description=f"You need **{int(price - balance)} more R7 tokens** to purchase **{item_info['display']}**.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Deduct tokens, grant the item, and (for boosters) stamp the monthly
        # discount in a single atomic document update. Both effects live on the
        # one users doc, so a crash can never leave the tokens gone without the
        # item. The `balance >= price` guard also blocks a concurrent balance
        # write (e.g. a drop claim) from letting the purchase go through twice or
        # drive the balance negative.
        discount_month = _budget_month_key() if discount_applied else None
        purchased = await purchase_item(user_id, item, price, discount_month)
        if not purchased:
            # Lost a race: the balance dropped below the price between the check
            # and the commit. No tokens were spent and no item was granted.
            fresh = await get_user_balance(user_id)
            embed = discord.Embed(
                title="❌ **Insufficient Balance**",
                description=f"You need **{int(price - fresh)} more R7 tokens** to purchase **{item_info['display']}**.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        new_balance = await get_user_balance(user_id)

        description = (
            f"You have purchased **{item_info['display']}**!\n"
            "Please use `/redeem` to claim it."
        )
        if discount_applied:
            description += (
                f"\n🚀 **Booster Discount:** ~~{original_price}~~ **{price}** "
                "R7 tokens — 10% off applied (1/month)"
            )

        embed = discord.Embed(
            title="✅ **Purchase Successful**",
            description=description,
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

        # Budget guard: block redemption when the effective budget (monthly
        # budget minus spent and pending tickets) cannot cover this item.
        budget_cost = _budget_cost_for_item(item)
        if budget_cost > 0:
            _, spent, pending_usd, available = await get_effective_budget(
                interaction.guild
            )
            if budget_cost > available:
                embed = discord.Embed(
                    title="⏳ **Budget Limit Reached**",
                    description=(
                        f"This redemption requires **${budget_cost:.2f}**, but only "
                        f"**${max(available, 0.0):.2f}** is available in the monthly "
                        f"budget (${spent:.2f} spent, ${pending_usd:.2f} reserved by "
                        "open tickets).\n\n"
                        "You can join the queue for next month instead: your "
                        f"**{item_info['display']}** will be consumed now, and a "
                        "ticket will open automatically once the budget resets and "
                        "can cover it."
                    ),
                    color=discord.Color.orange(),
                )
                await interaction.response.send_message(
                    embed=embed,
                    view=RedemptionQueueConfirmView(user_id, item, budget_cost),
                    ephemeral=True,
                )
                return

        await interaction.response.defer()

        pending_id = None
        ticket_created = False
        try:
            # Re-check after defer in case a concurrent redemption claimed
            # the remaining budget.
            if budget_cost > 0:
                _, _, _, available = await get_effective_budget(interaction.guild)
                if budget_cost > available:
                    await interaction.followup.send(
                        "❌ The remaining budget was claimed by another redemption "
                        "just now. Please run `/redeem` again.",
                        ephemeral=True,
                    )
                    return

            # Consume the token and write a durable pending marker in one atomic
            # op, so a hard crash before the ticket exists is recoverable on
            # startup (reconcile_pending_redemptions). None => the item was
            # claimed by a concurrent redemption; abort without side effects.
            pending_id = await begin_pending_redemption(user_id, item, budget_cost)
            if pending_id is None:
                await interaction.followup.send(
                    "❌ That item is no longer available on your account. "
                    "Please run `/redeem` again.",
                    ephemeral=True,
                )
                return

            ch = await create_redemption_ticket(
                interaction.guild, interaction.user, item, budget_cost
            )
            ticket_created = True

            # Record the ticket so a crash after this point is decidable on
            # reconcile (ticket exists → no refund), then finish bookkeeping.
            await set_pending_redemption_channel(user_id, pending_id, ch.id)
            await _increment_redeem_counter(item)
            await clear_pending_redemption(user_id, pending_id)

            instructions = _redemption_instructions(item)
            embed = discord.Embed(
                title="✅ **Redemption Successful**",
                description=f"A ticket has been created in {ch.mention}.\nPlease provide the following details to redeem your **{item_info['display']}**:\n{instructions}",
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            # In-process failure: self-heal now. (A hard crash skips this handler;
            # the startup reconcile covers that case.) Refund only when no ticket
            # was created — if one was, the token was delivered, so just drop the
            # marker to avoid a double (ticket + refund).
            if pending_id is not None:
                if not ticket_created:
                    await add_item_token(user_id, item, quantity=1)
                await clear_pending_redemption(user_id, pending_id)
            await interaction.followup.send(
                f"❌ **Error** Failed to create ticket: {e}", ephemeral=True
            )

    @app_commands.command(name="daily", description="Claim your daily R7 tokens!")
    async def daily(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        now = datetime.utcnow()

        # 1. FETCH DATA
        # The cooldown lives on the user doc (daily_last_claimed) so the grant + stamp
        # can be one atomic write (see claim_daily_reward). The daily message counter
        # deliberately stays in settings (daily_msg_count_{uid}) — it isn't part of the
        # atomic claim, so it's fine to keep it where it is.
        user_doc = await get_user_data(user_id)
        last_daily_ts = user_doc.get("daily_last_claimed")
        window_key = str(last_daily_ts) if last_daily_ts else "0"

        daily_msg_data = await get_setting(
            f"daily_msg_count_{user_id}", f"{window_key}:0"
        )
        stored_window_key, count = daily_msg_data.split(":", 1)
        msg_count = int(count) if stored_window_key == window_key else 0

        cooldown_remaining = None
        if last_daily_ts:
            last_daily = datetime.utcfromtimestamp(float(last_daily_ts))
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

        # Booster Bonus: flat +20 tokens on every claim
        booster_bonus = 0
        if interaction.guild:
            booster_role = interaction.guild.get_role(SERVER_BOOSTER_ROLE_ID)
            if booster_role and booster_role in interaction.user.roles:
                booster_bonus = 20
        final_tokens += booster_bonus

        # Atomically stamp the cooldown AND grant the tokens in one write, so a crash
        # can't land between "tokens granted" and "cooldown stamped" and let the user
        # claim twice. If the claim loses the cooldown predicate (a concurrent or
        # duplicate invoke slipped past the check above), treat it as on cooldown
        # instead of granting again.
        now_ts = now.timestamp()
        cutoff_ts = (now - timedelta(days=1)).timestamp()
        updated = await claim_daily_reward(user_id, final_tokens, cutoff_ts, now_ts)
        if updated is None:
            embed = discord.Embed(
                title="🔒 Daily Reward Status",
                description="You've already claimed your daily reward. Try again later!",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        new_balance = updated.get("balance", 0)

        description = (
            f"You received **{final_tokens} R7 tokens**!\n"
            f"New balance: **{int(new_balance)}** | Level: **{level}**"
        )
        if booster_bonus:
            description += f"\n🚀 **Booster Bonus:** +{booster_bonus} tokens included!"

        embed = discord.Embed(
            title="🎉 Daily Reward Claimed!",
            description=description,
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

    @leaderboard_group.command(
        name="token", description="View the server's R7 token leaderboard."
    )
    async def leaderboard_token(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = LeaderboardView(interaction.user)
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @leaderboard_group.command(
        name="level", description="View the server's level leaderboard."
    )
    async def leaderboard_level(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = LevelsLeaderboardView(interaction.user)
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @leaderboard_group.command(
        name="supply-drops",
        description="View the server's supply drop leaderboard.",
    )
    async def leaderboard_supply_drops(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = SupplyDropsLeaderboardView(interaction.user)
        embed = await view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="check-budget", description="Check the remaining budget for redemptions."
    )
    async def check_budget(self, interaction: discord.Interaction):
        total_budget, total_spent, pending_usd, available = await get_effective_budget(
            interaction.guild
        )
        _, pending_count = _pending_redemptions_total(interaction.guild)
        queue = await get_redemption_queue()
        queued_usd = sum(_budget_cost_for_item(entry["item"]) for entry in queue)

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
            f"**Pending Tickets:** ${pending_usd:.2f} ({pending_count} open)\n"
            f"**Available Budget:** ${available:.2f}\n"
            f"**Queued for Next Month:** {len(queue)} "
            f"redemption(s) (${queued_usd:.2f} est.)\n"
            f"**Budget Resets:** <t:{reset_timestamp}:R> (<t:{reset_timestamp}:F>)"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="redemption-queue",
        description="See your queued redemptions for next month.",
    )
    async def redemption_queue_status(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        queue = await get_redemption_queue()
        lines = []
        for position, entry in enumerate(queue, start=1):
            if entry["user_id"] != user_id:
                continue
            item_display = SHOP_DATA.get(entry["item"], {}).get(
                "display", entry["item"]
            )
            cost = _budget_cost_for_item(entry["item"])
            queued_ts = int(entry["queued_at"].replace(tzinfo=timezone.utc).timestamp())
            lines.append(
                f"**#{position}** — {item_display} (${cost:.2f}) — "
                f"queued <t:{queued_ts}:R>"
            )

        embed = discord.Embed(
            title="📥 **Your Redemption Queue**",
            description="\n".join(lines)
            if lines
            else "You have nothing queued. Over-budget redemptions can be "
            "queued from `/redeem`.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="redemption-queue-list",
        description="STAFF: List all queued redemptions.",
    )
    async def redemption_queue_list(self, interaction: discord.Interaction):
        if not _is_redemption_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Permission Denied", ephemeral=True
            )
            return

        queue = await get_redemption_queue()
        lines = []
        total_usd = 0.0
        for position, entry in enumerate(queue, start=1):
            cost = _budget_cost_for_item(entry["item"])
            total_usd += cost
            queued_ts = int(entry["queued_at"].replace(tzinfo=timezone.utc).timestamp())
            lines.append(
                f"**{position}.** <@{entry['user_id']}> — {entry['item']} "
                f"(${cost:.2f}) — queued <t:{queued_ts}:R> — id: `{entry['_id']}`"
            )

        embed = discord.Embed(
            title="📥 **Redemption Queue**",
            description="\n".join(lines) if lines else "The queue is empty.",
            color=discord.Color.blue(),
        )
        embed.set_footer(
            text=f"{len(queue)} entries | ${total_usd:.2f} estimated total"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="redemption-queue-remove",
        description="STAFF: Remove a queue entry and give the item back.",
    )
    @app_commands.describe(entry_id="The entry id shown in /redemption-queue-list")
    async def redemption_queue_remove(
        self, interaction: discord.Interaction, entry_id: str
    ):
        if not _is_redemption_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Permission Denied", ephemeral=True
            )
            return

        # Claim before paying so a crash between the entry removal and the item
        # grant can't lose the item: the claimed entry is resolved by the
        # cold-boot reconcile, and apply_queue_refund is idempotent per entry.
        doc = await claim_redemption_queue_refund(entry_id, "item")
        if doc is None:
            await interaction.response.send_message(
                "❌ Queue entry not found, or it's already being processed.",
                ephemeral=True,
            )
            return

        await apply_queue_refund(doc["user_id"], entry_id, item=doc["item"])
        await remove_redemption_queue_entry(entry_id)
        embed = discord.Embed(
            title="✅ **Queue Entry Removed**",
            description=(
                f"Removed the **{doc['item']}** redemption queued by "
                f"<@{doc['user_id']}> — their item was returned to their inventory."
            ),
            color=discord.Color.green(),
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
            "🚀 **Booster Bonus:** Server Boosters receive a **10% increase** in coins on average, "
            "bonus XP in general chat, and **+20 tokens** on every `/daily` claim."
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
            "🎟️ **Redeeming:** Use `/redeem <item>` to open a ticket and claim your reward from staff.\n"
            "🚀 **Booster Discount:** Boosters of **14+ days** automatically get "
            "**10% off** one purchase per month."
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
            "`/leaderboard token` - See top token holders\n"
            "`/level` - Check your rank & XP progress\n"
            "`/leaderboard level` - See top server levels\n"
            "`/leaderboard supply-drops` - See top supply drop claimers\n"
            "`/shop` - Browse the token store\n"
            "`/buy` - Purchase an item from the shop\n"
            "`/redeem` - Claim your purchased rewards\n\n"
            "**Utility:**\n"
            "`/check-budget` - See remaining monthly reward budget\n"
            "`/redemption-queue` - View your queued redemptions"
        )
        cmd_embed.description = cmd_text

        # Sending all three embeds in a single interaction response
        await interaction.response.send_message(
            embeds=[earn_embed, spend_embed, cmd_embed]
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
