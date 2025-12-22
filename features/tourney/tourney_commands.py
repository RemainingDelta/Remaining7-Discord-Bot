import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re 

from database.mongo import (
    add_payout_batch,         
    get_payout_logs,         
    get_user_unpaid_batches, 
    get_all_pending_payouts, 
    clear_pending_payout
)

# Import Config and Utils
from features.config import (
    ALLOWED_STAFF_ROLES,
    OTHER_TICKET_CHANNEL_ID,
    MEMBER_ROLE_ID,
    TOURNEY_SUPPORT_CHANNEL_ID,
    PRE_TOURNEY_SUPPORT_CHANNEL_ID,
    TOURNEY_CATEGORY_ID,
    PRE_TOURNEY_CATEGORY_ID,
    TOURNEY_CLOSED_CATEGORY_ID,
    PRE_TOURNEY_CLOSED_CATEGORY_ID,
    HALL_OF_FAME_CHANNEL_ID
)
from .tourney_utils import (
    close_ticket_via_command,
    reset_ticket_counter,
    delete_ticket_with_transcript,
    delete_ticket_via_command,
    reopen_ticket_via_command
)
from .tourney_views import TourneyOpenTicketView, PreTourneyOpenTicketView

# Global lock tasks dictionary to track auto-reopen timers
lock_tasks: dict[int, asyncio.Task] = {}
LOCK_DURATION_HOURS = 6

def is_staff(member: discord.Member) -> bool:
    """Return True if the member has any of the allowed staff roles."""
    return any(role.id in ALLOWED_STAFF_ROLES for role in member.roles)

class PayoutResetConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.value = None

    @discord.ui.button(label="Confirm Reset All", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()

def setup_tourney_commands(bot: commands.Bot):
    print("Setting up tourney commands...")

    # =========================================================================
    #  PREFIX COMMANDS (Exact Replica from Old Main)
    # =========================================================================

    @bot.command(name="close", aliases=["c"])
    async def close_command(ctx: commands.Context):
        """Close a tourney ticket (staff only)."""
        await close_ticket_via_command(ctx)

    @bot.command(name="lock")
    async def lock_command(ctx: commands.Context):
        """Temporarily lock the OTHER ticket channel from members."""
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to lock the ticket channel.")
            return

        channel = bot.get_channel(OTHER_TICKET_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await ctx.reply("Configured ticket channel not found. Check OTHER_TICKET_CHANNEL_ID.")
            return

        guild = channel.guild

        # Use member role from config, or @everyone if MEMBER_ROLE_ID is None
        if MEMBER_ROLE_ID is None:
            member_role = guild.default_role
        else:
            member_role = guild.get_role(MEMBER_ROLE_ID)

        if member_role is None:
            await ctx.reply("Member role not found in this server.")
            return

        # Hide from members
        await channel.set_permissions(member_role, view_channel=False)
        await ctx.reply(
            f"🔒 Locked {channel.mention}. It will auto-reopen in {LOCK_DURATION_HOURS} hours "
            f"or when `!reopen` is used."
        )

        # Cancel any old timer
        old = lock_tasks.get(channel.id)
        if old and not old.done():
            old.cancel()

        # Remember where the command was run so we can notify there later
        notify_channel_id = ctx.channel.id

        async def auto_reopen():
            try:
                await asyncio.sleep(LOCK_DURATION_HOURS * 3600)
            except asyncio.CancelledError:
                return  # manually reopened with !reopen

            ticket_ch = bot.get_channel(OTHER_TICKET_CHANNEL_ID)
            if isinstance(ticket_ch, discord.TextChannel):
                await ticket_ch.set_permissions(member_role, view_channel=True)

            # Notify in the original channel where !lock was used
            notify_ch = bot.get_channel(notify_channel_id)
            if isinstance(notify_ch, discord.TextChannel):
                await notify_ch.send(
                    f"🔓 Reopened {ticket_ch.mention} automatically after {LOCK_DURATION_HOURS} hours."
                )

        task = asyncio.create_task(auto_reopen())
        lock_tasks[channel.id] = task

    @bot.command(name="unlock")
    async def unlock_command(ctx: commands.Context):
        """
        Manually unlock the general support channel (Legacy feature).
        Previously named !reopen.
        """
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to unlock the ticket channel.")
            return

        channel = bot.get_channel(OTHER_TICKET_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await ctx.reply("Configured ticket channel not found. Check OTHER_TICKET_CHANNEL_ID.")
            return

        guild = channel.guild

        if MEMBER_ROLE_ID is None:
            member_role = guild.default_role
        else:
            member_role = guild.get_role(MEMBER_ROLE_ID)

        if member_role is None:
            await ctx.reply("Member role not found in this server.")
            return

        # Restore permissions for members
        await channel.set_permissions(member_role, view_channel=True)

        # Cancel any auto-lock timer
        task = lock_tasks.pop(channel.id, None)
        if task and not task.done():
            task.cancel()

        await ctx.reply(f"🔓 **Unlocked** {channel.mention}. Members can see it again.")
        
    @bot.command(name="delete", aliases=["del"])
    async def delete_command(ctx: commands.Context):
        """Delete a ticket (backup for button)."""
        await delete_ticket_via_command(ctx)

    @bot.command(name="reopen")
    async def reopen_command(ctx: commands.Context):
        """
        Reopen a closed tourney ticket channel.
        Moves it from the Closed Category back to the Active Category.
        """
        # Check if we are inside a CLOSED ticket category
        if ctx.channel.category_id in (TOURNEY_CLOSED_CATEGORY_ID, PRE_TOURNEY_CLOSED_CATEGORY_ID):
            await reopen_ticket_via_command(ctx)
        else:
            await ctx.reply("⚠️ This command is for reopening **Closed Tourney Tickets**.\nTo unlock the main support channel, use `!unlock`.")

    @bot.command(name="starttourney")
    async def start_tourney_command(ctx: commands.Context):
        """
        Start a tourney:
        - Reset ticket counter.
        - Lock OTHER ticket channel.
        - Setup Main Tourney Support (Open Perms, Send Panel, then Background Rename).
        - Setup Pre-Tourney Support (Close Perms, Delete Tickets, then Background Rename).
        """
        # Staff-only
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to start the tourney.")
            return

        guild = ctx.guild
        if not guild:
            return

        # 1. Reset ticket numbering & Lock other channel (Existing)
        reset_ticket_counter()
        await lock_command(ctx)

        # 2. Update MAIN Tourney Support Channel
        # GOAL: 「🔴」tourney-support | Perms: Everyone View(/) Send(X)
        main_channel = guild.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(main_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical - Do this first)
            overwrites = main_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await main_channel.edit(overwrites=overwrites)
            await main_channel.purge()

            # B. Send Panel (Critical)
            embed = discord.Embed(
                title="🎟️ Tournament Support Ticket",
                description=(
                    "Experiencing a match issue? We’ve got you covered.\n"
                    "Use this if you're dealing with:\n\n"
                    "⚠️ **No-show opponents**\n"
                    "⚔️ **Score disputes**\n"
                    "🛜 **Lobby / connection problems**\n"
                    "📜 **Rule questions or clarifications**\n"
                    "🔧 **Anything else blocking your match**\n\n"
                    "Click the button below to open a **private support ticket**.\n\n"
                    "You’ll be prompted to provide:\n"
                    "📛 **Team Name**\n"
                    "🔢 **Match / Bracket Number**\n"
                    "📝 **Description of the Issue**\n\n"
                    "A Tourney Admin will assist you as soon as possible. 🛠️"
                ),
                color=discord.Color.blurple()
            )
            await main_channel.send(embed=embed, view=TourneyOpenTicketView())

            # C. Attempt Rename (Background Task - Won't block if rate limited)
            asyncio.create_task(main_channel.edit(name="「🔴」tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Main Tourney Channel (ID: {TOURNEY_SUPPORT_CHANNEL_ID})")

        # 3. Update PRE-Tourney Support Channel
        # GOAL: 「❌❌❌」「🟡」pre-tourney-support | Perms: Everyone View(X)
        pre_channel = guild.get_channel(PRE_TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(pre_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical)
            overwrites = pre_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await pre_channel.edit(overwrites=overwrites)
            await pre_channel.purge() 

            # B. Attempt Rename (Background Task)
            asyncio.create_task(pre_channel.edit(name="「❌❌❌」「🟡」pre-tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Pre-Tourney Channel (ID: {PRE_TOURNEY_SUPPORT_CHANNEL_ID})")

        # 4. Delete ALL Pre-Tourney Tickets
        deleted_count = 0
        categories_to_check = [PRE_TOURNEY_CATEGORY_ID, PRE_TOURNEY_CLOSED_CATEGORY_ID]
        
        for cat_id in categories_to_check:
            pre_category = guild.get_channel(cat_id)
            if isinstance(pre_category, discord.CategoryChannel):
                for ch in pre_category.channels:
                    if isinstance(ch, discord.TextChannel) and "ticket-" in ch.name and ch.id != PRE_TOURNEY_SUPPORT_CHANNEL_ID:
                        try:
                            await delete_ticket_with_transcript(guild, ch, ctx.author, bot)
                            deleted_count += 1
                        except Exception as e:
                            print(f"Failed to delete pre-tourney ticket {ch.name}: {e}")
        
        await ctx.send(f"✅ Tourney Started! Channels updated and {deleted_count} pre-tourney tickets deleted.")

    @bot.command(name="endtourney")
    async def end_tourney_command(ctx: commands.Context):
        """
        End the tourney:
        - Reopen the "Other" ticket channel.
        - Setup Main Tourney Support (Close Perms, then Background Rename).
        - Setup Pre-Tourney Support (Open Perms, Send Panel, then Background Rename).
        - Close & delete all MAIN tourney tickets.
        """
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to end the tourney.")
            return

        guild = ctx.guild
        if guild is None:
            return

        await reopen_command(ctx)

        # 1. Update MAIN Tourney Support Channel
        # GOAL: 「❌❌❌」「🔴」tourney-support | Perms: Everyone View(X)
        main_channel = guild.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(main_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical)
            overwrites = main_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await main_channel.edit(overwrites=overwrites)
            await main_channel.purge()

            # B. Attempt Rename (Background Task)
            asyncio.create_task(main_channel.edit(name="「❌❌❌」「🔴」tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Main Tourney Channel (ID: {TOURNEY_SUPPORT_CHANNEL_ID})")

        # 2. Update PRE-Tourney Support Channel
        # GOAL: 「🟡」pre-tourney-support | Perms: Everyone View(/) Send(X)
        pre_channel = guild.get_channel(PRE_TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(pre_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical)
            overwrites = pre_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await pre_channel.edit(overwrites=overwrites)
            await pre_channel.purge()

            # B. Send Pre-Tourney Panel (Critical)
            embed = discord.Embed(
                title="📩 Pre-Tournament Support",
                description=(
                    "Need help before the tournament starts? Use this for:\n\n"
                    "📋 **Registration Issues**\n"
                    "🤝 **Team / Roster Questions**\n"
                    "❓ **General Inquiries**\n\n"
                    "Click the button below to open a ticket. **Team Name** is optional." 
                ),
                color=discord.Color.orange()
            )
            await pre_channel.send(embed=embed, view=PreTourneyOpenTicketView())

            # C. Attempt Rename (Background Task)
            asyncio.create_task(pre_channel.edit(name="「🟡」pre-tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Pre-Tourney Channel (ID: {PRE_TOURNEY_SUPPORT_CHANNEL_ID})")

        # 3. Delete ALL MAIN Tourney Tickets
        ticket_channels: list[discord.TextChannel] = []
        categories_to_check = [TOURNEY_CATEGORY_ID, TOURNEY_CLOSED_CATEGORY_ID]

        for cat_id in categories_to_check:
            cat = guild.get_channel(cat_id)
            if isinstance(cat, discord.CategoryChannel):
                for ch in cat.channels:
                    # Delete if it's a ticket and NOT the support channel
                    if isinstance(ch, discord.TextChannel) and "ticket-" in ch.name and ch.id != TOURNEY_SUPPORT_CHANNEL_ID:
                        ticket_channels.append(ch)

        if not ticket_channels:
            await ctx.reply("No tourney tickets found to delete.")
            return

        await ctx.reply(
            f"Ending tourney. Deleting {len(ticket_channels)} ticket(s) with transcripts..."
        )

        for ch in ticket_channels:
            try:
                await delete_ticket_with_transcript(
                    guild=guild,
                    channel=ch,
                    deleter=ctx.author,
                    client=bot,
                )
            except Exception as e:
                print(f"Error deleting ticket {ch.id} ({ch.name}): {e}")

    # =========================================================================
    #  SLASH COMMANDS (Restored from your New File)
    # =========================================================================

    @app_commands.command(name="tourney-panel", description="Post the tourney support button.")
    async def tourney_panel(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎟️ Tournament Support Ticket",
            description=(
                "Experiencing a match issue? We’ve got you covered.\n"
                "Use this if you're dealing with:\n\n"
                "⚠️ **No-show opponents**\n"
                "⚔️ **Score disputes**\n"
                "🛜 **Lobby / connection problems**\n"
                "📜 **Rule questions or clarifications**\n"
                "🔧 **Anything else blocking your match**\n\n"
                "Click the button below to open a **private support ticket**.\n\n"
                "You’ll be prompted to provide:\n"
                "📛 **Team Name**\n"
                "🔢 **Match / Bracket Number**\n"
                "📝 **Description of the Issue**\n\n"
                "A Tourney Admin will assist you as soon as possible. 🛠️"
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, view=TourneyOpenTicketView())

    @app_commands.command(name="pre-tourney-panel", description="Post the Pre-Tourney support button.")
    async def pre_tourney_panel(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📩 Pre-Tournament Support",
            description=(
                "Need help before the tournament starts? Use this for:\n\n"
                "📋 **Registration Issues**\n"
                "🤝 **Team / Roster Questions**\n"
                "❓ **General Inquiries**\n\n"
                "Click the button below to open a ticket. **Team Name** is optional."
            ),
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, view=PreTourneyOpenTicketView())

    @app_commands.command(name="add", description="Add a user to this tourney ticket.")
    async def add_to_ticket(interaction: discord.Interaction, user: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("You don't have permission to add users to tickets.", ephemeral=True)
            return
        
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a ticket text channel.", ephemeral=True)
            return

        if channel.category_id not in (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID):
            await interaction.response.send_message("This command can only be used inside a tourney ticket channel.", ephemeral=True)
            return

        await channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(f"✅ Added {user.mention} to this ticket.", ephemeral=True)
        await channel.send(f"{user.mention} has been added to this ticket by {interaction.user.mention}.")
    
    @app_commands.command(name="remove", description="Remove a user from this tourney ticket.")
    async def remove_from_ticket(interaction: discord.Interaction, user: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("You don't have permission to remove users from tickets.", ephemeral=True)
            return
        
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a ticket text channel.", ephemeral=True)
            return

        if channel.category_id not in (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID):
            await interaction.response.send_message("This command can only be used inside a tourney ticket channel.", ephemeral=True)
            return

        await channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(f"✅ Removed {user.mention} from this ticket.", ephemeral=True)
        await channel.send(f"{user.mention} has been removed from this ticket by {interaction.user.mention}.")

    @app_commands.command(name="hall-of-fame", description="Post results to Hall of Fame.")
    async def hall_of_fame(interaction: discord.Interaction, tourney_name: str, link: str, total_prize: str, first: str, second: str, third: str, fourth: str):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        target_channel = guild.get_channel(HALL_OF_FAME_CHANNEL_ID)
        if target_channel is None or not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message(f"❌ Could not find the configured Hall of Fame channel (ID: {HALL_OF_FAME_CHANNEL_ID}). Please check `tourney_config.py`.", ephemeral=True)
            return

        clean_prize = total_prize.replace('$', '').replace(',', '').strip()
        try:
            total = float(clean_prize)
        except ValueError:
            await interaction.response.send_message(f"❌ Invalid prize amount: `{total_prize}`. Please enter a number like `105.61`.", ephemeral=True)
            return

        p1 = total * 0.50
        p2 = total * 0.25
        p3 = total * 0.15
        p4 = total * 0.10

        embed = discord.Embed(
            title=f"🏆 {tourney_name}",
            url=link,
            description=(
                f"💰 **Total Prize:** ${total:.2f}\n\n"
                f"🥇 **{first}** — ${p1:.2f} (50%)\n"
                f"🥈 **{second}** — ${p2:.2f} (25%)\n"
                f"🥉 **{third}** — ${p3:.2f} (15%)\n"
                f"4️⃣ **{fourth}** — ${p4:.2f} (10%)"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Congratulations to the winners! 🎉")

        try:
            await target_channel.send(embed=embed)
            await interaction.response.send_message(f"✅ Hall of Fame post sent to {target_channel.mention}!", ephemeral=False)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ I don't have permission to send messages in {target_channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to send message: {e}", ephemeral=True)

    # =========================================================================
    #  PAYOUT COMMANDS
    # =========================================================================

    @app_commands.command(name="payout-add", description="Add compensation for tourney admins.")
    @app_commands.describe(
        mode="Split: Divides amount among admins. Flat: Each admin gets the full amount.",
        amount="The amount of currency.",
        staff_mentions="Mention the admins (e.g. @Admin1 @Admin2)",
        reason="Reason for this payout (e.g. Weekly Tourney)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Split Total Evenly", value="split"),
        app_commands.Choice(name="Flat Rate Per Person", value="flat")
    ])
    async def payout_add(interaction: discord.Interaction, mode: str, amount: float, staff_mentions: str, reason: str):
        # 1. Security Check
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to manage payouts.", ephemeral=True)
            return

        # 2. Parse User IDs
        found_ids = [str(uid) for uid in re.findall(r'<@!?(\d+)>', staff_mentions)]
        staff_ids = list(set(found_ids)) # Remove duplicates

        if not staff_ids:
            await interaction.response.send_message("❌ No valid user mentions found.", ephemeral=True)
            return

        # 3. Calculate Math
        payout_per_person = 0
        if mode == "split":
            payout_per_person = amount / len(staff_ids)
        else:
            payout_per_person = amount

        # 4. Update Database (Batch System)
        await add_payout_batch(payout_per_person, staff_ids, reason)

        # 5. Response
        embed = discord.Embed(title="💰 Payouts Recorded", color=discord.Color.green())
        embed.add_field(name="Mode", value=mode.title(), inline=True)
        embed.add_field(name="Amount Per Admin", value=f"{payout_per_person:,.2f}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        mentions_str = " ".join([f"<@{uid}>" for uid in staff_ids])
        embed.add_field(name="Staff Credited", value=mentions_str, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="payout-list", description="View all pending tourney admin payouts.")
    async def payout_list(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        rows = await get_all_pending_payouts()

        if not rows:
            await interaction.response.send_message("✅ No pending payouts found. All clear!", ephemeral=True)
            return

        embed = discord.Embed(title="🧾 Pending Staff Payouts", color=discord.Color.blurple())
        description = ""
        total_owed = 0

        for row in rows:
            user_id = row["_id"]
            amt = row.get("amount", 0)
            if amt > 0:
                description += f"<@{user_id}>: **{amt:,.2f}**\n"
                total_owed += amt

        if total_owed == 0:
             await interaction.response.send_message("✅ No pending payouts found (balances are 0).", ephemeral=True)
             return

        embed.description = description
        embed.set_footer(text=f"Total Treasury Needed: {total_owed:,.2f}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="payout-reset", description="Clear payouts (Cash Out).")
    @app_commands.describe(target="Leave empty to reset ALL, or tag a user to reset only them.")
    async def payout_reset(interaction: discord.Interaction, target: discord.User = None):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Option A: Reset One Person
        if target:
            await clear_pending_payout(str(target.id))
            await interaction.response.send_message(f"✅ Cashed out {target.mention}. Receipts cleared.", ephemeral=False)
            return

        # Option B: Reset EVERYONE
        view = PayoutResetConfirmView()
        await interaction.response.send_message(
            "⚠️ **WARNING** ⚠️\nYou are about to wipe **ALL** pending staff payouts.\nAre you sure?", 
            view=view, 
            ephemeral=True
        )

        await view.wait()
        
        if view.value is True:
            await clear_pending_payout(None)
            await interaction.followup.send("✅ All pending admin payouts have been cashed out.", ephemeral=False)
        else:
            await interaction.followup.send("❌ Operation cancelled.", ephemeral=True)

    @app_commands.command(name="payout-history", description="View log of multi-user additions.")
    async def payout_history(interaction: discord.Interaction):
        """
        Displays logs for multi-user adds. 
        Only shows users who still 'owe' the specific batch ID (have not been reset).
        """
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return
            
        logs = await get_payout_logs(limit=20)
        if not logs:
            await interaction.response.send_message("No logs found.", ephemeral=True)
            return

        embed = discord.Embed(title="📜 Group Payout History", color=discord.Color.gold())
        logs_found = False

        for entry in logs:
            # FILTER 1: Only show logs where multiple people were involved
            if len(entry["user_ids"]) <= 1:
                continue

            batch_id = entry.get("batch_id")
            active_users_display = []

            # FILTER 2: Check who still has the receipt
            for uid in entry["user_ids"]:
                user_batches = await get_user_unpaid_batches(uid)
                # If the batch_id is still in their list, they haven't been paid for this yet.
                if batch_id in user_batches:
                    active_users_display.append(f"<@{uid}>")

            # FILTER 3: If everyone in this log has been paid out, skip showing the log
            if not active_users_display:
                continue

            logs_found = True
            date_str = entry["timestamp"].strftime("%Y-%m-%d")
            
            users_str = ", ".join(active_users_display)
            value_text = (
                f"**Amount:** {entry['amount']:,.2f} per person\n"
                f"**Reason:** {entry['reason']}\n"
                f"**Included:** {users_str}"
            )
            
            embed.add_field(name=f"📅 {date_str} - Group Add", value=value_text, inline=False)

        if logs_found:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("✅ No outstanding multi-user payouts found.", ephemeral=True)

    bot.tree.add_command(tourney_panel)
    bot.tree.add_command(pre_tourney_panel)
    bot.tree.add_command(add_to_ticket)
    bot.tree.add_command(remove_from_ticket)
    bot.tree.add_command(hall_of_fame)
    bot.tree.add_command(payout_add)
    bot.tree.add_command(payout_list)
    bot.tree.add_command(payout_reset)
    bot.tree.add_command(payout_history)
