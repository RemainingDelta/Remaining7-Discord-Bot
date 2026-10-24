"""Brawl Stars club tracking (#595): the clubs shown in the club-list channel.

Community Managers (plus Admins and Founders) add and remove tracked clubs with
slash commands. A club's country is never entered: the refresh loop (#616)
detects it from the country rankings, since a club only has a country rank
when it appears in that country's top 200.
"""

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from database.mongo import (
    add_tracked_club,
    count_tracked_clubs,
    list_tracked_clubs,
    remove_tracked_club,
)
from features import brawl_stars_client as bs
from features.config import CLUB_MANAGER_ROLES, MAX_TRACKED_CLUBS

EMBED_DESCRIPTION_LIMIT = 4096
EMBEDS_PER_MESSAGE = 10
NO_PERMISSION = "❌ You don't have permission to manage tracked clubs."
API_UNAVAILABLE = "❌ The Brawl Stars API is unavailable right now. Try again later."


def is_club_manager(member) -> bool:
    """Community Managers, Admins and Founders can manage tracked clubs."""
    if not isinstance(member, discord.Member):
        return False
    return any(role.id in CLUB_MANAGER_ROLES for role in member.roles)


def _timestamp(dt: datetime) -> str:
    # Mongo returns naive UTC datetimes.
    return f"<t:{int(dt.replace(tzinfo=timezone.utc).timestamp())}:R>"


def _club_line(club: dict) -> str:
    parts = [f"**{club.get('name') or 'Unknown'}** `{club['_id']}`"]
    parts.append(club.get("country_code") or "—")
    fetched = club.get("fetched_at")
    parts.append(f"fetched {_timestamp(fetched)}" if fetched else "not fetched yet")
    line = " · ".join(parts)
    if club.get("failing_since"):
        line += f" · ⚠️ failing since {_timestamp(club['failing_since'])}"
    return line


def _chunk_lines(lines: list[str], limit: int = EMBED_DESCRIPTION_LIMIT) -> list[str]:
    chunks, current = [], ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class ClubTracking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_unload(self):
        await bs.close()

    async def request_refresh(self):
        """Refresh the club-list channel now. Filled in by the refresh loop (#616)."""

    async def club_tag_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            query = current.strip().lower().lstrip("#")
            choices = []
            for club in await list_tracked_clubs():
                name = club.get("name") or club["_id"]
                if query in name.lower() or query in club["_id"].lower():
                    label = f"{name} ({club['_id']})"[:100]
                    choices.append(app_commands.Choice(name=label, value=club["_id"]))
            return choices[:25]
        except Exception as e:
            print(f"Club autocomplete error: {e}")
            return []

    @app_commands.command(
        name="club-add",
        description="Start tracking a Brawl Stars club in the club list",
    )
    @app_commands.describe(tag="The club's tag, e.g. #QQGLJU2R")
    async def club_add(self, interaction: discord.Interaction, tag: str):
        if not is_club_manager(interaction.user):
            await interaction.response.send_message(NO_PERMISSION, ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        try:
            tag = bs.normalize_tag(tag)
        except ValueError:
            await interaction.followup.send("❌ Enter a club tag.")
            return

        if await count_tracked_clubs() >= MAX_TRACKED_CLUBS:
            await interaction.followup.send(
                f"❌ The club list is full ({MAX_TRACKED_CLUBS} clubs). "
                "Remove a club before adding another."
            )
            return

        try:
            club = await bs.get_club(tag)
        except bs.NotFoundError:
            await interaction.followup.send(f"❌ No club with tag `{tag}` exists.")
            return
        except (bs.AccessDeniedError, bs.ApiUnavailableError) as e:
            print(f"Club add: API error for {tag}: {e} ({e.reason})")
            await interaction.followup.send(API_UNAVAILABLE)
            return

        name = club.get("name") or tag
        if not await add_tracked_club(tag, name):
            await interaction.followup.send(
                f"❌ **{name}** (`{tag}`) is already tracked."
            )
            return

        await interaction.followup.send(
            f"✅ Added **{name}** (`{tag}`) to the club list."
        )
        await self.request_refresh()

    @app_commands.command(
        name="club-remove", description="Stop tracking a club in the club list"
    )
    @app_commands.describe(tag="The tracked club to remove")
    @app_commands.autocomplete(tag=club_tag_autocomplete)
    async def club_remove(self, interaction: discord.Interaction, tag: str):
        if not is_club_manager(interaction.user):
            await interaction.response.send_message(NO_PERMISSION, ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        try:
            tag = bs.normalize_tag(tag)
        except ValueError:
            await interaction.followup.send("❌ Enter a club tag.")
            return

        if not await remove_tracked_club(tag):
            await interaction.followup.send(f"❌ `{tag}` is not tracked.")
            return

        await interaction.followup.send(
            f"✅ Removed `{tag}` from the club list. Its history is kept."
        )
        await self.request_refresh()

    @app_commands.command(name="club-list", description="Show every tracked club")
    async def club_list(self, interaction: discord.Interaction):
        if not is_club_manager(interaction.user):
            await interaction.response.send_message(NO_PERMISSION, ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        clubs = sorted(
            await list_tracked_clubs(), key=lambda c: (c.get("name") or "").lower()
        )
        if not clubs:
            await interaction.followup.send(
                "No clubs are tracked yet. Add one with `/club-add`."
            )
            return

        chunks = _chunk_lines([_club_line(c) for c in clubs])
        embeds = [
            discord.Embed(
                title=f"Tracked Clubs ({len(clubs)}/{MAX_TRACKED_CLUBS})"
                if i == 0
                else None,
                description=chunk,
                color=discord.Color.gold(),
            )
            for i, chunk in enumerate(chunks)
        ]
        for start in range(0, len(embeds), EMBEDS_PER_MESSAGE):
            await interaction.followup.send(
                embeds=embeds[start : start + EMBEDS_PER_MESSAGE]
            )


async def setup(bot):
    await bot.add_cog(ClubTracking(bot))
