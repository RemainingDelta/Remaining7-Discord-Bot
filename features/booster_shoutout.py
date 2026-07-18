import discord
from discord.ext import commands
import asyncio
import io
import re
from datetime import datetime

from database.mongo import (
    get_booster_shoutout_month,
    get_next_support_ticket_number,
    set_booster_shoutout_month,
)
from features.config import (
    ADMIN_ROLE_ID,
    BOOSTER_SHOUTOUT_CATEGORY_ID,
    MODERATOR_ROLE_ID,
    SUPPORT_TRANSCRIPT_LOG_CHANNEL_ID,
)


def _staff_role_ids() -> set[int]:
    return {
        rid
        for rid in (ADMIN_ROLE_ID, MODERATOR_ROLE_ID)
        if isinstance(rid, int) and rid > 0
    }


def _is_staff(member: discord.abc.User | discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    allowed = _staff_role_ids()
    return any(role.id in allowed for role in member.roles)


def _is_new_boost(
    before_premium: datetime | None, after_premium: datetime | None
) -> bool:
    """A member started boosting when premium_since goes from None to a datetime."""
    return before_premium is None and after_premium is not None


def _current_month_key() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _extract_opener_id(topic: str | None) -> int | None:
    if not topic:
        return None
    for part in topic.split("|"):
        key, _, value = part.partition(":")
        if key == "booster-opener":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _strip_status_prefix(channel_name: str) -> str:
    return re.sub(r"^「[^」]+」", "", channel_name).strip()


def _active_ticket_name(channel_name: str) -> str:
    return f"「❗」{_strip_status_prefix(channel_name)}"


def _closed_ticket_name(channel_name: str) -> str:
    return f"「👍」{_strip_status_prefix(channel_name)}"


def _is_booster_shoutout_ticket_channel(channel: discord.abc.GuildChannel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if (
        not isinstance(BOOSTER_SHOUTOUT_CATEGORY_ID, int)
        or BOOSTER_SHOUTOUT_CATEGORY_ID <= 0
    ):
        return False
    return (
        channel.category_id == BOOSTER_SHOUTOUT_CATEGORY_ID
        and "shoutout-" in channel.name
    )


def _set_remaining7_footer(
    embed: discord.Embed, bot_user: discord.abc.User | None
) -> None:
    icon_url = None
    if bot_user is not None:
        icon_url = bot_user.display_avatar.url
    embed.set_footer(text="Remaining 7 Bot", icon_url=icon_url)


async def _try_rename_channel(
    channel: discord.TextChannel,
    new_name: str,
    reason: str,
    timeout_seconds: float = 3.0,
) -> bool:
    """
    Try to rename quickly; if API is rate-limited or delayed, skip rename.
    Permissions are higher priority than cosmetic rename state.
    """
    if channel.name == new_name:
        return True

    try:
        await asyncio.wait_for(
            channel.edit(name=new_name, reason=reason),
            timeout=timeout_seconds,
        )
        return True
    except (asyncio.TimeoutError, discord.HTTPException):
        return False


async def _build_transcript_text(channel: discord.TextChannel) -> str:
    opener_id = _extract_opener_id(channel.topic)
    lines: list[str] = [
        f"Channel: {channel.name}",
        f"Opener ID: {opener_id or 'Unknown'}",
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

    if len(lines) <= 3:
        lines.append("No messages in this ticket.")

    return "\n".join(lines)


async def create_booster_shoutout_ticket(
    guild: discord.Guild,
    member: discord.Member,
    bot_user: discord.abc.User | None,
) -> discord.TextChannel | None:
    if (
        not isinstance(BOOSTER_SHOUTOUT_CATEGORY_ID, int)
        or BOOSTER_SHOUTOUT_CATEGORY_ID <= 0
    ):
        print("⚠️ Booster shoutout category ID is not configured.")
        return None

    category = guild.get_channel(BOOSTER_SHOUTOUT_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        print(
            f"⚠️ Booster shoutout category {BOOSTER_SHOUTOUT_CATEGORY_ID} "
            f"not found in guild {guild.id}."
        )
        return None

    ticket_number = await get_next_support_ticket_number("booster_shoutout")
    channel_name = f"「❗」shoutout-{ticket_number:03d}"

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            use_application_commands=True,
        ),
    }

    for role_id in _staff_role_ids():
        role = guild.get_role(role_id)
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                use_application_commands=True,
            )

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"Booster shoutout ticket for {member}",
    )
    await channel.edit(
        topic=f"booster-opener:{member.id}|type:booster_shoutout",
        reason="Store booster shoutout opener",
    )

    await channel.send(f"Welcome {member.mention}")
    embed = discord.Embed(
        title="Server Booster Shoutout",
        description=(
            "Thank you for boosting **Remaining 7**! 💜\n\n"
            "Write the message you'd like featured in the announcements "
            "channel here. Staff will review it and post a link to your "
            "message in announcements — Discord shows it with your name "
            "and avatar.\n\n"
            "If you'd rather not have a shoutout, just say so and staff "
            "will close this ticket."
        ),
        color=discord.Color.green(),
    )
    _set_remaining7_footer(embed, bot_user)
    await channel.send(embed=embed)
    return channel


async def close_booster_shoutout_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
) -> bool:
    if not _is_staff(actor):
        return False
    if not _is_booster_shoutout_ticket_channel(channel):
        return False

    guild = channel.guild
    opener_id = _extract_opener_id(channel.topic)
    if opener_id is not None:
        opener = guild.get_member(opener_id)
        if opener is not None and not _is_staff(opener):
            await channel.set_permissions(
                opener,
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                use_application_commands=True,
            )

    await _try_rename_channel(
        channel,
        _closed_ticket_name(channel.name),
        reason=f"Booster shoutout ticket closed by {actor}",
    )

    await channel.send(
        f"Ticket closed by {actor.name}.",
        view=BoosterShoutoutClosedView(),
    )
    return True


async def reopen_booster_shoutout_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
) -> bool:
    if not _is_staff(actor):
        return False
    if not _is_booster_shoutout_ticket_channel(channel):
        return False

    guild = channel.guild
    opener_id = _extract_opener_id(channel.topic)
    if opener_id is not None:
        opener = guild.get_member(opener_id)
        if opener is not None:
            await channel.set_permissions(
                opener,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                use_application_commands=True,
            )

    await _try_rename_channel(
        channel,
        _active_ticket_name(channel.name),
        reason=f"Booster shoutout ticket reopened by {actor}",
    )

    await channel.send(f"✅ Ticket reopened by {actor.mention}.")
    return True


async def delete_booster_shoutout_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
    bot: commands.Bot,
) -> bool:
    if not _is_staff(actor):
        return False
    if not _is_booster_shoutout_ticket_channel(channel):
        return False

    transcript_text = await _build_transcript_text(channel)
    transcript_bytes = transcript_text.encode("utf-8")
    filename = f"{channel.name}_transcript.txt"

    opener_id = _extract_opener_id(channel.topic)
    opener_display = "unknown"
    if opener_id is not None:
        opener_display = f"<@{opener_id}>"
        user = bot.get_user(opener_id)
        if user is None:
            try:
                user = await bot.fetch_user(opener_id)
            except Exception:
                user = None
        if user is not None:
            try:
                dm_file = discord.File(io.BytesIO(transcript_bytes), filename=filename)
                await user.send(
                    content=f"Here is the transcript for your closed ticket in **{channel.guild.name}**.",
                    file=dm_file,
                )
            except discord.Forbidden:
                pass

    log_channel = (
        channel.guild.get_channel(SUPPORT_TRANSCRIPT_LOG_CHANNEL_ID)
        if isinstance(SUPPORT_TRANSCRIPT_LOG_CHANNEL_ID, int)
        else None
    )
    if isinstance(log_channel, discord.TextChannel):
        log_file = discord.File(io.BytesIO(transcript_bytes), filename=filename)
        await log_channel.send(
            content=(
                f"📝 Transcript for ticket **#{channel.name}** "
                f"deleted by **{actor.name}** (opener: {opener_display})."
            ),
            file=log_file,
        )

    await channel.delete(reason=f"Booster shoutout ticket deleted by {actor}")
    return True


async def close_booster_shoutout_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to close this ticket.")
        return

    ok = await close_booster_shoutout_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply(
            "This command can only be used inside a booster shoutout ticket channel."
        )


async def reopen_booster_shoutout_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to reopen this ticket.")
        return

    ok = await reopen_booster_shoutout_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply(
            "This command can only be used inside a booster shoutout ticket channel."
        )


async def delete_booster_shoutout_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to delete this ticket.")
        return

    ok = await delete_booster_shoutout_ticket_channel(ctx.channel, ctx.author, ctx.bot)
    if not ok:
        await ctx.reply(
            "This command can only be used inside a booster shoutout ticket channel."
        )


class BoosterShoutoutClosedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Delete Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="booster_shoutout_delete_ticket",
    )
    async def delete_ticket_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Only server members can use this.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This only works in booster shoutout ticket channels.", ephemeral=True
            )
            return

        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.NotFound:
            # Interaction expired; continue with deletion flow anyway.
            deferred = False

        ok = await delete_booster_shoutout_ticket_channel(
            interaction.channel, interaction.user, interaction.client
        )
        if ok:
            # Channel is deleted — any followup will fail with 10003 Unknown Channel.
            # The disappearing channel is confirmation enough; suppress silently.
            return
        try:
            if deferred or interaction.response.is_done():
                await interaction.followup.send(
                    "This button can only be used in booster shoutout tickets by staff.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "This button can only be used in booster shoutout tickets by staff.",
                    ephemeral=True,
                )
        except discord.NotFound:
            pass

    @discord.ui.button(
        label="Reopen Ticket",
        style=discord.ButtonStyle.success,
        custom_id="booster_shoutout_reopen_ticket",
    )
    async def reopen_ticket_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Only server members can use this.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This only works in booster shoutout ticket channels.", ephemeral=True
            )
            return

        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.NotFound:
            deferred = False

        ok = await reopen_booster_shoutout_ticket_channel(
            interaction.channel, interaction.user
        )
        if not ok:
            try:
                if deferred or interaction.response.is_done():
                    await interaction.followup.send(
                        "This button can only be used in booster shoutout tickets by staff.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "This button can only be used in booster shoutout tickets by staff.",
                        ephemeral=True,
                    )
            except discord.NotFound:
                pass
            return
        try:
            if deferred or interaction.response.is_done():
                await interaction.followup.send("Ticket reopened.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "Ticket reopened.", ephemeral=True
                )
        except discord.NotFound:
            # Reopen already completed; ignore expired interaction response.
            pass


class BoosterShoutout(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(BoosterShoutoutClosedView())

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not _is_new_boost(before.premium_since, after.premium_since):
            return

        month_key = _current_month_key()
        user_id = str(after.id)
        if await get_booster_shoutout_month(user_id) == month_key:
            return

        try:
            channel = await create_booster_shoutout_ticket(
                after.guild, after, self.bot.user
            )
        except discord.HTTPException as e:
            print(f"⚠️ Failed to create booster shoutout ticket for {after.id}: {e}")
            return

        # Marker is set only after successful creation so a failed attempt
        # (e.g. category full) can retry on a later boost this month.
        if channel is not None:
            await set_booster_shoutout_month(user_id, month_key)


async def setup(bot: commands.Bot):
    await bot.add_cog(BoosterShoutout(bot))
