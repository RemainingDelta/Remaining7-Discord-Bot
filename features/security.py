import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta, datetime
import asyncio

from database.mongo import add_hacked_user, get_hacked_users, remove_hacked_user
# UPDATE: Added the new variables to the import
from features.config import ADMIN_ROLE_ID, LOG_CHANNEL_ID, MODERATOR_ROLE_ID, MODERATOR_LOGS_CHANNEL_ID

class Security(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- HELPER: Checks permissions (Admins OR Mods) ---
    async def has_security_permission(self, source):
        # 'source' can be Interaction or Context
        user = source.user if isinstance(source, discord.Interaction) else source.author
        
        if isinstance(user, discord.Member):
            is_admin = user.get_role(ADMIN_ROLE_ID) is not None
            is_mod = user.get_role(MODERATOR_ROLE_ID) is not None
            return is_admin or is_mod
        return False

    # --- CORE LOGIC: The shared hacked/purge process ---
    async def _execute_hacked_action(self, guild, target_user, moderator, days_to_clean=7):
        """
        Shared logic that performs the timeout, DB update, and message purge.
        """
        # 1. Prevent targetting admins/mods or self
        if target_user.top_role >= moderator.top_role:
            return discord.Embed(description="❌ You cannot target someone with equal or higher roles.", color=discord.Color.red())

        # 2. Timeout the User (7 Days)
        try:
            duration = timedelta(days=7)
            await target_user.timeout(duration, reason="Security: User Compromised/Hacked")
            timeout_status = "✅ User Timed Out (7 Days)"
        except Exception as e:
            timeout_status = f"⚠️ Failed to Timeout: {e}"

        # 3. Add to Database
        await add_hacked_user(str(target_user.id))

        # 4. Global Message Purge
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_clean)
        total_deleted = 0
        channels_checked = 0
        
        # COMBINE LISTS: Convert all to list() first to avoid SequenceProxy errors
        all_channels = list(guild.text_channels) + list(guild.voice_channels) + list(guild.threads)
        
        for channel in all_channels:
            # Skip channels where bot lacks permission to Manage Messages
            perms = channel.permissions_for(guild.me)
            if not perms.manage_messages or not perms.read_message_history:
                continue

            try:
                # Purge messages from this user specifically
                deleted = await channel.purge(
                    limit=None, 
                    after=cutoff_date, 
                    check=lambda m: m.author.id == target_user.id
                )
                if len(deleted) > 0:
                    total_deleted += len(deleted)
            except Exception:
                pass 
            
            channels_checked += 1
            await asyncio.sleep(0.1) 

        # 5. Build Result Embed
        embed = discord.Embed(
            title="🚨 User Flagged as Hacked",
            description=f"**Target:** {target_user.mention} (`{target_user.id}`)\n**Action:** 7-Day Timeout & Message Purge",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="Status", value=timeout_status, inline=False)
        embed.add_field(name="Cleanup Stats", value=f"🗑️ Deleted **{total_deleted} messages** across **{channels_checked} channels** (Past {days_to_clean} days).", inline=False)
        embed.add_field(name="Next Step", value="User added to Hacked Database. Use `/unhacked` when recovered.", inline=False)
        
        return embed

    # --- HELPER: Send Logs to Multiple Channels ---
    async def _send_security_logs(self, embed):
        # 1. Admin Log
        admin_log = self.bot.get_channel(LOG_CHANNEL_ID)
        if admin_log: 
            await admin_log.send(embed=embed)
        
        # 2. Mod Log (Avoid sending twice if IDs are the same)
        if MODERATOR_LOGS_CHANNEL_ID != LOG_CHANNEL_ID:
            mod_log = self.bot.get_channel(MODERATOR_LOGS_CHANNEL_ID)
            if mod_log: 
                await mod_log.send(embed=embed)

    # --- COMMAND 1: Slash Command (/hacked) ---
    @app_commands.command(name="hacked", description="MOD/ADMIN: Flag user as hacked, timeout them, and delete messages.")
    @app_commands.describe(user="The hacked user", days_to_clean="Days of messages to delete (default 7)")
    async def hacked_slash(self, interaction: discord.Interaction, user: discord.Member, days_to_clean: int = 7):
        if not await self.has_security_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied.", ephemeral=True)
            return

        await interaction.response.defer()
        result_embed = await self._execute_hacked_action(interaction.guild, user, interaction.user, days_to_clean)
        await interaction.followup.send(embed=result_embed)
        
        # Log to both channels
        await self._send_security_logs(result_embed)

    # --- COMMAND 2: Text Command (!hacked) ---
    @commands.command(name="hacked")
    async def hacked_text(self, ctx):
        """
        Usage: Reply to a suspicious message with !hacked
        """
        if not await self.has_security_permission(ctx):
            return

        if not ctx.message.reference:
            await ctx.send("❌ Reply to a message with `!hacked` to flag that user.")
            return

        replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        target_user = replied_message.author

        if isinstance(target_user, discord.User):
            try:
                target_user = await ctx.guild.fetch_member(target_user.id)
            except:
                await ctx.send("❌ User is no longer in the server.")
                return

        status_msg = await ctx.send("⏳ Processing Hacked Protocol...")
        result_embed = await self._execute_hacked_action(ctx.guild, target_user, ctx.author)
        await status_msg.edit(content=None, embed=result_embed)

        # Log to both channels
        await self._send_security_logs(result_embed)

    # --- OTHER COMMANDS ---

    @app_commands.command(name="unhacked", description="MOD/ADMIN: Mark user as recovered (Remove Timeout & Flag).")
    async def unhacked(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.has_security_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied.", ephemeral=True)
            return

        try:
            await user.timeout(None, reason="Account Recovered") 
            await remove_hacked_user(str(user.id))
            await interaction.response.send_message(f"✅ {user.mention} has been marked as safe/unhacked.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}")

    @app_commands.command(name="hacked-list", description="MOD/ADMIN: View all currently hacked users.")
    async def hackedlist(self, interaction: discord.Interaction):
        if not await self.has_security_permission(interaction):
            await interaction.response.send_message("❌ Permission Denied.", ephemeral=True)
            return
        
        await interaction.response.defer()
        users = await get_hacked_users()
        
        if not users:
            await interaction.followup.send("✅ No users are currently flagged as hacked.")
            return
            
        embed = discord.Embed(title="🚨 Hacked Users List", color=discord.Color.dark_red())
        description_lines = []
        for u in users:
            user_id = u['_id']
            reason = u.get('reason', 'No reason provided')
            time_str = u.get('timestamp', datetime.utcnow()).strftime('%Y-%m-%d')
            description_lines.append(f"• <@{user_id}> (`{user_id}`)\n   Reason: *{reason}* ({time_str})")
            
        full_text = "\n".join(description_lines)
        if len(full_text) > 4000: full_text = full_text[:3900] + "..."
            
        embed.description = full_text
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Security(bot))