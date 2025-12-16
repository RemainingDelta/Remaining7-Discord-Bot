import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, time
import zoneinfo # Standard in Python 3.9+

from features.config import (
    ADMIN_ROLE_ID, 
    EVENT_STAFF_ROLE_ID,
    RED_EVENT_CHANNEL_ID,
    BLUE_EVENT_CHANNEL_ID,
    GREEN_EVENT_CHANNEL_ID,
    EVENT_STAFF_CHANNEL_ID
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

async def setup(bot):
    await bot.add_cog(Events(bot))