import discord
from discord.ext import commands

from features.config import (
    BOOSTER_SHOUTOUT_CATEGORY_ID,
    EVENT_TICKET_CATEGORY_ID,
    REDEMPTION_TICKET_CATEGORY_ID,
    SUPPORT_ISSUES_CATEGORY_ID,
    SUPPORT_PARTNERSHIP_CATEGORY_ID,
    SUPPORT_SERVER_CATEGORY_ID,
    SUPPORT_STAFF_APPS_CATEGORY_ID,
)


def get_support_category_ids() -> set[int]:
    """Return configured support ticket category IDs."""
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


def is_support_ticket_channel(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    return channel.category_id in get_support_category_ids()


def is_redemption_ticket_channel(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if (
        not isinstance(REDEMPTION_TICKET_CATEGORY_ID, int)
        or REDEMPTION_TICKET_CATEGORY_ID <= 0
    ):
        return False
    return channel.category_id == REDEMPTION_TICKET_CATEGORY_ID


def is_booster_shoutout_ticket_channel(
    channel: discord.abc.GuildChannel | None,
) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if (
        not isinstance(BOOSTER_SHOUTOUT_CATEGORY_ID, int)
        or BOOSTER_SHOUTOUT_CATEGORY_ID <= 0
    ):
        return False
    return channel.category_id == BOOSTER_SHOUTOUT_CATEGORY_ID


def is_event_ticket_channel(channel: discord.abc.GuildChannel | None) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if not isinstance(EVENT_TICKET_CATEGORY_ID, int) or EVENT_TICKET_CATEGORY_ID <= 0:
        return False
    return channel.category_id == EVENT_TICKET_CATEGORY_ID


async def route_shared_ticket_command(ctx: commands.Context, action: str) -> bool:
    """
    Route shared prefix ticket commands to support/redemption ticket handlers.
    Returns True if handled by a non-tourney module.
    """
    if is_redemption_ticket_channel(ctx.channel):
        from features.economy import (
            close_redemption_ticket_via_command,
            handle_redemption_delete_attempt,
            reopen_redemption_ticket_via_command,
        )

        if action == "close":
            await close_redemption_ticket_via_command(ctx)
            return True
        if action == "delete":
            await handle_redemption_delete_attempt(ctx)
            return True
        if action == "reopen":
            await reopen_redemption_ticket_via_command(ctx)
            return True

    if is_booster_shoutout_ticket_channel(ctx.channel):
        from features.booster_shoutout import (
            close_booster_shoutout_ticket_via_command,
            delete_booster_shoutout_ticket_via_command,
            reopen_booster_shoutout_ticket_via_command,
        )

        if action == "close":
            await close_booster_shoutout_ticket_via_command(ctx)
            return True
        if action == "delete":
            await delete_booster_shoutout_ticket_via_command(ctx)
            return True
        if action == "reopen":
            await reopen_booster_shoutout_ticket_via_command(ctx)
            return True

    if is_event_ticket_channel(ctx.channel):
        from features.event_tickets import (
            close_event_ticket_via_command,
            delete_event_ticket_via_command,
            reopen_event_ticket_via_command,
        )

        if action == "close":
            await close_event_ticket_via_command(ctx)
            return True
        if action == "delete":
            await delete_event_ticket_via_command(ctx)
            return True
        if action == "reopen":
            await reopen_event_ticket_via_command(ctx)
            return True

    if not is_support_ticket_channel(ctx.channel):
        return False

    from features.support_tickets import (
        close_support_ticket_via_command,
        delete_support_ticket_via_command,
        reopen_support_ticket_via_command,
    )

    if action == "close":
        await close_support_ticket_via_command(ctx)
        return True
    if action == "delete":
        await delete_support_ticket_via_command(ctx)
        return True
    if action == "reopen":
        await reopen_support_ticket_via_command(ctx)
        return True

    return False
