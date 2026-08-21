"""Event ticketing system.

Lets members open a private channel to submit their answer for an event, gives
event staff access to every open ticket, and on deletion saves a transcript to a
dedicated event transcript channel while DMing a copy to the opener.

Modelled on ``features/support_tickets.py`` (self-contained cog, close-in-place,
shared prefix-command router) rather than the tourney system, which moves channels
between categories. Namespaced ``event_ticket*`` to avoid colliding with
``features/event.py`` (the token-reward events cog).
"""

import asyncio
import io
import re

import discord
from discord import app_commands
from discord.ext import commands

from features.config import (
    EVENT_STAFF_ROLE_ID,
    EVENT_TICKET_CATEGORY_ID,
    EVENT_TICKET_PANEL_CHANNEL_ID,
    EVENT_TICKET_TRANSCRIPT_CHANNEL_ID,
)

# Leave headroom under Discord's 100-char channel-name limit for the
# "「❗」event-" prefix.
_MAX_USERNAME_LEN = 90


def _event_staff_role_ids() -> set[int]:
    return {rid for rid in (EVENT_STAFF_ROLE_ID,) if isinstance(rid, int) and rid > 0}


def _is_event_staff(member: discord.abc.User | discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    allowed = _event_staff_role_ids()
    return any(role.id in allowed for role in member.roles)


def _sanitize_username(username: str, user_id: int) -> str:
    """Turn a display name into a valid Discord channel-name fragment.

    Lowercases, converts whitespace to hyphens, drops anything outside
    ``[a-z0-9-]``, collapses/trims hyphens and truncates. Falls back to the
    numeric user id when nothing usable remains.
    """
    lowered = (username or "").lower()
    hyphenated = re.sub(r"\s+", "-", lowered)
    cleaned = re.sub(r"[^a-z0-9-]", "", hyphenated)
    collapsed = re.sub(r"-+", "-", cleaned).strip("-")
    truncated = collapsed[:_MAX_USERNAME_LEN].strip("-")
    return truncated or str(user_id)


def _extract_opener_id(topic: str | None) -> int | None:
    if not topic:
        return None
    for part in topic.split("|"):
        key, _, value = part.partition(":")
        if key == "event-opener":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _strip_status_prefix(channel_name: str) -> str:
    return re.sub(r"^「[^」]+」", "", channel_name).strip()


def _active_name(channel_name: str) -> str:
    return f"「❗」{_strip_status_prefix(channel_name)}"


def _closed_name(channel_name: str) -> str:
    return f"「👍」{_strip_status_prefix(channel_name)}"


def is_event_ticket_channel(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if not isinstance(EVENT_TICKET_CATEGORY_ID, int) or EVENT_TICKET_CATEGORY_ID <= 0:
        return False
    return channel.category_id == EVENT_TICKET_CATEGORY_ID


def _find_existing_ticket(
    category: discord.CategoryChannel, user_id: int
) -> discord.TextChannel | None:
    """Return the caller's existing event ticket in this category, if any."""
    for ch in category.channels:
        if isinstance(ch, discord.TextChannel) and ch.topic:
            if f"event-opener:{user_id}" in ch.topic:
                return ch
    return None


def _set_remaining7_footer(
    embed: discord.Embed, bot_user: discord.abc.User | None
) -> None:
    icon_url = bot_user.display_avatar.url if bot_user is not None else None
    embed.set_footer(text="Remaining 7 Bot", icon_url=icon_url)


async def _try_rename_channel(
    channel: discord.TextChannel,
    new_name: str,
    reason: str,
    timeout_seconds: float = 3.0,
) -> bool:
    """Rename quickly; skip (rather than block) if the API is rate-limited.

    Permission changes matter more than the cosmetic emoji prefix.
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


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def create_event_ticket_channel(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "This can only be used in a server.", ephemeral=True
        )
        return

    if not isinstance(EVENT_TICKET_CATEGORY_ID, int) or EVENT_TICKET_CATEGORY_ID <= 0:
        await interaction.response.send_message(
            "Event tickets are not configured yet. Ask an admin to set "
            "`EVENT_TICKET_CATEGORY_ID` in config.",
            ephemeral=True,
        )
        return

    category = guild.get_channel(EVENT_TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message(
            "Configured event ticket category was not found. Please contact an admin.",
            ephemeral=True,
        )
        return

    # One open ticket per user at a time.
    existing = _find_existing_ticket(category, interaction.user.id)
    if existing is not None:
        await interaction.response.send_message(
            f"You already have an open event ticket: {existing.mention}\n"
            "Please use your existing ticket.",
            ephemeral=True,
        )
        return

    username = _sanitize_username(interaction.user.name, interaction.user.id)
    channel_name = f"「❗」event-{username}"

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

    for role_id in _event_staff_role_ids():
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
        reason=f"Event ticket from {interaction.user}",
    )
    await channel.edit(
        topic=f"event-opener:{interaction.user.id}",
        reason="Store event ticket opener",
    )

    await interaction.response.send_message(
        f"Your event ticket has been created: {channel.mention}",
        ephemeral=True,
    )

    prompt_embed = discord.Embed(
        title="Event Submission",
        description=(
            "**Please post your event answer / submission here.**\n\n"
            "Event staff will review it shortly."
        ),
        color=discord.Color.green(),
    )
    _set_remaining7_footer(prompt_embed, interaction.client.user)
    # content= mention actually pings the opener (an embed field alone would not).
    await channel.send(content=interaction.user.mention, embed=prompt_embed)


async def close_event_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
) -> bool:
    if not _is_event_staff(actor):
        return False
    if not is_event_ticket_channel(channel):
        return False

    guild = channel.guild
    opener_id = _extract_opener_id(channel.topic)
    if opener_id is not None:
        opener = guild.get_member(opener_id)
        if opener is not None and not _is_event_staff(opener):
            await channel.set_permissions(
                opener,
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                use_application_commands=True,
            )

    # Close in place: flip the emoji prefix, do NOT move the channel.
    await _try_rename_channel(
        channel,
        _closed_name(channel.name),
        reason=f"Event ticket closed by {actor}",
    )

    await channel.send(
        f"Ticket closed by {actor.name}.",
        view=EventClosedTicketView(),
    )
    return True


async def reopen_event_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
) -> bool:
    if not _is_event_staff(actor):
        return False
    if not is_event_ticket_channel(channel):
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
        _active_name(channel.name),
        reason=f"Event ticket reopened by {actor}",
    )

    await channel.send(f"✅ Ticket reopened by {actor.mention}.")
    return True


async def delete_event_ticket_channel(
    channel: discord.TextChannel,
    actor: discord.Member,
    bot: commands.Bot,
) -> bool:
    if not _is_event_staff(actor):
        return False
    if not is_event_ticket_channel(channel):
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
                    content=(
                        "Here is the transcript for your closed event ticket in "
                        f"**{channel.guild.name}**."
                    ),
                    file=dm_file,
                )
            except discord.Forbidden:
                pass

    log_channel = (
        channel.guild.get_channel(EVENT_TICKET_TRANSCRIPT_CHANNEL_ID)
        if isinstance(EVENT_TICKET_TRANSCRIPT_CHANNEL_ID, int)
        and EVENT_TICKET_TRANSCRIPT_CHANNEL_ID > 0
        else None
    )
    if isinstance(log_channel, discord.TextChannel):
        log_file = discord.File(io.BytesIO(transcript_bytes), filename=filename)
        await log_channel.send(
            content=(
                f"📝 Transcript for event ticket **#{channel.name}** "
                f"deleted by **{actor.name}** (opener: {opener_display})."
            ),
            file=log_file,
        )

    await channel.delete(reason=f"Event ticket deleted by {actor}")
    return True


# ---------------------------------------------------------------------------
# Prefix-command wrappers (dispatched via features/ticket_command_router.py)
# ---------------------------------------------------------------------------


async def close_event_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_event_staff(ctx.author):
        await ctx.reply("You don't have permission to close this ticket.")
        return

    ok = await close_event_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply(
            "This command can only be used inside an active event ticket channel."
        )


async def reopen_event_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_event_staff(ctx.author):
        await ctx.reply("You don't have permission to reopen this ticket.")
        return

    ok = await reopen_event_ticket_channel(ctx.channel, ctx.author)
    if not ok:
        await ctx.reply("This command can only be used inside an event ticket channel.")


async def delete_event_ticket_via_command(ctx: commands.Context):
    if ctx.guild is None or not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server ticket channel.")
        return
    if not isinstance(ctx.author, discord.Member) or not _is_event_staff(ctx.author):
        await ctx.reply("You don't have permission to delete this ticket.")
        return

    ok = await delete_event_ticket_channel(ctx.channel, ctx.author, ctx.bot)
    if not ok:
        await ctx.reply("This command can only be used inside an event ticket channel.")


# ---------------------------------------------------------------------------
# UI (persistent views)
# ---------------------------------------------------------------------------


class EventTicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Event Ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="event_open_ticket",
    )
    async def open_ticket_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await create_event_ticket_channel(interaction)


class EventClosedTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Delete Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="event_delete_ticket",
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
                "This only works in event ticket channels.", ephemeral=True
            )
            return

        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.NotFound:
            deferred = False

        ok = await delete_event_ticket_channel(
            interaction.channel, interaction.user, interaction.client
        )
        if ok:
            # Channel is gone; any followup would 404. Its disappearance is confirmation.
            return
        try:
            if deferred or interaction.response.is_done():
                await interaction.followup.send(
                    "This button can only be used in event tickets by staff.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "This button can only be used in event tickets by staff.",
                    ephemeral=True,
                )
        except discord.NotFound:
            pass

    @discord.ui.button(
        label="Reopen Ticket",
        style=discord.ButtonStyle.success,
        custom_id="event_reopen_ticket",
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
                "This only works in event ticket channels.", ephemeral=True
            )
            return

        deferred = False
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.NotFound:
            deferred = False

        ok = await reopen_event_ticket_channel(interaction.channel, interaction.user)
        if not ok:
            try:
                if deferred or interaction.response.is_done():
                    await interaction.followup.send(
                        "This button can only be used in event tickets by staff.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "This button can only be used in event tickets by staff.",
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
            pass


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class EventTickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(EventTicketPanelView())
        self.bot.add_view(EventClosedTicketView())

    @app_commands.command(
        name="event-ticket-panel",
        description="Post the event ticket panel.",
    )
    async def event_ticket_panel(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        if not _is_event_staff(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to post this panel.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "This command can only be used in a text channel.", ephemeral=True
            )
            return

        if (
            isinstance(EVENT_TICKET_PANEL_CHANNEL_ID, int)
            and EVENT_TICKET_PANEL_CHANNEL_ID > 0
            and channel.id != EVENT_TICKET_PANEL_CHANNEL_ID
        ):
            await interaction.response.send_message(
                f"Please run this command in <#{EVENT_TICKET_PANEL_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Event Tickets",
            description=(
                "Click the button below to open a private ticket for your event "
                "submission.\n\n"
                "You can only have **one open event ticket** at a time. Event staff "
                "will review your submission inside the ticket."
            ),
            color=discord.Color.green(),
        )
        _set_remaining7_footer(embed, interaction.client.user)

        await interaction.response.send_message(
            embed=embed, view=EventTicketPanelView()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EventTickets(bot))
