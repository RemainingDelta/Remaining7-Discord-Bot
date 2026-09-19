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
from typing import NamedTuple

import discord
from discord import app_commands
from discord.ext import commands

from features.config import (
    ADMIN_ROLE_ID,
    EVENT_STAFF_ROLE_ID,
    EVENT_TICKET_CATEGORY_ID,
    EVENT_TICKET_PANEL_CHANNEL_ID,
    EVENT_TICKET_TRANSCRIPT_CHANNEL_ID,
)

# Leave headroom under Discord's 100-char channel-name limit for the
# "「❗」event-" prefix.
_MAX_USERNAME_LEN = 90

# A policy cap on how much of a ticket is worth preserving, not a Discord
# limit. Collection is oldest-first, so a ticket above this keeps its earliest
# images; the rest stay named and linked in the transcript text.
_MAX_TRANSCRIPT_IMAGES = 25

# This one is Discord's, and it is enforced with a 400 rather than the 413 that
# drives size splitting -- so it has to be respected up front, by chunking.
_MAX_ATTACHMENTS_PER_MESSAGE = 10

# Same list as features/scam_detection.py. Deliberately excludes .gif.
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# Peak memory, not a Discord limit. The bot runs on a 256 MB host that
# typically sits around 87% used, leaving roughly 33 MB free, so images are
# downloaded one batch at a time and released before the next. Peak is this
# budget regardless of how many images a ticket holds; raising it trades
# message count back for OOM risk.
_MAX_BATCH_BYTES = 8 * 1024 * 1024

# A file larger than one batch could never form a sendable batch, so there is
# no point downloading it.
_MAX_IMAGE_BYTES = _MAX_BATCH_BYTES


def _event_staff_role_ids() -> set[int]:
    """Roles that may manage event tickets: event staff and admins.

    Every gate in this module reads this one set, so adding a role here grants
    it the panel command, access to every ticket channel, and close/reopen/delete.
    """
    return {
        rid
        for rid in (EVENT_STAFF_ROLE_ID, ADMIN_ROLE_ID)
        if isinstance(rid, int) and rid > 0
    }


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
    """Return the caller's OPEN event ticket in this category, if any.

    Closed tickets stay in the category (close happens in place), so they must not
    block a new one. The opener ID is parsed exactly rather than substring-matched,
    so user 123 is not matched by a ticket belonging to user 1234.
    """
    for ch in category.channels:
        if not isinstance(ch, discord.TextChannel):
            continue
        if _extract_opener_id(ch.topic) != user_id:
            continue
        if "「❗」" in ch.name:  # only an open ticket blocks a new one
            return ch
    return None


def _set_remaining7_footer(
    embed: discord.Embed, bot_user: discord.abc.User | None
) -> None:
    icon_url = bot_user.display_avatar.url if bot_user is not None else None
    embed.set_footer(text="Remaining 7 Bot", icon_url=icon_url)


def build_event_panel_embed(bot_user: discord.abc.User | None) -> discord.Embed:
    """The panel embed, rebuilt from source on every post.

    Shared by /event-ticket-panel and the restart repost so an edit here reaches
    the channel on the next boot, rather than the channel keeping a stale copy.
    """
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
    _set_remaining7_footer(embed, bot_user)
    return embed


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


# One attachment chosen for the transcript, with the prefixed filename it will
# be uploaded under. Bytes are not read until delivery.
SelectedImage = tuple[str, discord.Attachment]

# A file ready to upload: filename and its bytes.
TranscriptFile = tuple[str, bytes]


class Destination(NamedTuple):
    """Somewhere a transcript is sent, and the line that introduces it."""

    target: discord.abc.Messageable
    content: str


class Transcript(NamedTuple):
    """A ticket's history, plus the images chosen to keep with it.

    Attachments, not bytes: they are downloaded a batch at a time during
    delivery so peak memory never scales with the size of the ticket.
    """

    text: str
    attachments: list[SelectedImage]


def _is_transcript_image(attachment: discord.Attachment) -> bool:
    return attachment.filename.lower().endswith(_IMAGE_EXTENSIONS)


async def _build_transcript(channel: discord.TextChannel) -> Transcript:
    """Render the ticket history and download its images in one history pass.

    Images are re-uploaded rather than linked: Discord attachment URLs are
    signed and expire within about a day, and deleting the channel makes the
    originals collectable, so a linked screenshot is gone by the time anyone
    reads the transcript. Anything not downloaded still gets its name and URL
    in the text, so nothing disappears without a trace.
    """
    opener_id = _extract_opener_id(channel.topic)
    lines: list[str] = [
        f"Channel: {channel.name}",
        f"Opener ID: {opener_id or 'Unknown'}",
        "",
    ]
    chosen: list[SelectedImage] = []
    skipped: list[str] = []

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

        for attachment in msg.attachments:
            if (
                len(chosen) >= _MAX_TRANSCRIPT_IMAGES
                or not _is_transcript_image(attachment)
                or attachment.size > _MAX_IMAGE_BYTES
            ):
                skipped.append(attachment.filename)
                continue
            # Prefixed so two "image.png" from different messages stay distinct.
            chosen.append((f"{len(chosen) + 1:02d}-{attachment.filename}", attachment))

    if len(lines) <= 3:
        lines.append("No messages in this ticket.")

    if chosen:
        lines += ["", "Attached to this transcript:"]
        lines += [f"  {name}" for name, _ in chosen]
    if skipped:
        lines += ["", "Not attached (links above expire):"]
        lines += [f"  {name}" for name in skipped]

    return Transcript("\n".join(lines), chosen)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _batch_attachments(attachments: list[SelectedImage]) -> list[list[SelectedImage]]:
    """Group attachments so each message stays within both ceilings.

    Bytes bound peak memory, since a batch is downloaded and released as a
    unit. Count is Discord's own limit, reported as a 400 rather than the 413
    that drives size splitting, so it has to be respected up front.

    Every batch may hold the full ten. The transcript .txt is appended to the
    last one during delivery, or sent alone if that batch is already full.
    """
    batches: list[list[SelectedImage]] = []
    current: list[SelectedImage] = []
    held = 0
    for name, attachment in attachments:
        too_big = held + attachment.size > _MAX_BATCH_BYTES
        too_many = len(current) >= _MAX_ATTACHMENTS_PER_MESSAGE
        if current and (too_big or too_many):
            batches.append(current)
            current, held = [], 0
        current.append((name, attachment))
        held += attachment.size
    if current:
        batches.append(current)
    return batches


async def _deliver_transcript(
    destinations: list[Destination],
    transcript_file: TranscriptFile,
    attachments: list[SelectedImage],
) -> list[str]:
    """Send the transcript and its images, one batch of bytes at a time.

    Each batch is downloaded, sent to every destination, then dropped before
    the next is read, so peak memory is _MAX_BATCH_BYTES rather than the size
    of the whole ticket. A destination that fails is skipped for that batch
    without abandoning the others.

    Images go first and the transcript .txt closes the delivery: the images
    are the submission, the .txt only summarises them.
    """
    dropped: list[str] = []
    batches = _batch_attachments(attachments)
    # The .txt needs a slot of its own when the final batch is already full,
    # or when there are no images at all.
    if not batches or len(batches[-1]) >= _MAX_ATTACHMENTS_PER_MESSAGE:
        batches.append([])

    for index, batch in enumerate(batches):
        payload: list[TranscriptFile] = []
        for name, attachment in batch:
            try:
                payload.append((name, await attachment.read()))
            except (discord.HTTPException, discord.NotFound):
                dropped.append(name)
        if index == len(batches) - 1:
            payload.append(transcript_file)
        if not payload:
            continue

        for destination in destinations:
            try:
                dropped += await _send_one_message(
                    destination.target,
                    destination.content if index == 0 else None,
                    payload,
                )
            except discord.HTTPException:
                # DMs closed, missing permissions: never block the rest.
                pass
    return dropped


async def _send_one_message(
    destination: discord.abc.Messageable,
    content: str | None,
    payload: list[TranscriptFile],
) -> list[str]:
    """Send one message's worth of files, splitting only if Discord refuses.

    The byte limit is variable and may apply per file or per payload, so rather
    than predict it we attempt the send and let a 413 drive the split. Files are
    rebuilt from bytes on every attempt: a discord.File wraps a single-use
    stream and cannot be retried.
    """
    try:
        await destination.send(
            content=content,
            files=[
                discord.File(io.BytesIO(data), filename=name) for name, data in payload
            ],
        )
        return []
    except discord.HTTPException as e:
        if e.status != 413:
            raise  # not a size problem; the caller's handler owns it

    if len(payload) == 1:
        return [payload[0][0]]

    half = len(payload) // 2
    dropped = await _send_one_message(destination, content, payload[:half])
    # Follow-ups carry no content line; the first message already has it.
    return dropped + await _send_one_message(destination, None, payload[half:])


async def create_event_ticket_channel(interaction: discord.Interaction) -> None:
    # Defer first: creating the channel takes two API writes, which can exceed
    # Discord's 3s interaction window and raise Unknown Interaction (10062).
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.NotFound:
        return

    guild = interaction.guild
    if guild is None:
        await interaction.followup.send(
            "This can only be used in a server.", ephemeral=True
        )
        return

    if not isinstance(EVENT_TICKET_CATEGORY_ID, int) or EVENT_TICKET_CATEGORY_ID <= 0:
        await interaction.followup.send(
            "Event tickets are not configured yet. Ask an admin to set "
            "`EVENT_TICKET_CATEGORY_ID` in config.",
            ephemeral=True,
        )
        return

    category = guild.get_channel(EVENT_TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send(
            "Configured event ticket category was not found. Please contact an admin.",
            ephemeral=True,
        )
        return

    # One open ticket per user at a time.
    existing = _find_existing_ticket(category, interaction.user.id)
    if existing is not None:
        await interaction.followup.send(
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

    # The topic is set in the create call, not a follow-up edit: it is how
    # _find_existing_ticket identifies the opener, so a channel that exists
    # without one is a window in which a second click opens a duplicate ticket.
    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=f"event-opener:{interaction.user.id}",
        reason=f"Event ticket from {interaction.user}",
    )

    await interaction.followup.send(
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

    transcript = await _build_transcript(channel)
    transcript_file = (
        f"{channel.name}_transcript.txt",
        transcript.text.encode("utf-8"),
    )

    opener_id = _extract_opener_id(channel.topic)
    opener_display = "unknown"
    user = None
    if opener_id is not None:
        opener_display = f"<@{opener_id}>"
        user = bot.get_user(opener_id)
        if user is None:
            try:
                user = await bot.fetch_user(opener_id)
            except Exception:
                user = None

    log_channel = (
        channel.guild.get_channel(EVENT_TICKET_TRANSCRIPT_CHANNEL_ID)
        if isinstance(EVENT_TICKET_TRANSCRIPT_CHANNEL_ID, int)
        and EVENT_TICKET_TRANSCRIPT_CHANNEL_ID > 0
        else None
    )

    # Both destinations share one download pass: each batch is read once, sent
    # everywhere, then released.
    destinations: list[Destination] = []
    if isinstance(log_channel, discord.TextChannel):
        destinations.append(
            Destination(
                log_channel,
                f"📝 Transcript for event ticket **#{channel.name}** "
                f"deleted by **{actor.name}** (opener: {opener_display}).",
            )
        )
    if user is not None:
        destinations.append(
            Destination(
                user,
                "Here is the transcript for your closed event ticket in "
                f"**{channel.guild.name}**.",
            )
        )

    if destinations:
        dropped = await _deliver_transcript(
            destinations, transcript_file, transcript.attachments
        )
        if dropped:
            print(f"⚠️ Could not deliver {dropped} with the transcript")

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


async def _respond(interaction: discord.Interaction, text: str) -> None:
    """Reply to a button press, whether or not the interaction was deferred.

    Once defer() has succeeded the only usable channel is the followup; before
    that it is the initial response. Either can 404 on an expired interaction,
    which is not worth reporting to anyone.
    """
    send = (
        interaction.followup.send
        if interaction.response.is_done()
        else interaction.response.send_message
    )
    try:
        await send(text, ephemeral=True)
    except discord.NotFound:
        pass


class EventClosedTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _run(self, interaction: discord.Interaction, action, success: str | None):
        """Shared body of both buttons: guard, defer, act, report.

        `success` is None for delete: the channel is gone by then, so any
        followup would 404 and its disappearance is the confirmation.
        """
        if not isinstance(interaction.user, discord.Member):
            await _respond(interaction, "Only server members can use this.")
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await _respond(interaction, "This only works in event ticket channels.")
            return

        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            pass

        if not await action(interaction):
            await _respond(
                interaction, "This button can only be used in event tickets by staff."
            )
        elif success is not None:
            await _respond(interaction, success)

    @discord.ui.button(
        label="Delete Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="event_delete_ticket",
    )
    async def delete_ticket_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._run(
            interaction,
            lambda i: delete_event_ticket_channel(i.channel, i.user, i.client),
            success=None,
        )

    @discord.ui.button(
        label="Reopen Ticket",
        style=discord.ButtonStyle.success,
        custom_id="event_reopen_ticket",
    )
    async def reopen_ticket_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._run(
            interaction,
            lambda i: reopen_event_ticket_channel(i.channel, i.user),
            success="Ticket reopened.",
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Startup repost
# ---------------------------------------------------------------------------

# on_ready re-fires on every gateway reconnect, so the repost is guarded to once
# per process. A reconnect is not a restart, and wiping the channel on each one
# would churn it and break links to the panel message.
_PANEL_REPOSTED = False


async def _clear_panel_channel(channel: discord.TextChannel) -> None:
    """Remove every message, whoever posted it.

    Bulk purge is one request per 100 messages but Discord refuses it for
    anything older than 14 days, so fall back to individual deletes.
    """
    try:
        await channel.purge(limit=None)
    except discord.HTTPException:
        async for message in channel.history(limit=None):
            try:
                await message.delete()
            except discord.HTTPException:
                pass


async def repost_event_ticket_panel(bot: commands.Bot) -> None:
    """Wipe the panel channel and post a fresh panel, once per process."""
    global _PANEL_REPOSTED

    if not EVENT_TICKET_PANEL_CHANNEL_ID:
        print("⚠️ EVENT_TICKET_PANEL_CHANNEL_ID is not set — skipping the panel post")
        return
    if _PANEL_REPOSTED:
        return

    channel = bot.get_channel(EVENT_TICKET_PANEL_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        print(
            f"⚠️ Event panel channel {EVENT_TICKET_PANEL_CHANNEL_ID} not found "
            "— panel not posted"
        )
        return

    if not channel.permissions_for(channel.guild.me).manage_messages:
        # Posting without being able to clear the channel would stack another
        # panel on every restart, so do nothing and leave this line as the signal.
        print(
            f"⚠️ Missing Manage Messages in #{channel.name} — event panel not reposted"
        )
        return

    try:
        await _clear_panel_channel(channel)
        await channel.send(
            embed=build_event_panel_embed(bot.user), view=EventTicketPanelView()
        )
        _PANEL_REPOSTED = True
        print(f"✅ Reposted the event ticket panel in #{channel.name}")
    except Exception as e:
        print(f"⚠️ Could not repost the event ticket panel: {e}")


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

        embed = build_event_panel_embed(interaction.client.user)

        await interaction.response.send_message(
            embed=embed, view=EventTicketPanelView()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EventTickets(bot))
