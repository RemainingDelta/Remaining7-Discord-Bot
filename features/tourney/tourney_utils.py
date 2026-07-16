import re
from deep_translator import GoogleTranslator
from langdetect import detect
import discord
from discord.ext import commands
import io
from datetime import datetime
from discord.utils import utcnow
import asyncio
from database.mongo import get_blacklisted_user
from features.config import (
    TOURNEY_CATEGORY_ID,
    PRE_TOURNEY_CATEGORY_ID,
    TOURNEY_CLOSED_CATEGORY_ID,
    PRE_TOURNEY_CLOSED_CATEGORY_ID,
    ALLOWED_STAFF_ROLES,
    LOG_CHANNEL_ID,
    TOURNEY_ADMIN_CHANNEL_ID,
    TOURNEY_ADMIN_ROLE_ID,
)

_ticket_counter: int = 1
_pre_tourney_ticket_counter: int = 1

# Prefix of the bot message that carries images submitted via the ticket modal.
# Used to find those images again when the transcript is generated on delete.
SUBMITTED_IMAGES_MARKER = "🖼️ **Submitted Images**"

# user_id -> set of open ticket channel IDs
_user_open_tickets: dict[int, set[int]] = {}

# user_id -> datetime of last ticket creation
_user_last_ticket_open_time: dict[int, datetime] = {}


async def _get_translation(text: str) -> str | None:
    """Detects language and returns English translation if not already English."""
    try:
        # Run blocking detection and translation in a thread to keep the bot responsive
        detected = await asyncio.to_thread(detect, text)
        if detected == "en":
            return None

        translated = await asyncio.to_thread(
            GoogleTranslator(source="auto", target="en").translate, text
        )
        return translated
    except Exception:
        return None


def _filter_image_attachments(
    attachments: list[discord.Attachment] | None,
) -> list[discord.Attachment]:
    """Keep only attachments Discord identifies as images."""
    if not attachments:
        return []
    return [
        a for a in attachments if a.content_type and a.content_type.startswith("image/")
    ]


async def _post_submitted_images(
    channel: discord.TextChannel,
    opener: discord.abc.User,
    attachments: list[discord.Attachment] | None,
) -> None:
    """Re-upload modal-submitted images into the ticket channel.

    Interaction attachments are not guaranteed to stay on Discord's CDN, so the
    images are re-sent as bot-owned files. The marker content lets
    delete_ticket_with_transcript() find them again for the transcript log.
    """
    if not attachments:
        return

    images = _filter_image_attachments(attachments)

    # Tell the user when uploads were discarded, otherwise they believe their
    # proof was submitted while staff sees nothing.
    dropped = len(attachments) - len(images)
    if dropped:
        plural = "s were" if dropped > 1 else " was"
        try:
            await channel.send(
                f"⚠️ {dropped} submitted file{plural} ignored — only images "
                f"(PNG, JPG, etc.) are accepted. Please post other proof "
                f"directly in this channel."
            )
        except Exception:
            pass

    if not images:
        return

    # One message per image so each renders full-size instead of as a collage.
    # No mention here — the opener is already pinged by the proof embed message,
    # and a second ping on ticket open is noisy.
    total = len(images)
    opener_name = discord.utils.escape_markdown(opener.display_name)
    for index, attachment in enumerate(images, start=1):
        counter = f" ({index}/{total})" if total > 1 else ""
        content = f"{SUBMITTED_IMAGES_MARKER} from **{opener_name}**{counter}:"
        try:
            file = await attachment.to_file()
            await channel.send(content=content, file=file)
        except discord.HTTPException:
            # Upload failed (e.g. over the guild size limit) — fall back to a link
            # so staff can at least view the image while the interaction lives.
            try:
                await channel.send(content=f"{content}\n{attachment.url}")
            except Exception:
                pass
        except Exception:
            continue


def _get_open_ticket_count(user_id: int) -> int:
    tickets = _user_open_tickets.get(user_id)
    return len(tickets) if tickets else 0


def _register_ticket_for_user(user_id: int, channel_id: int) -> None:
    tickets = _user_open_tickets.setdefault(user_id, set())
    tickets.add(channel_id)
    _user_last_ticket_open_time[user_id] = utcnow()


def _unregister_ticket_for_user(user_id: int, channel_id: int) -> None:
    tickets = _user_open_tickets.get(user_id)
    if not tickets:
        return
    tickets.discard(channel_id)
    if not tickets:
        # No more open tickets for this user
        _user_open_tickets.pop(user_id, None)


def _check_ticket_limits_for_user(user_id: int) -> tuple[bool, str | None]:
    """
    Returns (ok, message_if_not_ok). Now pulls live values from config
    to support real-time Test Mode toggling.
    """
    import features.config as config  # Import live config state

    # Dynamic limits based on current Test Mode state
    MAX_OPEN_TICKETS_PER_USER = 100 if config.TOURNEY_TEST_MODE else 3
    TICKET_COOLDOWN = 0.1 if config.TOURNEY_TEST_MODE else 180

    # 1) Max open tickets check
    if _get_open_ticket_count(user_id) >= MAX_OPEN_TICKETS_PER_USER:
        return (
            False,
            f"You already have {MAX_OPEN_TICKETS_PER_USER} open tourney tickets. "
            f"Please close one before opening another.",
        )

    # 2) Cooldown between creations check
    last_opened = _user_last_ticket_open_time.get(user_id)
    if last_opened is not None:
        now = utcnow()
        elapsed = (now - last_opened).total_seconds()
        if elapsed < TICKET_COOLDOWN:
            remaining = int(TICKET_COOLDOWN - elapsed)
            minutes, seconds = divmod(remaining, 60)
            human = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            return (
                False,
                f"Please wait {human} before opening another tourney ticket.",
            )

    return True, None


def get_next_ticket_number() -> int:
    """Return the next ticket number and increment the counter."""
    global _ticket_counter
    current = _ticket_counter
    _ticket_counter += 1
    if _ticket_counter > 999:
        _ticket_counter = 1  # wrap after 999, optional
    return current


def get_next_pre_tourney_ticket_number() -> int:
    """Return the next PRE-tourney ticket number."""
    global _pre_tourney_ticket_counter
    current = _pre_tourney_ticket_counter
    _pre_tourney_ticket_counter += 1
    if _pre_tourney_ticket_counter > 999:
        _pre_tourney_ticket_counter = 1
    return current


def reset_ticket_counter():
    """Reset the ticket counter back to 1 (called when tourney starts)."""
    global _ticket_counter
    _ticket_counter = 1


async def create_tourney_ticket_channel(
    interaction: discord.Interaction,
    team_name: str,
    bracket: str,
    issue: str,
    images: list[discord.Attachment] | None = None,
):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    assert guild is not None

    category = guild.get_channel(TOURNEY_CATEGORY_ID)
    if category is None or not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send(
            "Tourney category is not configured correctly. Please tell an admin.",
            ephemeral=True,
        )
        return

    current_count = len(category.channels)
    if current_count >= 50:
        await interaction.followup.send(
            "❌ **System Full:** The tournament ticket queue is currently at maximum capacity (50/50).\n"
            "Please wait for Admins to close some tickets before trying again.",
            ephemeral=True,
        )
        return

    user_id = interaction.user.id
    ok, message = _check_ticket_limits_for_user(user_id)
    if not ok:
        await interaction.followup.send(message, ephemeral=True)
        return

    ticket_number = get_next_ticket_number()
    channel_name = f"「❗」ticket-{ticket_number:03d}"

    # Build permission overwrites
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        # Ticket opener: full access plus slash commands inside this channel
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            use_application_commands=True,
        ),
    }

    for role_id in ALLOWED_STAFF_ROLES:
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
        reason=f"Tourney ticket from {interaction.user} (team {team_name})",
    )
    # Force move to top
    await channel.edit(position=0)

    _register_ticket_for_user(interaction.user.id, channel.id)

    topic = (
        f"tourney-opener:{interaction.user.id}"
        f"|team:{team_name}"
        f"|bracket:{bracket}"
        f"|issue:{issue}"
    )
    await channel.edit(topic=topic, reason="Store ticket opener ID")

    translation = await _get_translation(issue)

    ticket_embed = discord.Embed(
        title="🎟️ New Tournament Ticket",
        description="A Tourney Admin will assist you shortly.",
        color=discord.Color.blurple(),
    )

    ticket_embed.add_field(
        name="👤 Player", value=interaction.user.mention, inline=False
    )
    ticket_embed.add_field(name="📛 Team", value=f"```\n{team_name}\n```", inline=False)
    ticket_embed.add_field(
        name="🔢 Match / Bracket", value=f"```\n{bracket}\n```", inline=False
    )
    ticket_embed.add_field(name="📝 Issue", value=f"```\n{issue}\n```", inline=False)

    if translation:
        ticket_embed.add_field(
            name="🌐 English Translation",
            value=f"```\n{translation}\n```",
            inline=False,
        )

    await channel.send(embed=ticket_embed)

    await _post_submitted_images(channel, interaction.user, images)

    proof_embed = discord.Embed(
        title="📎 Proof Required",
        description=(
            "To help staff resolve your issue, please provide **any one** of the following:\n\n"
            "• 📸 A **screenshot** OR\n"
            "• 🎥 A **short video clip** OR\n"
            "• 📝 **In-game / lobby evidence**\n\n"
            "**Only one type of proof is needed, unless Tourney Admins ask for more.**\n"
            "If no proof is submitted, we may be unable to take action."
        ),
        color=discord.Color.red(),
    )

    if _filter_image_attachments(images):
        proof_embed.add_field(
            name="✅ Screenshots Received",
            value=(
                "The screenshot(s) you attached when opening this ticket count "
                "as proof — nothing more is needed unless a Tourney Admin asks."
            ),
            inline=False,
        )

    await channel.send(
        content=f"{interaction.user.mention} 👇 **Please read this:**",
        embed=proof_embed,
    )

    await interaction.followup.send(
        f"Tourney ticket created: {channel.mention}",
        ephemeral=True,
    )

    await check_and_alert_blacklist(guild, interaction.user, channel)

    return channel


def _is_staff(member: discord.abc.User | discord.Member) -> bool:
    """Check if the user has any of the allowed staff roles."""
    if not isinstance(member, discord.Member):
        return False
    return any(role.id in ALLOWED_STAFF_ROLES for role in member.roles)


async def create_pre_tourney_ticket_channel(
    interaction: discord.Interaction,
    team_name: str | None,
    issue: str,
    images: list[discord.Attachment] | None = None,
):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    assert guild is not None

    category = guild.get_channel(PRE_TOURNEY_CATEGORY_ID)
    if category is None or not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send(
            "Pre-Tourney category is not configured correctly. Please tell an admin.",
            ephemeral=True,
        )
        return

    # --- ADDED: Safety Checks ---
    current_count = len(category.channels)

    # Check 1: Hard Limit (50)
    if current_count >= 50:
        await interaction.followup.send(
            "❌ **System Full:** The pre-tournament ticket queue is currently at maximum capacity (50/50).\n"
            "Please wait for Admins to close some tickets.",
            ephemeral=True,
        )
        return

    user_id = interaction.user.id
    ok, message = _check_ticket_limits_for_user(user_id)
    if not ok:
        await interaction.followup.send(message, ephemeral=True)
        return

    # ... rest of the function remains the same ...
    ticket_number = get_next_pre_tourney_ticket_number()
    channel_name = f"「❗」ticket-{ticket_number:03d}"

    # (Keep the rest of your existing code here)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        # Ticket opener: full access plus slash commands inside this channel
        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            use_application_commands=True,
        ),
    }

    for role_id in ALLOWED_STAFF_ROLES:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                use_application_commands=True,
            )

    display_team = team_name if team_name else "N/A"

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"Pre-Tourney ticket from {interaction.user}",
    )
    await channel.edit(position=0)

    _register_ticket_for_user(interaction.user.id, channel.id)

    topic = f"tourney-opener:{interaction.user.id}|team:{display_team}|issue:{issue}"
    await channel.edit(topic=topic, reason="Store ticket opener ID")

    translation = await _get_translation(issue)

    ticket_embed = discord.Embed(
        title="📩 New Pre-Tourney Inquiry",
        description="A Staff member will assist you shortly.",
        color=discord.Color.orange(),
    )
    ticket_embed.add_field(name="👤 User", value=interaction.user.mention, inline=False)
    ticket_embed.add_field(
        name="📛 Team", value=f"```\n{display_team}\n```", inline=False
    )
    ticket_embed.add_field(name="📝 Inquiry", value=f"```\n{issue}\n```", inline=False)

    if translation:
        ticket_embed.add_field(
            name="🌐 English Translation (Auto)",
            value=f"```\n{translation}\n```",
            inline=False,
        )

    await channel.send(embed=ticket_embed)

    await _post_submitted_images(channel, interaction.user, images)

    await interaction.followup.send(
        f"Support ticket created: {channel.mention}", ephemeral=True
    )

    await check_and_alert_blacklist(guild, interaction.user, channel)


async def close_ticket_via_command(ctx: commands.Context):
    """
    Handle the !close command:
    1. Check perms.
    2. Move to CLOSED category.
    3. Rename (background).
    4. Lock perms.
    """
    from .tourney_views import DeleteTicketView

    guild = ctx.guild
    channel = ctx.channel

    if guild is None or not isinstance(channel, discord.TextChannel):
        await ctx.reply("This command can only be used in a server text channel.")
        return

    if not _is_staff(ctx.author):
        await ctx.reply("You don't have permission to close this ticket.")
        return

    # Determine destination category
    target_category = None
    if channel.category_id == TOURNEY_CATEGORY_ID:
        target_category = guild.get_channel(TOURNEY_CLOSED_CATEGORY_ID)
    elif channel.category_id == PRE_TOURNEY_CATEGORY_ID:
        target_category = guild.get_channel(PRE_TOURNEY_CLOSED_CATEGORY_ID)
    else:
        await ctx.reply(
            "This command can only be used in an active tourney ticket channel."
        )
        return

    if target_category and isinstance(target_category, discord.CategoryChannel):
        current_count = len(target_category.channels)
        LIMIT = 40

        if current_count >= LIMIT:
            # Sort existing archive tickets by creation time (Oldest first)
            existing_channels = [
                c
                for c in target_category.channels
                if isinstance(c, discord.TextChannel)
            ]
            existing_channels.sort(key=lambda c: c.created_at)

            # Delete enough to get back to 39 (making room for the incoming one)
            excess_amount = current_count - LIMIT + 1
            to_delete = existing_channels[:excess_amount]

            await ctx.send(
                f"🧹 Closed category full ({current_count}/50). Auto-cleaning {len(to_delete)} oldest closed ticket(s)..."
            )

            for old_chan in to_delete:
                try:
                    await delete_ticket_with_transcript(
                        guild, old_chan, ctx.author, ctx.bot
                    )
                    await asyncio.sleep(1.5)
                except Exception as e:
                    print(f"Failed to auto-clean ticket {old_chan.name}: {e}")

    # 1. Move Category (Await this first so it happens immediately)
    if target_category and isinstance(target_category, discord.CategoryChannel):
        await channel.edit(category=target_category)

    # 2. Handle Opener Tracking
    opener_id: int | None = None
    if channel.topic:
        for part in channel.topic.split("|"):
            key, _, value = part.partition(":")
            if key == "tourney-opener":
                try:
                    opener_id = int(value)
                except ValueError:
                    opener_id = None
                break

    if opener_id is not None:
        _unregister_ticket_for_user(opener_id, channel.id)

    # 3. Rename (Background)
    base_name = channel.name
    if "「" in base_name and "」" in base_name:
        try:
            base_name = base_name.split("」", 1)[1]
        except IndexError:
            pass
    new_name = f"「👍」{base_name}"

    if channel.name != new_name:
        asyncio.create_task(channel.edit(name=new_name, reason="Tourney ticket closed"))

    # 4. Update Permissions
    # Lock send_messages for every non-staff user overwrite (opener + anyone added via /add)
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and not _is_staff(target):
            overwrite.send_messages = False
            overwrite.view_channel = True
            await channel.set_permissions(target, overwrite=overwrite)

    for role_id in ALLOWED_STAFF_ROLES:
        staff_role = guild.get_role(role_id)
        if staff_role is not None:
            await channel.set_permissions(
                staff_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

    await ctx.send(
        f"Ticket closed by {ctx.author.name} and moved to {target_category.name if target_category else 'closed category'}.",
        view=DeleteTicketView(),
    )


def _extract_translation_lines(
    embeds: list[discord.Embed], timestamp: str
) -> list[str]:
    result = []
    for embed in embeds:
        title = embed.title or ""
        fields = {f.name: f.value for f in embed.fields}
        if title.startswith("🌐 Translated from"):
            lang = title.removeprefix("🌐 Translated from ").strip()
            original = fields.get("Original Message", "").removeprefix("> ").strip()
            translation = fields.get("English Translation", "").strip("*").strip()
            if original and translation:
                result.append(
                    f'[{timestamp}] R7 Bot#9997 ({lang} >> English): "{original}" >> "{translation}"'
                )
        elif title.startswith("🌐 Translated to"):
            lang = title.removeprefix("🌐 Translated to ").strip()
            original = fields.get("Original English", "").removeprefix("> ").strip()
            translated = next(
                (
                    v.strip("*").strip()
                    for k, v in fields.items()
                    if k != "Original English"
                ),
                None,
            )
            if original and translated:
                result.append(
                    f'[{timestamp}] R7 Bot#9997 (English >> {lang}): "{original}" >> "{translated}"'
                )
    return result


async def build_transcript_text(channel: discord.TextChannel) -> str:
    """Collect all messages in the channel into a plain-text transcript,
    with header info from the channel topic.
    """
    header_team = None
    header_bracket = None
    header_issue = None

    # Parse topic for team / bracket / issue
    if channel.topic:
        for part in channel.topic.split("|"):
            key, _, value = part.partition(":")
            if key == "team":
                header_team = value
            elif key == "bracket":
                header_bracket = value
            elif key == "issue":
                header_issue = value

    lines: list[str] = []

    # Header block
    lines.append(f"Team: {header_team or 'Unknown'}")
    lines.append(f"Match Number: {header_bracket or 'Unknown'}")
    lines.append(f"Issue: {header_issue or 'Not specified'}")
    lines.append("")  # blank line before messages

    # Message history
    async for msg in channel.history(limit=None, oldest_first=True):
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
        author = f"{msg.author} ({msg.author.id})"
        content = msg.content or ""
        if msg.attachments:
            attachment_list = ", ".join(a.url for a in msg.attachments)
            if content:
                content += " "
            content += f"[Attachments: {attachment_list}]"

        translation_lines = _extract_translation_lines(msg.embeds, timestamp)

        if content or not translation_lines:
            lines.append(f"[{timestamp}] {author}: {content}")
        lines.extend(translation_lines)

    if len(lines) <= 4:  # only header, no messages
        lines.append("No messages in this ticket.")

    return "\n".join(lines)


async def _collect_submitted_images(
    channel: discord.TextChannel,
    client: discord.Client,
) -> list[tuple[bytes, str]]:
    """Re-download the images posted by _post_submitted_images() as
    (bytes, filename) pairs before the channel (and its CDN links) is deleted.

    Raw bytes rather than discord.File so the caller can send the same images
    to multiple destinations (opener DM + log channel) with a single download —
    discord.File objects are single-use. The marker messages are among the
    first in the channel."""
    bot_id = client.user.id if client.user else None
    if bot_id is None:
        return []

    images: list[tuple[bytes, str]] = []
    try:
        # Each submitted image is its own marker message, so keep scanning
        # instead of stopping at the first hit.
        async for msg in channel.history(limit=25, oldest_first=True):
            if msg.author.id != bot_id or not msg.content.startswith(
                SUBMITTED_IMAGES_MARKER
            ):
                continue
            for attachment in msg.attachments:
                # Cap at 9 so transcript file + images stay within the
                # 10-attachments-per-message limit.
                if len(images) >= 9:
                    return images
                try:
                    images.append((await attachment.read(), attachment.filename))
                except Exception:
                    continue
    except Exception:
        pass
    return images


async def delete_ticket_with_transcript(
    guild: discord.Guild,
    channel: discord.TextChannel,
    deleter: discord.abc.User,
    client: discord.Client,
):
    """Core logic to log a transcript, DM opener, and delete a ticket channel."""
    # Allow deletion from Active OR Closed categories
    valid_categories = (
        TOURNEY_CATEGORY_ID,
        PRE_TOURNEY_CATEGORY_ID,
        TOURNEY_CLOSED_CATEGORY_ID,
        PRE_TOURNEY_CLOSED_CATEGORY_ID,
    )

    if channel.category_id not in valid_categories:
        return

    opener_id: int | None = None
    if channel.topic:
        for part in channel.topic.split("|"):
            key, _, value = part.partition(":")
            if key == "tourney-opener":
                try:
                    opener_id = int(value)
                except ValueError:
                    opener_id = None
                break

    if opener_id is not None:
        _unregister_ticket_for_user(opener_id, channel.id)

    # Build transcript
    transcript_text = await build_transcript_text(channel)
    filename = f"{channel.name}_transcript.txt"

    bytes_for_dm = io.BytesIO(transcript_text.encode("utf-8"))
    bytes_for_log = io.BytesIO(transcript_text.encode("utf-8"))

    file_for_dm = discord.File(bytes_for_dm, filename=filename)
    file_for_log = discord.File(bytes_for_log, filename=filename)

    # Images submitted with the ticket modal, downloaded once and re-sent to
    # both the opener DM and the log channel so they survive channel deletion.
    submitted_images = await _collect_submitted_images(channel, client)

    def _image_files() -> list[discord.File]:
        # discord.File is single-use, so each send needs fresh objects.
        return [
            discord.File(io.BytesIO(data), filename=name)
            for data, name in submitted_images
        ]

    # DM opener
    if opener_id is not None:
        user = client.get_user(opener_id)
        if user is None:
            try:
                user = await client.fetch_user(opener_id)
            except Exception:
                user = None

        if user is not None:
            dm_content = (
                f"Here is the transcript for your closed ticket: "
                f"**#{channel.name}** in **{guild.name}**."
            )
            try:
                await user.send(
                    content=dm_content,
                    files=[file_for_dm, *_image_files()],
                )
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                if not submitted_images:
                    raise
                # Images pushed the DM over a limit — retry transcript only.
                retry_dm = discord.File(
                    io.BytesIO(transcript_text.encode("utf-8")), filename=filename
                )
                try:
                    await user.send(content=dm_content, files=[retry_dm])
                except discord.Forbidden:
                    pass

    # Log channel
    log_channel = guild.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
    if isinstance(log_channel, discord.TextChannel):
        deleter_name = deleter.name
        opener_mention = f"<@{opener_id}>" if opener_id is not None else "Unknown"

        # 1. Extract Info from Topic
        topic = channel.topic if channel.topic else ""

        # Default values
        team_name = "N/A"
        match_num = "N/A"

        if topic:
            # Pattern: Look for "team:" followed by anything until a "|" or End of Line
            team_match = re.search(r"team:(.*?)(?:\||$)", topic, re.IGNORECASE)

            # Pattern: Look for "bracket:" OR "match:" followed by anything until "|" or End of Line
            bracket_match = re.search(
                r"(?:bracket|match|match number):(.*?)(?:\||$)", topic, re.IGNORECASE
            )

            if team_match:
                team_name = team_match.group(1).strip()
            if bracket_match:
                match_num = bracket_match.group(1).strip()

        # 👇 2. Update Content
        log_content = (
            f"📝 Transcript for ticket **#{channel.name}** "
            f"deleted by **{deleter_name}** (opener: {opener_mention}).\n"
            f"🛡️ **Team:** `{team_name}` | 🔢 **Match:** `{match_num}`"
        )

        try:
            await log_channel.send(
                content=log_content,
                files=[file_for_log, *_image_files()],
            )
        except discord.HTTPException:
            if not submitted_images:
                raise
            # Image upload pushed the message over a limit — send the
            # transcript alone rather than losing it entirely.
            retry_file = discord.File(
                io.BytesIO(transcript_text.encode("utf-8")), filename=filename
            )
            await log_channel.send(content=log_content, files=[retry_file])

    await channel.delete(reason=f"Tourney ticket deleted by {deleter}")


async def reopen_tourney_ticket(interaction: discord.Interaction):
    """
    Re-open a ticket:
    1. Check perms.
    2. Move back to ACTIVE category (at TOP).
    3. Rename (background).
    4. Restore perms.
    """
    guild = interaction.guild
    channel = interaction.channel

    if guild is None or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Error: Not a text channel.", ephemeral=True
        )
        return

    if not _is_staff(interaction.user):
        await interaction.response.send_message("Permission denied.", ephemeral=True)
        return

    # Determine destination (Active) category based on current (Closed) category
    target_category = None
    if channel.category_id == TOURNEY_CLOSED_CATEGORY_ID:
        target_category = guild.get_channel(TOURNEY_CATEGORY_ID)
    elif channel.category_id == PRE_TOURNEY_CLOSED_CATEGORY_ID:
        target_category = guild.get_channel(PRE_TOURNEY_CATEGORY_ID)
    else:
        # Also allow reopening if it's already in the active category (just in case)
        if channel.category_id in (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID):
            target_category = channel.category  # Stay here
        else:
            await interaction.response.send_message(
                "This ticket is not in a valid tourney category.", ephemeral=True
            )
            return

    await interaction.response.defer(ephemeral=True)

    # 1. Move Category & Force Top Position
    if target_category and isinstance(target_category, discord.CategoryChannel):
        # --- SAFETY CHECK: Is the active category full? ---
        if len(target_category.channels) >= 50:
            await interaction.followup.send(
                "❌ **Cannot Reopen:** The Active Ticket category is full (50/50). You must close another ticket first.",
                ephemeral=True,
            )
            return
        # --------------------------------------------------

        # We edit category first
        await channel.edit(category=target_category)
        # Then force position 0
        await channel.edit(position=0)

    # 2. Register Opener
    opener_id: int | None = None
    if channel.topic:
        for part in channel.topic.split("|"):
            key, _, value = part.partition(":")
            if key.strip() == "tourney-opener":
                try:
                    opener_id = int(value.strip())
                except ValueError:
                    opener_id = None
                break

    if opener_id is not None:
        _register_ticket_for_user(opener_id, channel.id)

    # 3. Rename (Background)
    base_name = channel.name
    if "「" in base_name and "」" in base_name:
        base_name = base_name.split("」", 1)[1]
    new_name = f"「❗」{base_name}"

    if channel.name != new_name:
        asyncio.create_task(
            channel.edit(name=new_name, reason="Tourney ticket reopened")
        )

    # 4. Restore Perms
    opener_mention = "the ticket owner"
    if opener_id is not None:
        opener = guild.get_member(opener_id)
        if opener is not None:
            opener_mention = opener.mention
            try:
                await channel.set_permissions(
                    opener,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    reason="Ticket Reopened",
                )
            except discord.HTTPException as e:
                print(f"[reopen_tourney_ticket] Failed to update perms: {e}")

    embed = discord.Embed(
        title="🔓 Ticket Reopened",
        description=f"{opener_mention}, this ticket has been reopened by staff. You may send messages again.",
        color=discord.Color.green(),
    )
    await channel.send(content=opener_mention if opener_id else None, embed=embed)

    try:
        if interaction.message:
            await interaction.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    await interaction.followup.send(
        "Ticket reopened and moved to top of active category.", ephemeral=True
    )


async def delete_tourney_ticket(interaction: discord.Interaction):
    """Delete the ticket channel via button interaction, using shared helper."""
    guild = interaction.guild
    channel = interaction.channel

    if guild is None or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This can only be used in a server text channel.",
            ephemeral=True,
        )
        return

    member = interaction.user
    if not _is_staff(member):
        await interaction.response.send_message(
            "You don't have permission to delete this ticket.",
            ephemeral=True,
        )
        return

    valid_categories = (
        TOURNEY_CATEGORY_ID,
        PRE_TOURNEY_CATEGORY_ID,
        TOURNEY_CLOSED_CATEGORY_ID,
        PRE_TOURNEY_CLOSED_CATEGORY_ID,
    )

    if channel.category_id not in valid_categories:
        await interaction.response.send_message(
            "This can only be used in a tourney ticket channel.",
            ephemeral=True,
        )
        return

    # Acknowledge, then run shared delete logic
    await interaction.response.send_message(
        "Deleting this ticket channel…",
        ephemeral=True,
    )

    await delete_ticket_with_transcript(
        guild=guild,
        channel=channel,
        deleter=member,
        client=interaction.client,
    )


async def delete_ticket_via_command(ctx: commands.Context):
    """Command version of delete ticket logic."""
    if not _is_staff(ctx.author):
        await ctx.reply("Permission denied.")
        return

    # Check if we are in a valid ticket category (Active or Closed)
    valid_categories = (
        TOURNEY_CATEGORY_ID,
        PRE_TOURNEY_CATEGORY_ID,
        TOURNEY_CLOSED_CATEGORY_ID,
        PRE_TOURNEY_CLOSED_CATEGORY_ID,
    )
    if ctx.channel.category_id not in valid_categories:
        await ctx.reply("This command can only be used in a tourney ticket channel.")
        return

    await ctx.send("Deleting this ticket channel...")
    await delete_ticket_with_transcript(ctx.guild, ctx.channel, ctx.author, ctx.bot)


async def reopen_ticket_via_command(ctx: commands.Context):
    """Command version of reopen ticket logic."""
    guild = ctx.guild
    channel = ctx.channel

    if not _is_staff(ctx.author):
        await ctx.reply("Permission denied.")
        return

    # Determine destination (Active) category based on current (Closed) category
    target_category = None
    if channel.category_id == TOURNEY_CLOSED_CATEGORY_ID:
        target_category = guild.get_channel(TOURNEY_CATEGORY_ID)
    elif channel.category_id == PRE_TOURNEY_CLOSED_CATEGORY_ID:
        target_category = guild.get_channel(PRE_TOURNEY_CATEGORY_ID)
    else:
        await ctx.reply("This ticket is not in a Closed Ticket category.")
        return

    # SAFETY CHECK: Capacity (50 channel limit)
    if target_category and len(target_category.channels) >= 50:
        await ctx.reply(
            f"❌ Cannot reopen: The active category '{target_category.name}' is full (50/50)."
        )
        return

    # 1. Move
    if target_category:
        await channel.edit(category=target_category, position=0)

    # 2. Register Opener
    opener_id = None
    if channel.topic:
        for part in channel.topic.split("|"):
            key, _, value = part.partition(":")
            if key.strip() == "tourney-opener":
                try:
                    opener_id = int(value.strip())
                except ValueError:
                    pass
                break

    if opener_id:
        _register_ticket_for_user(opener_id, channel.id)

    # 3. Rename
    base_name = channel.name
    if "「" in base_name and "」" in base_name:
        base_name = base_name.split("」", 1)[1]
    new_name = f"「❗」{base_name}"

    if channel.name != new_name:
        asyncio.create_task(channel.edit(name=new_name, reason="Reopened via command"))

    # 4. Restore Perms
    opener_mention = "the ticket owner"
    if opener_id:
        opener = guild.get_member(opener_id)
        if opener:
            opener_mention = opener.mention
            await channel.set_permissions(
                opener, view_channel=True, send_messages=True, read_message_history=True
            )

    embed = discord.Embed(
        title="🔓 Ticket Reopened",
        description=f"{opener_mention}, this ticket has been reopened by staff.",
        color=discord.Color.green(),
    )
    await channel.send(embed=embed)

    # React to the command message to show success
    try:
        await ctx.message.add_reaction("✅")
    except Exception:
        pass


async def check_and_alert_blacklist(
    guild: discord.Guild, user: discord.User, ticket_channel: discord.TextChannel
):
    """
    Checks if a user is blacklisted. If so, pings admins in the admin channel.
    """
    blacklist_data = await get_blacklisted_user(str(user.id))

    if not blacklist_data:
        return  # Not blacklisted, do nothing.

    # They are blacklisted! Prepare the alert.
    admin_channel = guild.get_channel(TOURNEY_ADMIN_CHANNEL_ID)
    if not admin_channel or not isinstance(admin_channel, discord.TextChannel):
        return

    reason = blacklist_data.get("reason", "N/A")
    matcherino = blacklist_data.get("matcherino", "N/A")
    alts = blacklist_data.get("alts", [])
    timestamp = blacklist_data.get("timestamp")

    date_str = timestamp.strftime("%Y-%m-%d") if timestamp else "Unknown"

    # Build Alt String
    if alts:
        alt_str = ", ".join([f"<@{aid}>" for aid in alts])
    else:
        alt_str = "None"

    embed = discord.Embed(
        title="🚨 Blacklisted User Opened Ticket",
        description=f"**User:** {user.mention} (`{user.id}`)\n**Ticket:** {ticket_channel.mention}",
        color=discord.Color.dark_red(),
    )

    embed.add_field(name="Ban Reason", value=reason, inline=False)
    embed.add_field(name="Ban Date", value=date_str, inline=True)
    embed.add_field(name="Matcherino", value=matcherino, inline=True)
    embed.add_field(name="Known Alts", value=alt_str, inline=False)

    # Ping the admin role
    content = f"<@&{TOURNEY_ADMIN_ROLE_ID}> ⚠️ **Blacklisted User Alert!**"

    try:
        await admin_channel.send(content=content, embed=embed)
    except Exception as e:
        print(f"Failed to send blacklist alert: {e}")
