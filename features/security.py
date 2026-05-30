import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta, datetime, timezone
from math import ceil
import asyncio

from database.mongo import add_hacked_user, get_hacked_users, remove_hacked_user

# UPDATE: Added the new variables to the import
from features.config import ADMIN_ROLE_ID, MODERATOR_ROLE_ID, MODERATOR_LOGS_CHANNEL_ID


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
    async def _execute_hacked_action(self, guild, target_user, moderator):
        """
        Shared logic that performs the timeout, DB update, and message purge.
        """
        # 1. Prevent targetting admins/mods or self
        if target_user.top_role >= moderator.top_role:
            return discord.Embed(
                description="❌ You cannot target someone with equal or higher roles.",
                color=discord.Color.red(),
            )

        # 2. Timeout the User (7 Days)
        try:
            duration = timedelta(days=7)
            await target_user.timeout(
                duration, reason="Security: User Compromised/Hacked"
            )
            timeout_status = "✅ User Timed Out (7 Days)"
        except Exception as e:
            timeout_status = f"⚠️ Failed to Timeout: {e}"

        # 3. Add to Database
        await add_hacked_user(str(target_user.id))

        # 4. DM the flagged user
        try:
            dm_embed = discord.Embed(
                title="🚨 Account Flagged as Compromised",
                description=(
                    "Your account has been flagged as **hacked** on the **Remaining 7** server.\n\n"
                    "You have been **timed out for 1 week** as a security measure.\n\n"
                    "If you recover your account, please message <@408419700729708545> to be untimed out."
                ),
                color=discord.Color.dark_red(),
            )
            await target_user.send(embed=dm_embed)
        except Exception as e:
            print(f"Failed to DM hacked user {target_user.id}: {e}")

        # 5. Global Message Purge
        cutoff_date = datetime.utcnow() - timedelta(hours=12)
        total_deleted = 0
        channels_checked = 0
        earliest_message_time = None

        # COMBINE LISTS: Convert all to list() first to avoid SequenceProxy errors
        all_channels = (
            list(guild.text_channels) + list(guild.voice_channels) + list(guild.threads)
        )

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
                    check=lambda m: m.author.id == target_user.id,
                )
                if len(deleted) > 0:
                    total_deleted += len(deleted)
                    channel_earliest = min(msg.created_at for msg in deleted)
                    if (
                        earliest_message_time is None
                        or channel_earliest < earliest_message_time
                    ):
                        earliest_message_time = channel_earliest
            except Exception:
                pass

            channels_checked += 1
            await asyncio.sleep(0.1)

        # 6. Calculate response time
        if earliest_message_time is not None:
            response_delta = datetime.now(timezone.utc) - earliest_message_time
            total_seconds = int(response_delta.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes = remainder // 60
            response_time_str = f"{hours:02d}:{minutes:02d}"
        else:
            response_time_str = "N/A (no messages found)"

        # 7. Build Result Embed
        embed = discord.Embed(
            title="🚨 User Flagged as Hacked",
            description=(
                f"**Target:** {target_user.mention} (`{target_user.id}`)\n"
                f"**Moderator:** {moderator.mention}\n"
                f"**Action:** 7-Day Timeout & Message Purge"
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Status", value=timeout_status, inline=False)
        embed.add_field(
            name="Cleanup Stats",
            value=f"🗑️ Deleted **{total_deleted} messages** across **{channels_checked} channels** (Past 12 hours).",
            inline=False,
        )
        embed.add_field(
            name="Response Time",
            value=f"⏱️ {response_time_str}",
            inline=False,
        )
        embed.add_field(
            name="Next Step",
            value="User added to Hacked Database. Use `/unhacked` when recovered.",
            inline=False,
        )

        return embed

    # --- HELPER: Send Logs to Moderator Logs Channels ---
    async def _send_security_logs(self, embed):
        # Only send to the dedicated Moderator Logs Channel
        mod_log = self.bot.get_channel(MODERATOR_LOGS_CHANNEL_ID)
        if mod_log:
            await mod_log.send(embed=embed)

    # --- COMMAND 1: Slash Command (/hacked) ---
    @app_commands.command(
        name="hacked",
        description="MOD/ADMIN: Flag user as hacked, timeout them, and delete messages.",
    )
    @app_commands.describe(user="The hacked user")
    async def hacked_slash(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        if not await self.has_security_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied.", ephemeral=True
            )
            return

        await interaction.response.defer()
        result_embed = await self._execute_hacked_action(
            interaction.guild, user, interaction.user
        )
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

        if ctx.message.content.strip() != "!hacked":
            return

        if not ctx.message.reference:
            await ctx.send("❌ Reply to a message with `!hacked` to flag that user.")
            return

        replied_message = await ctx.channel.fetch_message(
            ctx.message.reference.message_id
        )
        target_user = replied_message.author

        if isinstance(target_user, discord.User):
            try:
                target_user = await ctx.guild.fetch_member(target_user.id)
            except Exception:
                await ctx.send("❌ User is no longer in the server.")
                return

        status_msg = await ctx.send("⏳ Processing Hacked Protocol...")
        result_embed = await self._execute_hacked_action(
            ctx.guild, target_user, ctx.author
        )
        await status_msg.edit(content=None, embed=result_embed)

        # Log to both channels
        await self._send_security_logs(result_embed)

    # --- OTHER COMMANDS ---

    @app_commands.command(
        name="unhacked",
        description="MOD/ADMIN: Mark user as recovered (Remove Timeout & Flag).",
    )
    async def unhacked(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.has_security_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied.", ephemeral=True
            )
            return

        try:
            await user.timeout(None, reason="Account Recovered")
            await remove_hacked_user(str(user.id))
            await interaction.response.send_message(
                f"✅ {user.mention} has been marked as safe/unhacked."
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}")

    @app_commands.command(
        name="hacked-list", description="MOD/ADMIN: View all currently hacked users."
    )
    async def hackedlist(self, interaction: discord.Interaction):
        if not await self.has_security_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission Denied.", ephemeral=True
            )
            return

        await interaction.response.defer()
        users = await get_hacked_users()

        if not users:
            await interaction.followup.send(
                "✅ No users are currently flagged as hacked."
            )
            return

        view = HackedListView(users, interaction.user)
        await interaction.followup.send(embed=view.create_embed(), view=view)


class HackedListView(discord.ui.View):
    def __init__(self, users: list, author: discord.User):
        super().__init__(timeout=300)
        self.users = sorted(
            users, key=lambda u: u.get("timestamp", datetime.min), reverse=True
        )
        self.author = author
        self.per_page = 10
        self.current_page = 0
        self.total_pages = ceil(len(users) / self.per_page)
        self.update_buttons()

    def create_embed(self) -> discord.Embed:
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_users = self.users[start:end]

        entries = []
        for u in page_users:
            user_id = u["_id"]
            reason = u.get("reason", "No reason provided")
            time_str = u.get("timestamp", datetime.utcnow()).strftime("%Y-%m-%d")
            entries.append(
                f"<@{user_id}> (`{user_id}`)\nReason: *{reason}* ({time_str})"
            )

        embed = discord.Embed(
            title="🚨 Hacked Users List",
            description="\n\n".join(entries),
            color=discord.Color.dark_red(),
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")
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
        if interaction.user.id != self.author.id:
            await interaction.response.defer()
            return
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.blurple)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.author.id:
            await interaction.response.defer()
            return
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


async def setup(bot):
    await bot.add_cog(Security(bot))
