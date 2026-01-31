import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import re 
import datetime 

from database.mongo import (
    add_payout_batch,         
    get_payout_logs,         
    get_user_unpaid_batches, 
    get_all_pending_payouts, 
    clear_pending_payout,
    add_blacklisted_user,
    remove_blacklisted_user,
    get_all_blacklisted_users,
    get_blacklisted_user,
    create_tourney_session,
    get_active_tourney_session,
    end_tourney_session,
    increment_tourney_message_count,
    update_tourney_queue,
    increment_staff_closure,
    get_top_staff_stats
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

class QueueDashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.dashboard_task.start()  <-- Manual start via !starttourney

    def cog_unload(self):
        self.dashboard_task.cancel()

    async def start_dashboard(self):
        """Starts the loop if not already running."""
        if not self.dashboard_task.is_running():
            self.dashboard_task.start()
            print("📊 Queue Dashboard Started")

    async def stop_dashboard(self):
        """Stops the loop and deletes the message."""
        if self.dashboard_task.is_running():
            self.dashboard_task.cancel()
            print("📊 Queue Dashboard Stopped")
        
        # Cleanup
        channel = self.bot.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if channel and isinstance(channel, discord.TextChannel):
            try:
                async for m in channel.history(limit=10):
                    if m.author == self.bot.user and m.embeds and m.embeds[0].title == "📊 Live Tournament Queue":
                        await m.delete()
                        break
            except Exception as e:
                print(f"Failed to cleanup dashboard message: {e}")

    @tasks.loop(seconds=15)
    async def dashboard_task(self):
        """Updates the live queue status in the main support channel."""
        await self.bot.wait_until_ready()
        
        channel = self.bot.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        # 1. Get Active Tickets
        guild = channel.guild
        cat = guild.get_channel(TOURNEY_CATEGORY_ID)
        
        active_tickets = []
        active_nums = [] # List to store just the integers (e.g., [3, 4, 5])

        if cat and isinstance(cat, discord.CategoryChannel):
            active_tickets = [c for c in cat.channels if isinstance(c, discord.TextChannel) and "ticket-" in c.name]
            # Sort by creation time to establish line order
            active_tickets.sort(key=lambda c: c.created_at)

            # Extract numbers from active tickets for logic checks
            for t in active_tickets:
                match = re.search(r"ticket-(\d+)", t.name)
                if match:
                    try:
                        active_nums.append(int(match.group(1)))
                    except ValueError:
                        pass
            
            # Sort numbers just in case creation time didn't match numbering perfectly
            active_nums.sort()

        count = len(active_tickets)

        # 2. Determine Message Content
        embed = discord.Embed(title="📊 Live Tournament Queue", color=discord.Color.blurple())
        
        # --- LOGIC START ---
        # If no tickets are open at all, show the "Green" state immediately
        if count == 0:
            embed.color = discord.Color.green()
            embed.description = "✅ **No tickets currently in the queue.**\nStaff are standing by!"
            serving_display = None # Flag to skip adding fields
        else:
            # Calculate Max Closed Number
            max_closed_num = 0
            closed_cat = guild.get_channel(TOURNEY_CLOSED_CATEGORY_ID)
            if closed_cat and isinstance(closed_cat, discord.CategoryChannel):
                for ch in closed_cat.channels:
                    match = re.search(r"ticket-(\d+)", ch.name)
                    if match:
                        try:
                            num = int(match.group(1))
                            if num > max_closed_num:
                                max_closed_num = num
                        except:
                            pass
            
            # Logic: Determine who we are serving
            target_num = max_closed_num + 1
            
            if target_num in active_nums:
                # Ideally, we serve the next number in sequence
                final_serving_num = target_num
            else:
                # EDGE CASE: 
                # The target (MaxClosed + 1) does not exist in active tickets.
                # In this case, serve the LOWEST available open ticket.
                if len(active_nums) > 0:
                    final_serving_num = min(active_nums)
                else:
                    # Should be caught by the (count == 0) check above, but safe fallback
                    final_serving_num = 0 

            serving_display = f"ticket-{final_serving_num:03d}"
            embed.color = discord.Color.orange()

        # 3. Add Timestamp & Fields
        current_timestamp = int(discord.utils.utcnow().timestamp())
        
        # --- FIX IS HERE ---
        # Initialize description to empty string if it is None
        if embed.description is None:
            embed.description = ""
            
        embed.description = f"**Last Updated:** <t:{current_timestamp}:R>\n\n{embed.description}"
        # -------------------

        if serving_display:
            embed.add_field(
                name="🟢 Currently Serving", 
                value=f"**{serving_display}**", 
                inline=True
            )
            embed.add_field(
                name="👥 In Line", 
                value=f"**{count}** tickets waiting", 
                inline=True
            )
            

        # 4. Jump-to-Bottom Logic (Edit or Resend)
        try:
            last_message = None
            async for m in channel.history(limit=1):
                last_message = m
                break 

            old_dashboard_msg = None
            async for m in channel.history(limit=10):
                if m.author == self.bot.user and m.embeds and m.embeds[0].title == "📊 Live Tournament Queue":
                    old_dashboard_msg = m
                    break

            if last_message and old_dashboard_msg and last_message.id == old_dashboard_msg.id:
                try: await old_dashboard_msg.edit(embed=embed)
                except discord.HTTPException: pass 
            else:
                if old_dashboard_msg:
                    try: await old_dashboard_msg.delete()
                    except: pass
                await channel.send(embed=embed)

        except Exception as e:
            print(f"Queue Dashboard Error: {e}")
            
class BlacklistGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="blacklist", description="Manage tournament blacklisted users")
        self.bot = bot

    @app_commands.command(name="add", description="Blacklist a user from tournaments.")
    @app_commands.describe(
        user="The user to blacklist",
        reason="Why are they being blacklisted?",
        matcherino="Link to their Matcherino profile (Optional)",
        alts="List of Alt User IDs or mentions (space separated) (Optional)"
    )
    async def blacklist_add(self, interaction: discord.Interaction, user: discord.User, reason: str, matcherino: str = None, alts: str = None):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Parse Alts string into a list of IDs
        alt_ids = []
        if alts:
            # clear out <@! > formatting to get raw IDs
            raw_ids = re.findall(r'\d+', alts)
            alt_ids = list(set(raw_ids)) # unique IDs only

        await add_blacklisted_user(
            user_id=str(user.id),
            reason=reason,
            admin_id=str(interaction.user.id),
            matcherino=matcherino,
            alts=alt_ids
        )

        embed = discord.Embed(title="⛔ User Blacklisted", color=discord.Color.dark_red())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        if matcherino:
            embed.add_field(name="Matcherino", value=matcherino, inline=False)
        if alt_ids:
            alt_mentions = ", ".join([f"<@{aid}>" for aid in alt_ids])
            embed.add_field(name="Registered Alts", value=alt_mentions, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Remove a user from the blacklist.")
    async def blacklist_remove(self, interaction: discord.Interaction, user: discord.User):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Check if they are actually blacklisted first
        existing = await get_blacklisted_user(str(user.id))
        if not existing:
            await interaction.response.send_message(f"⚠️ {user.mention} is not currently blacklisted.", ephemeral=True)
            return

        await remove_blacklisted_user(str(user.id))
        await interaction.response.send_message(f"✅ {user.mention} has been removed from the blacklist.")

    @app_commands.command(name="list", description="View all blacklisted users.")
    async def blacklist_list(self, interaction: discord.Interaction):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        users = await get_all_blacklisted_users()
        if not users:
            await interaction.response.send_message("✅ No users are currently blacklisted.", ephemeral=True)
            return

        # Simple pagination or long list logic
        embed = discord.Embed(title="⛔ Blacklisted Users", color=discord.Color.dark_red())
        
        description_lines = []
        for doc in users:
            uid = doc["_id"]
            reason = doc.get("reason", "No reason provided")
            date_str = doc.get("timestamp").strftime("%Y-%m-%d") if doc.get("timestamp") else "Unknown Date"
            description_lines.append(f"• <@{uid}> (`{uid}`) — {date_str}\n  Reason: *{reason}*")

        # Join lines. If too long, Discord will error, so ideally chunk this. 
        # For now, we truncate to 4000 chars to be safe.
        full_text = "\n\n".join(description_lines)
        if len(full_text) > 4000:
            full_text = full_text[:3990] + "... (list truncated)"
            
        embed.description = full_text
        await interaction.response.send_message(embed=embed)
                                    
def setup_tourney_commands(bot: commands.Bot):
    print("Setting up tourney commands...")

    @bot.command(name="close", aliases=["c"])
    async def close_command(ctx: commands.Context):
        """Close a tourney ticket (staff only)."""
        active_session = await get_active_tourney_session()
        if active_session:
            await increment_staff_closure(active_session['_id'], ctx.author.id, ctx.author.name)
            await update_tourney_queue(active_session['_id'], change=-1)
        # -----------------------
        
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
        
        existing_session = await get_active_tourney_session()
        if existing_session:
            await ctx.send("⚠ **Note:** A tournament session is already active in the database.")
        else:
            await create_tourney_session()

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

        # START THE DASHBOARD
        dashboard_cog = bot.get_cog("QueueDashboard")
        if dashboard_cog:
            await dashboard_cog.start_dashboard()

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
        
        dashboard_cog = bot.get_cog("QueueDashboard")
        if dashboard_cog:
            await dashboard_cog.stop_dashboard()

        guild = ctx.guild
        if guild is None:
            return

        session = await get_active_tourney_session()
        if session:
            # 1. Calculate Duration
            start_time = session['start_time']
            duration = datetime.datetime.utcnow() - start_time
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)

            # 2. Get Staff Leaderboard
            top_staff = await get_top_staff_stats(session['_id'], limit=12)
            
            staff_msg = ""
            
            for i, s in enumerate(top_staff):
                if i == 0: icon = "🥇"
                elif i == 1: icon = "🥈"
                elif i == 2: icon = "🥉"
                else: icon = f"**{i+1}.**" # e.g. "4.", "5.", "6."
                
                staff_msg += f"{icon} **{s['username']}**: {s['tickets_closed']} tickets\n"
            
            if not staff_msg: staff_msg = "No tickets closed."

            # 3. Send Embed
            stat_embed = discord.Embed(title="📊 Tournament Report", color=discord.Color.gold())
            stat_embed.add_field(name="⏱️ Duration", value=f"`{hours}h {minutes}m`", inline=True)
            stat_embed.add_field(name="📩 Total Tickets", value=f"`{session['total_tickets']}`", inline=True)
            stat_embed.add_field(name="💬 Total Messages", value=f"`{session['total_messages']}`", inline=True)
            stat_embed.add_field(name="📈 Peak Queue", value=f"**{session['peak_queue']}** tickets", inline=False)
            stat_embed.add_field(name="🏆 Top Tourney Admins", value=staff_msg, inline=False)
                        
            report_msg = await ctx.send(embed=stat_embed)
            
            try:
                await report_msg.pin()
            except Exception as e:
                print(f"⚠️ Could not pin report: {e}")
            
            # 4. Close Session in DB
            await end_tourney_session(session['_id'])
        # ------------------------------

        await unlock_command(ctx)

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
            
    @app_commands.command(name="queue", description="Check your current position in the ticket line.")
    async def check_queue(interaction: discord.Interaction):
        # 1. Validation
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or "ticket-" not in channel.name:
            await interaction.response.send_message("❌ This command can only be used inside a ticket channel.", ephemeral=True)
            return

        # 2. Identify Queue
        if channel.category_id == TOURNEY_CATEGORY_ID:
            cat = interaction.guild.get_channel(TOURNEY_CATEGORY_ID)
        elif channel.category_id == PRE_TOURNEY_CATEGORY_ID:
            cat = interaction.guild.get_channel(PRE_TOURNEY_CATEGORY_ID)
        else:
            await interaction.response.send_message("❌ This ticket is not in an active queue.", ephemeral=True)
            return

        # 3. Calculate Position
        tickets = [c for c in cat.channels if isinstance(c, discord.TextChannel) and "ticket-" in c.name]
        tickets.sort(key=lambda c: c.created_at)

        try:
            position = tickets.index(channel) + 1
            total = len(tickets)
        except ValueError:
            await interaction.response.send_message("Could not determine position.", ephemeral=True)
            return

        # 4. Report
        if position == 1:
            status = "🟢 **NOW SERVING**"
            desc = f"You are **1/{total}** in the queue.\nA staff member should be with you momentarily!"
            color = discord.Color.green()
        else:
            status = "🟠 **WAITING**"
            desc = f"You are **{position}/{total}** in the queue.\nPlease wait for a staff member."
            color = discord.Color.orange()

        embed = discord.Embed(title="⏳ Queue Status", description=desc, color=color)
        embed.add_field(name="Current Status", value=status, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Start the Dashboard Task ---
    asyncio.create_task(bot.add_cog(QueueDashboard(bot)))
    print("✅ Queue Dashboard task started.")

    bot.tree.add_command(tourney_panel)
    bot.tree.add_command(pre_tourney_panel)
    bot.tree.add_command(add_to_ticket)
    bot.tree.add_command(remove_from_ticket)
    bot.tree.add_command(hall_of_fame)
    bot.tree.add_command(payout_add)
    bot.tree.add_command(payout_list)
    bot.tree.add_command(payout_reset)
    bot.tree.add_command(payout_history)
    bot.tree.add_command(check_queue)
    bot.tree.add_command(BlacklistGroup(bot))


    async def background_stats_update():
        try:
            active = await get_active_tourney_session()
            if active:
                await increment_tourney_message_count(active['_id'])
        except Exception:
            pass # Ignore errors here so we don't spam logs

    @bot.listen()
    async def on_message(message):
        if message.author.bot: return
        if not isinstance(message.channel, discord.TextChannel):
            return
        
        valid_categories = (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID)
        
        # Check conditions (Fast in-memory checks)
        if "ticket-" in message.channel.name and message.channel.category_id in valid_categories:
            
            # 🔥 CRITICAL CHANGE: Fire and forget!
            # This creates a background task so the bot doesn't wait for MongoDB.
            asyncio.create_task(background_stats_update())