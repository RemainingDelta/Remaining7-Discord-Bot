import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import zoneinfo 
import re 
from database.mongo import get_user_balance, update_user_balance 

from features.config import (
    ADMIN_ROLE_ID, 
    EVENT_STAFF_ROLE_ID,
    RED_EVENT_CHANNEL_ID,
    BLUE_EVENT_CHANNEL_ID,
    GREEN_EVENT_CHANNEL_ID,
    EVENT_STAFF_CHANNEL_ID,
    EVENT_ANNOUNCEMENTS_CHANNEL_ID
)

# Mapping for easier looping
EVENT_CHANNELS = {
    "red": RED_EVENT_CHANNEL_ID,
    "blue": BLUE_EVENT_CHANNEL_ID,
    "green": GREEN_EVENT_CHANNEL_ID
}

class ClearChannelView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None) # Persistent view
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
            button.style = discord.ButtonStyle.secondary # Grey fallback
            button.label = "Purge Channel"

    # Define button with a placeholder style; __init__ overrides it
    @discord.ui.button(label="Purge Channel", style=discord.ButtonStyle.secondary, custom_id="purge_event_btn")
    async def purge_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Check Permissions
        user_roles = [r.id for r in interaction.user.roles]
        if not (ADMIN_ROLE_ID in user_roles or EVENT_STAFF_ROLE_ID in user_roles):
            await interaction.response.send_message("❌ You do not have permission to use this.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return

        # 2. Defer
        await interaction.response.defer()

        # 3. Purge
        try:
            deleted = await channel.purge(limit=None)
            count = len(deleted)
        except Exception as e:
            await interaction.followup.send(f"❌ **Error:** Failed to purge channel. Reason: {e}", ephemeral=True)
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
            ephemeral=False
        )
        

class PayoutConfirmView(discord.ui.View):
    def __init__(self, original_msg, matches, interaction_user):
        super().__init__(timeout=60) # Buttons expire after 60 seconds
        self.original_msg = original_msg
        self.matches = matches # List of tuples: [('User_ID', 'Amount'), ...]
        self.interaction_user = interaction_user
        self.processed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the person who ran the command to click
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("❌ This is not your command.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Payout", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processed: return
        self.processed = True
        
        await interaction.response.defer()
        
        processed_log = []
        total_distributed = 0

        # --- EXECUTE PAYOUTS ---
        for user_id_str, amount_str in self.matches:
            user_id = str(user_id_str)
            amount = int(amount_str)

            current_bal = await get_user_balance(user_id)
            await update_user_balance(user_id, current_bal + amount)
            
            processed_log.append(f"<@{user_id}>: +{amount}")
            total_distributed += amount
        
        # Mark original message with a checkmark
        try:
            await self.original_msg.add_reaction("✅")
        except:
            pass

        # Update the confirmation message to show success
        embed = interaction.message.embeds[0]
        embed.title = "✅ Payouts Complete"
        embed.color = discord.Color.green()
        embed.clear_fields()
        embed.add_field(name="Summary", value=f"Distributed **{total_distributed}** tokens to **{len(self.matches)}** users.", inline=False)
        
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


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cleanup_check_task.start()

    def cog_unload(self):
        self.cleanup_check_task.cancel()

    async def has_event_permission(self, interaction: discord.Interaction):
        if isinstance(interaction.user, discord.Member):
            if interaction.user.get_role(ADMIN_ROLE_ID) or interaction.user.get_role(EVENT_STAFF_ROLE_ID):
                return True
        return False

    async def execute_purge(self, interaction: discord.Interaction, channel_id: int, color_name: str):
        # 1. Permission Check
        if not await self.has_event_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied: You need Admin or Event Staff role.", ephemeral=True)
            return

        # 2. Channel Check (Must be in #event-staff)
        if interaction.channel_id != EVENT_STAFF_CHANNEL_ID:
            await interaction.response.send_message(f"❌ You can only use this command in <#{EVENT_STAFF_CHANNEL_ID}>.", ephemeral=True)
            return

        target_channel = self.bot.get_channel(channel_id)
        if not target_channel:
            await interaction.response.send_message(f"❌ Error: Could not find #{color_name}-event channel.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True) 
        
        try:
            deleted = await target_channel.purge(limit=None)
            
            # 3. Send PUBLIC Confirmation
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"🧹 {color_name} Event Cleared",
                    description=f"✅ **Success!** Deleted **{len(deleted)}** messages in {target_channel.mention}.",
                    color=discord.Color.green()
                )
            )
        except Exception as e:
            await interaction.followup.send(f"❌ **Error:** Failed to purge. {e}")

    # --- COMMANDS ---

    @app_commands.command(name="clear-red", description="Purge all messages in the #red-event channel.")
    async def clear_red(self, interaction: discord.Interaction):
        await self.execute_purge(interaction, RED_EVENT_CHANNEL_ID, "Red")

    @app_commands.command(name="clear-blue", description="Purge all messages in the #blue-event channel.")
    async def clear_blue(self, interaction: discord.Interaction):
        await self.execute_purge(interaction, BLUE_EVENT_CHANNEL_ID, "Blue")

    @app_commands.command(name="clear-green", description="Purge all messages in the #green-event channel.")
    async def clear_green(self, interaction: discord.Interaction):
        await self.execute_purge(interaction, GREEN_EVENT_CHANNEL_ID, "Green")

    # --- SCHEDULED TASK (12 AM ET) ---
    
    # ⚠️ FOR TESTING: Change to @tasks.loop(seconds=10)
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=zoneinfo.ZoneInfo("America/New_York")))
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
                            color=discord.Color.orange()
                        )
                        embed.add_field(name="Action Required", value="Discord cannot bulk delete messages >14 days old.\nPlease clear this channel soon.", inline=False)
                        
                        view = ClearChannelView(channel_id)
                        await staff_channel.send(embed=embed, view=view)
                        print(f"⚠️ Sent cleanup alert for #{name}-event")
                    
                    break 
            except Exception as e:
                print(f"Error checking history for #{name}-event: {e}")
    
    @app_commands.command(name="event-rewards", description="ADMIN ONLY: Distribute tokens from an announcement.")
    @app_commands.describe(message_id="The ID of the message in #event-announcements")
    async def event_rewards(self, interaction: discord.Interaction, message_id: str):
        # 1. Permission Check - STRICTLY ADMIN ONLY
        # We access the role directly rather than using the shared helper
        if not interaction.user.get_role(ADMIN_ROLE_ID):
            await interaction.response.send_message("❌ Permission Denied: Only Admins can process rewards.", ephemeral=True)
            return

        # 2. Channel Check
        if interaction.channel_id != EVENT_STAFF_CHANNEL_ID:
             await interaction.response.send_message(f"❌ Please use this command in <#{EVENT_STAFF_CHANNEL_ID}>.", ephemeral=True)
             return

        await interaction.response.defer()

        # 3. Fetch Message from Configured Channel
        ann_channel = self.bot.get_channel(EVENT_ANNOUNCEMENTS_CHANNEL_ID)
        if not ann_channel:
            await interaction.followup.send("❌ Config Error: Announcement channel not found.")
            return

        try:
            target_message = await ann_channel.fetch_message(int(message_id))
        except:
            await interaction.followup.send("❌ Could not find that message ID in the announcements channel.")
            return

        # 4. Check for previous processing
        if any(r.emoji == "✅" and r.me for r in target_message.reactions):
            await interaction.followup.send("⚠️ This message has already been processed (marked with ✅).")
            return

        # 5. Parse Data
        pattern = r'<@!?(\d+)>\s+(\d+)'
        matches = re.findall(pattern, target_message.content)

        if not matches:
            await interaction.followup.send("⚠️ No valid `User Amount` pairs found.\nFormat required: `@User 500`")
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
            color=discord.Color.orange()
        )
        embed.add_field(name="Recipient List", value=preview_text)
        
        view = PayoutConfirmView(target_message, matches, interaction.user)
        await interaction.followup.send(embed=embed, view=view)
        
    @app_commands.command(name="event-staff-help", description="STAFF ONLY: Guide for managing event channels.")
    async def event_staff_help(self, interaction: discord.Interaction):
        # 1. Permission Check
        if not await self.has_event_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied: This command is for Event Staff only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Event Staff Guide",
            description="Reference guide for managing live event channels and automated cleanup tasks.",
            color=discord.Color.blue()
        )

        # --- Channel Management ---
        mgmt_text = (
            f"`/clear-red` - Purge all messages in <#{RED_EVENT_CHANNEL_ID}>\n"
            f"`/clear-blue` - Purge all messages in <#{BLUE_EVENT_CHANNEL_ID}>\n"
            f"`/clear-green` - Purge all messages in <#{GREEN_EVENT_CHANNEL_ID}>\n"
            f"*Note: These commands must be run in <#{EVENT_STAFF_CHANNEL_ID}>.*"
        )
        embed.add_field(name="🧹 Manual Purge Commands", value=mgmt_text, inline=False)

        # --- Automated Cleanup ---
        cleanup_text = (
            "Every day at **12:00 AM ET**, the bot checks for messages older than **7 days**.\n"
            "If a channel is detected as 'stale', a **Cleanup Warning** will be posted here.\n\n"
            "**How to handle alerts:**\n"
            "Click the button on the alert embed to immediately purge that channel. "
            "This keeps channels clean and prevents Discord's 14-day bulk-delete limitation."
        )
        embed.add_field(name="⏲️ Automated Cleanup System", value=cleanup_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Events(bot))