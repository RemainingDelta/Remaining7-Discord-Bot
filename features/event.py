import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import zoneinfo
import re
from database.mongo import (
    claim_event_reward_payout,
    get_stuck_event_reward_payouts,
    increment_user_balance,
    is_poll_reward_processed,
    mark_event_reward_paid,
    mark_poll_reward_processed,
    resolve_stuck_event_reward_payout,
)

from features.config import (
    ADMIN_ROLE_ID,
    EVENT_STAFF_ROLE_ID,
    RED_EVENT_CHANNEL_ID,
    BLUE_EVENT_CHANNEL_ID,
    GREEN_EVENT_CHANNEL_ID,
    EVENT_STAFF_CHANNEL_ID,
    POLLS_CHANNEL_ID,
    EVENT_ANNOUNCEMENTS_CHANNEL_ID,
    BOT_VERSION,
)

# Mapping for easier looping
EVENT_CHANNELS = {
    "red": RED_EVENT_CHANNEL_ID,
    "blue": BLUE_EVENT_CHANNEL_ID,
    "green": GREEN_EVENT_CHANNEL_ID,
}


class ClearChannelView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)  # Persistent view
        self.channel_id = channel_id

        # --- DYNAMIC BUTTON STYLING ---
        # Get the button (it is the first item in children)
        button = self.children[0]

        if channel_id == RED_EVENT_CHANNEL_ID:
            button.style = discord.ButtonStyle.danger
            button.label = "Purge Red Event"
            # Optional: Add emoji
            # button.emoji = "🔴"
        elif channel_id == BLUE_EVENT_CHANNEL_ID:
            button.style = discord.ButtonStyle.primary  # Blurple (Blue-ish)
            button.label = "Purge Blue Event"
            # button.emoji = "🔵"
        elif channel_id == GREEN_EVENT_CHANNEL_ID:
            button.style = discord.ButtonStyle.success  # Green
            button.label = "Purge Green Event"
            # button.emoji = "🟢"
        else:
            button.style = discord.ButtonStyle.secondary  # Grey fallback
            button.label = "Purge Channel"

    # Define button with a placeholder style; __init__ overrides it
    @discord.ui.button(
        label="Purge Channel",
        style=discord.ButtonStyle.secondary,
        custom_id="purge_event_btn",
    )
    async def purge_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # 1. Check Permissions
        user_roles = [r.id for r in interaction.user.roles]
        if not (ADMIN_ROLE_ID in user_roles or EVENT_STAFF_ROLE_ID in user_roles):
            await interaction.response.send_message(
                "❌ You do not have permission to use this.", ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message(
                "❌ Channel no longer exists.", ephemeral=True
            )
            return

        # 2. Defer
        await interaction.response.defer()

        # 3. Purge
        try:
            deleted = await channel.purge(limit=None)
            count = len(deleted)
        except Exception as e:
            await interaction.followup.send(
                f"❌ **Error:** Failed to purge channel. Reason: {e}", ephemeral=True
            )
            return

        # 4. Update the Alert Message (Disable button)
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()

        # Success Update - Clean Title, Link in Description
        embed.title = "✅ Purge Complete"
        embed.description = (
            f"{channel.mention} has been cleared.\n\n"
            f"**Deleted:** {count} messages\n"
            f"**By:** {interaction.user.mention}"
        )

        button.disabled = True
        button.label = "Purged"
        button.style = discord.ButtonStyle.secondary

        await interaction.edit_original_response(embed=embed, view=self)

        # 5. Send PUBLIC Confirmation Message in Chat
        await interaction.followup.send(
            f"🗑️ **Cleared!** {interaction.user.mention} purged **{count} messages** in {channel.mention}.",
            ephemeral=False,
        )


class PayoutConfirmView(discord.ui.View):
    def __init__(self, original_msg, matches, interaction_user):
        super().__init__(timeout=60)  # Buttons expire after 60 seconds
        self.original_msg = original_msg
        self.matches = matches  # List of tuples: [('User_ID', 'Amount'), ...]
        self.interaction_user = interaction_user
        self.processed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the person who ran the command to click
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message(
                "❌ This is not your command.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm Payout", style=discord.ButtonStyle.green, emoji="✅"
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.processed:
            return
        self.processed = True

        await interaction.response.defer()

        paid_log = []
        skipped = 0
        total_distributed = 0
        mid = str(self.original_msg.id)
        admin = str(self.interaction_user.id)

        # --- EXECUTE PAYOUTS ---
        # Claim -> pay -> commit, per recipient. The claim writes a paid:False
        # ledger row before the $inc; a pre-existing row (already paid, or a
        # crashed prior run) makes the claim skip, so re-running after a crash
        # only pays recipients who were never claimed — never a double payout.
        for user_id_str, amount_str in self.matches:
            user_id = str(user_id_str)
            amount = int(amount_str)

            if not await claim_event_reward_payout(mid, user_id, amount, admin):
                skipped += 1
                continue

            await increment_user_balance(user_id, amount)
            await mark_event_reward_paid(mid, user_id)  # commit point

            paid_log.append(f"<@{user_id}>: +{amount}")
            total_distributed += amount

        # Mark original message with a checkmark
        try:
            await self.original_msg.add_reaction("✅")
        except Exception:
            pass

        # Update the confirmation message to show success
        embed = interaction.message.embeds[0]
        embed.title = "✅ Payouts Complete"
        embed.color = discord.Color.green()
        embed.clear_fields()
        summary = (
            f"Distributed **{total_distributed}** tokens to **{len(paid_log)}** users."
        )
        if skipped:
            summary += f"\nSkipped **{skipped}** already-processed recipients."
        embed.add_field(
            name="Summary",
            value=summary,
            inline=False,
        )

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.processed = True

        embed = interaction.message.embeds[0]
        embed.title = "❌ Payout Cancelled"
        embed.color = discord.Color.red()
        embed.description = "No tokens were distributed."
        embed.clear_fields()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class PollPayoutConfirmView(discord.ui.View):
    def __init__(self, original_msg, voters, amount, answer_text, interaction_user):
        super().__init__(timeout=60)
        self.original_msg = original_msg
        self.voters = voters
        self.amount = amount
        self.answer_text = answer_text
        self.interaction_user = interaction_user
        self.processed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message(
                "❌ This is not your command.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm Payout", style=discord.ButtonStyle.green, emoji="✅"
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.processed:
            return
        self.processed = True
        await interaction.response.defer()

        # Double-check idempotency before distributing
        if await is_poll_reward_processed(str(self.original_msg.id)):
            embed = interaction.message.embeds[0]
            embed.title = "❌ Already Processed"
            embed.color = discord.Color.red()
            embed.description = "This poll has already been processed."
            embed.clear_fields()
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(embed=embed, view=self)
            return

        # Distribute tokens atomically
        for voter in self.voters:
            await increment_user_balance(str(voter.id), self.amount)

        # Record in DB
        await mark_poll_reward_processed(
            message_id=str(self.original_msg.id),
            admin_id=str(interaction.user.id),
            answer_text=self.answer_text,
            amount=self.amount,
            voter_count=len(self.voters),
        )

        # Mark original poll message with checkmark
        try:
            await self.original_msg.add_reaction("✅")
        except Exception:
            pass

        # Update confirmation embed
        total = self.amount * len(self.voters)
        embed = interaction.message.embeds[0]
        embed.title = "✅ Poll Rewards Complete"
        embed.color = discord.Color.green()
        embed.clear_fields()
        embed.add_field(
            name="Summary",
            value=(
                f"Distributed **{total}** tokens to **{len(self.voters)}** voters.\n"
                f"(**{self.amount}** tokens each for option: *{self.answer_text}*)"
            ),
            inline=False,
        )
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.processed = True
        embed = interaction.message.embeds[0]
        embed.title = "❌ Poll Rewards Cancelled"
        embed.color = discord.Color.red()
        embed.description = "No tokens were distributed."
        embed.clear_fields()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._warning_msg_ids: dict[int, int] = {}  # channel_id → warning message_id
        self.cleanup_check_task.start()
        self.event_reward_reconcile_task.start()

    def cog_unload(self):
        self.cleanup_check_task.cancel()
        self.event_reward_reconcile_task.cancel()

    async def has_event_permission(self, interaction: discord.Interaction):
        if isinstance(interaction.user, discord.Member):
            if interaction.user.get_role(ADMIN_ROLE_ID) or interaction.user.get_role(
                EVENT_STAFF_ROLE_ID
            ):
                return True
        return False

    async def execute_purge(
        self, interaction: discord.Interaction, channel_id: int, color_name: str
    ):
        # 1. Permission Check
        if not await self.has_event_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied: You need Admin or Event Staff role.",
                ephemeral=True,
            )
            return

        # 2. Channel Check (Must be in #event-staff)
        if interaction.channel_id != EVENT_STAFF_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ You can only use this command in <#{EVENT_STAFF_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        target_channel = self.bot.get_channel(channel_id)
        if not target_channel:
            await interaction.response.send_message(
                f"❌ Error: Could not find #{color_name}-event channel.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            deleted = await target_channel.purge(limit=None)

            # 3. Send PUBLIC Confirmation
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"🧹 {color_name} Event Cleared",
                    description=f"✅ **Success!** Deleted **{len(deleted)}** messages in {target_channel.mention}.",
                    color=discord.Color.green(),
                )
            )
        except Exception as e:
            await interaction.followup.send(f"❌ **Error:** Failed to purge. {e}")

    # --- COMMANDS ---

    @app_commands.command(
        name="clear-red", description="Purge all messages in the #red-event channel."
    )
    async def clear_red(self, interaction: discord.Interaction):
        await self.execute_purge(interaction, RED_EVENT_CHANNEL_ID, "Red")

    @app_commands.command(
        name="clear-blue", description="Purge all messages in the #blue-event channel."
    )
    async def clear_blue(self, interaction: discord.Interaction):
        await self.execute_purge(interaction, BLUE_EVENT_CHANNEL_ID, "Blue")

    @app_commands.command(
        name="clear-green",
        description="Purge all messages in the #green-event channel.",
    )
    async def clear_green(self, interaction: discord.Interaction):
        await self.execute_purge(interaction, GREEN_EVENT_CHANNEL_ID, "Green")

    # --- SCHEDULED TASK (12 AM ET) ---

    # ⚠️ FOR TESTING: Change to @tasks.loop(seconds=10)
    @tasks.loop(
        time=time(hour=0, minute=0, tzinfo=zoneinfo.ZoneInfo("America/New_York"))
    )
    async def cleanup_check_task(self):
        if not self.bot.is_ready():
            return

        staff_channel = self.bot.get_channel(EVENT_STAFF_CHANNEL_ID)
        if not staff_channel:
            print("❌ Error: Event Staff channel not found for Cleanup Check.")
            return

        for name, channel_id in EVENT_CHANNELS.items():
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            try:
                # Check only the single oldest message
                async for message in channel.history(limit=1, oldest_first=True):
                    msg_date = message.created_at
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))

                    now_utc = datetime.now(zoneinfo.ZoneInfo("UTC"))
                    age = now_utc - msg_date

                    # ⚠️ FOR TESTING: Change to if age.days >= 0:
                    if age.days >= 7:
                        embed = discord.Embed(
                            title="⚠️ Cleanup Warning",
                            description=f"{channel.mention} has messages older than **{age.days} days**.",
                            color=discord.Color.orange(),
                        )
                        embed.add_field(
                            name="Action Required",
                            value="Discord cannot bulk delete messages >14 days old.\nPlease clear this channel soon.",
                            inline=False,
                        )

                        old_msg_id = self._warning_msg_ids.get(channel_id)
                        if old_msg_id:
                            try:
                                old_msg = await staff_channel.fetch_message(old_msg_id)
                                await old_msg.delete()
                            except (discord.NotFound, discord.HTTPException):
                                pass

                        view = ClearChannelView(channel_id)
                        new_msg = await staff_channel.send(embed=embed, view=view)
                        self._warning_msg_ids[channel_id] = new_msg.id
                        print(f"⚠️ Sent cleanup alert for #{name}-event")

                    break
            except Exception as e:
                print(f"Error checking history for #{name}-event: {e}")

    # --- EVENT REWARD CRASH RECOVERY ---

    @tasks.loop(count=1)
    async def event_reward_reconcile_task(self):
        """Runs once per process, after the bot is ready. A cog is loaded once
        and not re-added on gateway reconnect, so this is cold-boot-only."""
        await self.bot.wait_until_ready()
        try:
            await self.reconcile_event_rewards()
        except Exception as e:
            print(f"❌ Event reward reconcile failed: {e}")

    async def reconcile_event_rewards(self):
        """Reports (does NOT re-pay) any recipient left claimed-but-unpaid by a
        crash between the ledger claim and the balance $inc. Re-paying can't be
        safe here: a paid:False row can't tell 'crashed before the $inc' from
        'crashed after it', so an auto-repay could double-pay. Staff recover with
        a manual /give and clear the row via /check-stuck-payouts."""
        stuck = await get_stuck_event_reward_payouts()
        if not stuck:
            return

        staff_channel = self.bot.get_channel(EVENT_STAFF_CHANNEL_ID)
        if not staff_channel:
            print("❌ Event reward reconcile: staff channel not found.")
            return

        lines = [
            f"• <@{row['user_id']}> — **{row.get('amount', 0)}** tokens "
            f"(msg `{row.get('message_id', '?')}`)"
            for row in stuck
        ]
        text = "\n".join(lines)
        if len(text) > 1024:
            text = text[:960] + "\n... (more hidden)"

        embed = discord.Embed(
            title="⚠️ Stuck Event Payouts Detected",
            description=(
                f"**{len(stuck)}** recipient(s) were claimed for an event payout "
                "but their tokens were never confirmed (likely a crash mid-payout).\n"
                "These were **not** auto-paid to avoid double-paying. Pay each with "
                "`/give`, then run `/check-stuck-payouts resolve:True` to clear them."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(name="Unconfirmed Recipients", value=text, inline=False)
        try:
            await staff_channel.send(embed=embed)
        except Exception as e:
            print(f"❌ Event reward reconcile: failed to post report: {e}")

    @app_commands.command(
        name="event-rewards",
        description="ADMIN ONLY: Distribute tokens from an announcement.",
    )
    @app_commands.describe(message_id="The ID of the message in #event-announcements")
    async def event_rewards(self, interaction: discord.Interaction, message_id: str):
        # 1. Permission Check - STRICTLY ADMIN ONLY
        # We access the role directly rather than using the shared helper
        if not interaction.user.get_role(ADMIN_ROLE_ID):
            await interaction.response.send_message(
                "❌ Permission Denied: Only Admins can process rewards.", ephemeral=True
            )
            return

        # 2. Channel Check
        if interaction.channel_id != EVENT_STAFF_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ Please use this command in <#{EVENT_STAFF_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # 3. Fetch Message from Configured Channel
        ann_channel = self.bot.get_channel(EVENT_ANNOUNCEMENTS_CHANNEL_ID)
        if not ann_channel:
            await interaction.followup.send(
                "❌ Config Error: Announcement channel not found."
            )
            return

        try:
            target_message = await ann_channel.fetch_message(int(message_id))
        except Exception:
            await interaction.followup.send(
                "❌ Could not find that message ID in the announcements channel."
            )
            return

        # 4. Check for previous processing
        if any(r.emoji == "✅" and r.me for r in target_message.reactions):
            await interaction.followup.send(
                "⚠️ This message has already been processed (marked with ✅)."
            )
            return

        # 5. Parse Data
        pattern = r"<@!?(\d+)>\s+(\d+)"
        matches = re.findall(pattern, target_message.content)

        if not matches:
            await interaction.followup.send(
                "⚠️ No valid `User Amount` pairs found.\nFormat required: `@User 500`"
            )
            return

        # 6. Generate Preview
        preview_lines = []
        total_preview = 0
        for uid, amt in matches:
            amt = int(amt)
            preview_lines.append(f"• <@{uid}> ➡️ **{amt}**")
            total_preview += amt

        preview_text = "\n".join(preview_lines)
        if len(preview_text) > 2000:
            preview_text = preview_text[:2000] + "\n... (more users hidden)"

        # 7. Send Confirmation
        embed = discord.Embed(
            title="⚠️ Confirm Event Rewards?",
            description=f"Found **{len(matches)} users**.\nTotal Payout: **{total_preview} tokens**.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Recipient List", value=preview_text)

        view = PayoutConfirmView(target_message, matches, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="check-stuck-payouts",
        description="ADMIN ONLY: List event payouts claimed but never confirmed paid.",
    )
    @app_commands.describe(
        resolve="Mark the listed rows resolved (only after you've paid them via /give)."
    )
    async def check_stuck_payouts(
        self, interaction: discord.Interaction, resolve: bool = False
    ):
        # 1. Permission Check - STRICTLY ADMIN ONLY
        if not interaction.user.get_role(ADMIN_ROLE_ID):
            await interaction.response.send_message(
                "❌ Permission Denied: Only Admins can check payouts.", ephemeral=True
            )
            return

        # 2. Channel Check
        if interaction.channel_id != EVENT_STAFF_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ Please use this command in <#{EVENT_STAFF_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        stuck = await get_stuck_event_reward_payouts()
        if not stuck:
            await interaction.followup.send(
                "✅ No stuck payouts — every claimed recipient was confirmed paid."
            )
            return

        lines = []
        for row in stuck:
            lines.append(
                f"• <@{row['user_id']}> — **{row.get('amount', 0)}** tokens "
                f"(msg `{row.get('message_id', '?')}`)"
            )
        text = "\n".join(lines)
        if len(text) > 1024:
            text = text[:960] + "\n... (more hidden)"

        if resolve:
            for row in stuck:
                await resolve_stuck_event_reward_payout(
                    row.get("message_id", ""),
                    row.get("user_id", ""),
                    str(interaction.user.id),
                )
            title = "🧹 Stuck Payouts Resolved"
            description = (
                f"Marked **{len(stuck)}** row(s) resolved. Make sure you paid each "
                "with `/give` first — this only clears the report, it moves no tokens."
            )
            color = discord.Color.green()
        else:
            title = "⚠️ Stuck Event Payouts"
            description = (
                f"**{len(stuck)}** recipient(s) were claimed but never confirmed "
                "paid (likely a crash mid-payout). Pay each with `/give`, then run "
                "`/check-stuck-payouts resolve:True` to clear them. Nothing is "
                "auto-paid — re-paying could double-pay."
            )
            color = discord.Color.orange()

        embed = discord.Embed(title=title, description=description, color=color)
        embed.add_field(name="Recipients", value=text, inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="poll-rewards",
        description="ADMIN ONLY: Distribute tokens to voters of a poll option.",
    )
    @app_commands.describe(
        message_id="The ID of the poll message in #polls",
        answer="The poll option text to reward (case-insensitive match)",
        amount="Flat token amount to give each voter",
    )
    async def poll_rewards(
        self,
        interaction: discord.Interaction,
        message_id: str,
        answer: str,
        amount: int,
    ):
        # 1. Permission Check - Admin only
        if not interaction.user.get_role(ADMIN_ROLE_ID):
            await interaction.response.send_message(
                "❌ Permission Denied: Only Admins can process poll rewards.",
                ephemeral=True,
            )
            return

        # 2. Channel Check
        if interaction.channel_id != EVENT_STAFF_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ Please use this command in <#{EVENT_STAFF_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        # 3. Validate amount
        if amount <= 0:
            await interaction.response.send_message(
                "❌ Amount must be a positive number.", ephemeral=True
            )
            return

        await interaction.response.defer()

        # 4. Check idempotency (DB-backed)
        if await is_poll_reward_processed(message_id):
            await interaction.followup.send(
                "⚠️ This poll message has already been processed for rewards."
            )
            return

        # 5. Fetch message from polls channel
        polls_channel = self.bot.get_channel(POLLS_CHANNEL_ID)
        if not polls_channel:
            await interaction.followup.send("❌ Config Error: Polls channel not found.")
            return

        try:
            target_message = await polls_channel.fetch_message(int(message_id))
        except Exception:
            await interaction.followup.send(
                "❌ Could not find that message ID in the polls channel."
            )
            return

        # 6. Validate poll exists
        if not target_message.poll:
            await interaction.followup.send("❌ That message does not contain a poll.")
            return

        poll = target_message.poll

        # 7. Check poll is finalized
        if not poll.is_finalized():
            await interaction.followup.send(
                "⚠️ This poll has not ended yet. Please wait for it to close."
            )
            return

        # 8. Match answer text (case-insensitive)
        matched_answer = None
        for poll_answer in poll.answers:
            if poll_answer.text and poll_answer.text.lower() == answer.lower():
                matched_answer = poll_answer
                break

        if not matched_answer:
            available = ", ".join(f'"{a.text}"' for a in poll.answers if a.text)
            await interaction.followup.send(
                f'❌ No poll option matches "{answer}".\nAvailable options: {available}'
            )
            return

        # 9. Fetch all voters via async iterator
        voters = []
        async for voter in matched_answer.voters(limit=None):
            voters.append(voter)

        if not voters:
            await interaction.followup.send(
                f'⚠️ No voters found for option "{matched_answer.text}".'
            )
            return

        # 10. Build confirmation embed
        total = amount * len(voters)
        embed = discord.Embed(
            title="⚠️ Confirm Poll Rewards?",
            description=(
                f"**Poll Option:** {matched_answer.text}\n"
                f"**Voters:** {len(voters)}\n"
                f"**Amount Per Voter:** {amount} tokens\n"
                f"**Total Payout:** {total} tokens"
            ),
            color=discord.Color.orange(),
        )

        voter_preview = ", ".join(f"<@{v.id}>" for v in voters[:20])
        if len(voters) > 20:
            voter_preview += f"\n... and {len(voters) - 20} more"
        embed.add_field(name="Voters", value=voter_preview, inline=False)

        view = PollPayoutConfirmView(
            target_message, voters, amount, matched_answer.text, interaction.user
        )
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="event-staff-help",
        description="STAFF ONLY: Guide for managing event channels.",
    )
    async def event_staff_help(self, interaction: discord.Interaction):
        # 1. Permission Check
        if not await self.has_event_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied: This command is for Event Staff only.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"📋 Event Staff Guide | {BOT_VERSION}",
            description="Reference guide for managing live event channels and automated cleanup tasks.",
            color=discord.Color.blue(),
        )

        # --- Channel Management ---
        mgmt_text = (
            f"`/clear-red` - Purge all messages in <#{RED_EVENT_CHANNEL_ID}>\n"
            f"`/clear-blue` - Purge all messages in <#{BLUE_EVENT_CHANNEL_ID}>\n"
            f"`/clear-green` - Purge all messages in <#{GREEN_EVENT_CHANNEL_ID}>\n"
            f"*Note: These commands must be run in <#{EVENT_STAFF_CHANNEL_ID}>.*"
        )
        embed.add_field(name="🧹 Manual Purge Commands", value=mgmt_text, inline=False)

        # --- Reward Distribution ---
        reward_text = (
            "`/event-rewards <message_id>` - Process token distribution from an announcement message.\n"
            "*(Message must use `@User 500` format. Admin only.)*\n\n"
            "`/poll-rewards <message_id> <answer> <amount>` - Distribute tokens to all voters of a poll option.\n"
            "*(Poll must be finalized. Case-insensitive option match. Admin only.)*\n\n"
            "`/check-stuck-payouts [resolve]` - List event payouts claimed but never confirmed paid.\n"
            "*(Pay each with `/give`, then re-run with `resolve:True` to clear. Admin only.)*"
        )
        embed.add_field(name="🏆 Reward Distribution", value=reward_text, inline=False)

        # --- Automated Cleanup ---
        cleanup_text = (
            "Every day at **12:00 AM ET**, the bot checks for messages older than **7 days**.\n"
            "If a channel is detected as 'stale', a **Cleanup Warning** will be posted here.\n\n"
            "**How to handle alerts:**\n"
            "Click the button on the alert embed to immediately purge that channel. "
            "This keeps channels clean and prevents Discord's 14-day bulk-delete limitation."
        )
        embed.add_field(
            name="⏲️ Automated Cleanup System", value=cleanup_text, inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Events(bot))
