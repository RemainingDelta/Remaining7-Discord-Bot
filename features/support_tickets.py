import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import io
import re

from database.mongo import get_next_support_ticket_number
from features.config import (
    ADMIN_ROLE_ID,
    MODERATOR_ROLE_ID,
    OTHER_TICKET_CHANNEL_ID,
    PRE_TOURNEY_SUPPORT_CHANNEL_ID,
    SUPPORT_ISSUES_CATEGORY_ID,
    SUPPORT_PARTNERSHIP_CATEGORY_ID,
    SUPPORT_SERVER_CATEGORY_ID,
    SUPPORT_STAFF_APPS_CATEGORY_ID,
    SUPPORT_STAFF_APPS_INFO_CHANNEL_ID,
    SUPPORT_TRANSCRIPT_LOG_CHANNEL_ID,
)


TICKET_TYPES = {
    "issues": {
        "label": "Report an Issue",
        "emoji": "🔧",
        "counter_key": "issues",
        "category_id": SUPPORT_ISSUES_CATEGORY_ID,
        "open_message": (
            "**Please state the issue you want to report.**\n\n"
            "Moderators will be with you shortly."
        ),
    },
    "server_support": {
        "label": "Server Support",
        "emoji": "🛡️",
        "counter_key": "server_support",
        "category_id": SUPPORT_SERVER_CATEGORY_ID,
        "open_message": (
            "**Please state what you need support with.**\n\n"
            "Moderators will be with you shortly."
        ),
    },
    "staff_apps": {
        "label": "Staff Application",
        "emoji": "📋",
        "counter_key": "staff_apps",
        "category_id": SUPPORT_STAFF_APPS_CATEGORY_ID,
        "open_message": (
            "**Which position do you want to apply for:**\n"
            "**Tourney Admin** - Run Matcherino tournaments and manage support tickets\n"
            "**Event Staff** - Bring our community together by hosting fun, engaging events\n"
            "~~**Moderator** - Monitor chats, assist members, and enforce server rules fairly~~\n\n"
            "Then please present your reasons for why we should accept you.\n\n"
            "Moderators will be with you shortly."
        ),
    },
    "partnership": {
        "label": "Server Partnership",
        "emoji": "🤝",
        "counter_key": "partnership",
        "category_id": SUPPORT_PARTNERSHIP_CATEGORY_ID,
        "open_message": (
            "Please provide all information about your server and state why you want to partner with Remaining 7.\n\n"
            "Moderators will be with you shortly."
        ),
    },
}


def _support_staff_role_ids() -> set[int]:
    return {
        rid for rid in (ADMIN_ROLE_ID, MODERATOR_ROLE_ID)
        if isinstance(rid, int) and rid > 0
    }


def _support_category_ids() -> set[int]:
    return {
        cid
        for cid in (
            SUPPORT_ISSUES_CATEGORY_ID,
            SUPPORT_SERVER_CATEGORY_ID,
            SUPPORT_STAFF_APPS_CATEGORY_ID,
            SUPPORT_PARTNERSHIP_CATEGORY_ID,
        )
        if isinstance(cid, int) and cid > 0
    }


def _is_staff(member: discord.abc.User | discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    allowed = _support_staff_role_ids()
    return any(role.id in allowed for role in member.roles)


def _extract_opener_id(topic: str | None) -> int | None:
    if not topic:
        return None
    for part in topic.split("|"):
        key, _, value = part.partition(":")
        if key == "support-opener":
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


def _is_support_ticket_channel(channel: discord.abc.GuildChannel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    return channel.category_id in _support_category_ids() and "ticket-" in channel.name


def _set_remaining7_footer(embed: discord.Embed, bot_user: discord.abc.User | None) -> None:
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


async def close_support_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
) -> bool:
    if not _is_staff(actor):
        return False
    if not _is_support_ticket_channel(channel):
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
        reason=f"Support ticket closed by {actor}",
    )

    await channel.send(
        f"Ticket closed by {actor.name}.",
        view=SupportClosedTicketView(),
    )
    return True


async def reopen_support_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
) -> bool:
    if not _is_staff(actor):
        return False
    if not _is_support_ticket_channel(channel):
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
        reason=f"Support ticket reopened by {actor}",
    )

    await channel.send(f"✅ Ticket reopened by {actor.mention}.")
    return True


async def delete_support_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
    bot: commands.Bot,
) -> bool:
    if not _is_staff(actor):
        return False
    if not _is_support_ticket_channel(channel):
        return False

    transcript_text = await _build_transcript_text(channel)
    transcript_bytes = transcript_text.encode("utf-8")
    filename = f"{channel.name}_transcript.txt"

    opener_id = _extract_opener_id(channel.topic)
    if opener_id is not None:
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
                f"🗑️ Support ticket deleted\n"
                f"Channel: **{channel.name}**\n"
                f"Deleted by: {actor.mention}"
            ),
            file=log_file,
        )

    await channel.delete(reason=f"Support ticket deleted by {actor}")
    return True


async def close_support_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to close this ticket.")
        return

    ok = await close_support_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply("This command can only be used inside an active support ticket channel.")


async def reopen_support_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to reopen this ticket.")
        return

    ok = await reopen_support_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply("This command can only be used inside a support ticket channel.")


async def delete_support_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to delete this ticket.")
        return

    ok = await delete_support_ticket_channel(ctx.channel, ctx.author, ctx.bot)
    if not ok:
        await ctx.reply("This command can only be used inside a support ticket channel.")


class SupportTicketSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        options = []
        for ticket_type, cfg in TICKET_TYPES.items():
            options.append(
                discord.SelectOption(
                    label=cfg["label"],
                    value=ticket_type,
                    emoji=cfg["emoji"],
                )
            )

        super().__init__(
            placeholder="Make a selection",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="support_ticket_type_select",
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return

        selected = self.values[0]
        cfg = TICKET_TYPES[selected]
        category_id = cfg["category_id"]

        if not isinstance(category_id, int) or category_id <= 0:
            await interaction.response.send_message(
                "This ticket category is not configured yet. Ask an admin to set the category IDs in config/.env.",
                ephemeral=True,
            )
            return

        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "Configured category channel was not found. Please contact an admin.",
                ephemeral=True,
            )
            return

        # Rate-limit: one open ticket per type per user (closed/deleted tickets don't block)
        user_id = interaction.user.id
        for ch in category.channels:
            if isinstance(ch, discord.TextChannel) and ch.topic:
                if f"support-opener:{user_id}" in ch.topic and f"type:{selected}" in ch.topic:
                    if "「❗」" in ch.name:  # only block if still open
                        await interaction.response.send_message(
                            f"You already have an open **{cfg['label']}** ticket: {ch.mention}\n"
                            "Please use your existing ticket or wait for it to be closed.",
                            ephemeral=True,
                        )
                        return

        ticket_number = await get_next_support_ticket_number(cfg["counter_key"])
        channel_name = f"「❗」ticket-{ticket_number:03d}"

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                use_application_commands=True,
            ),
        }

        for role_id in _support_staff_role_ids():
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
            reason=f"Support ticket ({selected}) from {interaction.user}",
        )
        await channel.edit(topic=f"support-opener:{interaction.user.id}|type:{selected}", reason="Store support opener")

        await interaction.response.send_message(
            f"Your ticket has been created: {channel.mention}",
            ephemeral=True,
        )

        await channel.send(f"Welcome {interaction.user.mention}")
        prompt_embed = discord.Embed(
            title=cfg["label"],
            description=cfg["open_message"],
            color=discord.Color.green(),
        )
        _set_remaining7_footer(prompt_embed, interaction.client.user)
        await channel.send(embed=prompt_embed)


class SupportTicketPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.add_item(SupportTicketSelect(bot))


class SupportClosedTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Delete Ticket", style=discord.ButtonStyle.danger, custom_id="support_delete_ticket")
    async def delete_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Only server members can use this.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This only works in support ticket channels.", ephemeral=True)
            return

        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.NotFound:
            # Interaction expired; continue with deletion flow anyway.
            deferred = False

        ok = await delete_support_ticket_channel(interaction.channel, interaction.user, interaction.client)
        if ok:
            # Channel is deleted — any followup will fail with 10003 Unknown Channel.
            # The disappearing channel is confirmation enough; suppress silently.
            return
        try:
            if deferred or interaction.response.is_done():
                await interaction.followup.send("This button can only be used in support tickets by staff.", ephemeral=True)
            else:
                await interaction.response.send_message("This button can only be used in support tickets by staff.", ephemeral=True)
        except discord.NotFound:
            pass

    @discord.ui.button(label="Reopen Ticket", style=discord.ButtonStyle.success, custom_id="support_reopen_ticket")
    async def reopen_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Only server members can use this.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This only works in support ticket channels.", ephemeral=True)
            return

        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.NotFound:
            deferred = False

        ok = await reopen_support_ticket_channel(interaction.channel, interaction.user)
        if not ok:
            try:
                if deferred or interaction.response.is_done():
                    await interaction.followup.send("This button can only be used in support tickets by staff.", ephemeral=True)
                else:
                    await interaction.response.send_message("This button can only be used in support tickets by staff.", ephemeral=True)
            except discord.NotFound:
                pass
            return
        try:
            if deferred or interaction.response.is_done():
                await interaction.followup.send("Ticket reopened.", ephemeral=True)
            else:
                await interaction.response.send_message("Ticket reopened.", ephemeral=True)
        except discord.NotFound:
            # Reopen already completed; ignore expired interaction response.
            pass


class SupportTickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(SupportTicketPanelView(self.bot))
        self.bot.add_view(SupportClosedTicketView())

    @app_commands.command(name="support-panel", description="Post the master support ticket panel.")
    async def support_panel(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        allowed_roles = _support_staff_role_ids()
        if not any(role.id in allowed_roles for role in interaction.user.roles):
            await interaction.response.send_message("You do not have permission to post this panel.", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a text channel.", ephemeral=True)
            return

        if channel.id != OTHER_TICKET_CHANNEL_ID:
            target = f"<#{OTHER_TICKET_CHANNEL_ID}>" if OTHER_TICKET_CHANNEL_ID else "the configured support panel channel"
            await interaction.response.send_message(
                f"Please run this command in {target}.",
                ephemeral=True,
            )
            return

        staff_info = f"<#{SUPPORT_STAFF_APPS_INFO_CHANNEL_ID}>" if isinstance(SUPPORT_STAFF_APPS_INFO_CHANNEL_ID, int) else "the info channel"
        tourney_ch = f"<#{PRE_TOURNEY_SUPPORT_CHANNEL_ID}>" if isinstance(PRE_TOURNEY_SUPPORT_CHANNEL_ID, int) else "the tourney support channel"
        embed = discord.Embed(
            title="Support Tickets",
            description=(
                "Select a category below to open a private ticket channel.\n\n"
                "**Available categories:**\n"
                "🔧 **Report an Issue** — Bugs, rule-break reports, or technical problems\n"
                "🛡️ **Server Support** — General assistance for the server\n"
                f"📋 **Staff Application** — Apply for **Tourney Admin** or **Event Staff** (**No Moderator** spots currently open). More info: {staff_info}\n"
                "🤝 **Server Partnership** — Propose a partnership with your server details and goals\n\n"
                "⚠️ **Tourney tickets opened here will not be prioritised and may go unanswered.**\n"
                f"For tourney-related concerns, go to {tourney_ch}"
            ),
            color=discord.Color.green(),
        )
        _set_remaining7_footer(embed, interaction.client.user)

        await interaction.response.send_message(embed=embed, view=SupportTicketPanelView(self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(SupportTickets(bot))
