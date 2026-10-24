"""Brawl Stars club tracking (#595): the clubs shown in the club-list channel.

Community Managers (plus Admins and Founders) add and remove tracked clubs with
slash commands. Three background jobs keep their data current (#616):

- every 30 minutes, each club's stats plus its country and global rank;
- every 3 hours, each member's current ranked rank, reduced to per-club
  aggregates and spread out so ~1,350 player requests never burst;
- once a day, each club's country. The API has no country field, and a club
  only has a country rank when it is in that country's top 200, so the bot
  scans every country's top 200 and records where each club appears.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database.mongo import (
    add_tracked_club,
    count_tracked_clubs,
    get_setting,
    list_tracked_clubs,
    mark_club_failing,
    remove_tracked_club,
    save_club_countries,
    save_club_ranked,
    save_club_refresh,
    set_setting,
)
from features import brawl_stars_client as bs
from features.config import CLUB_MANAGER_ROLES, MAX_TRACKED_CLUBS

EMBED_DESCRIPTION_LIMIT = 4096
EMBEDS_PER_MESSAGE = 10
NO_PERMISSION = "❌ You don't have permission to manage tracked clubs."
API_UNAVAILABLE = "❌ The Brawl Stars API is unavailable right now. Try again later."

# Player requests for the ranked update are spread evenly over this window.
RANKED_SPREAD_SECONDS = 2 * 60 * 60
COUNTRY_SCAN_INTERVAL = timedelta(hours=24)
COUNTRY_SCAN_SPACING_SECONDS = 1
COUNTRY_SCAN_SETTING = "club_country_scan_at"


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _utcnow() -> datetime:
    # Naive UTC, matching what Mongo stores and returns.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_snapshot(club: dict, country_rank, global_rank) -> dict:
    """The stats shown for one club. Member names and tags are not kept."""
    members = club.get("members") or []
    trophies = [m.get("trophies", 0) for m in members]
    president = next((m for m in members if m.get("role") == "president"), None)
    return {
        "trophies": club.get("trophies", 0),
        "required_trophies": club.get("requiredTrophies", 0),
        "member_count": len(members),
        "president": president.get("name") if president else None,
        "vice_presidents": sum(1 for m in members if m.get("role") == "vicePresident"),
        "seniors": sum(1 for m in members if m.get("role") == "senior"),
        "min_member_trophies": min(trophies) if trophies else None,
        "max_member_trophies": max(trophies) if trophies else None,
        "country_rank": country_rank,
        "global_rank": global_rank,
    }


def build_ranked(players: list[dict]) -> dict | None:
    """Lowest and highest current rank plus members per tier, or None with no data."""
    ranked = [
        p
        for p in players
        if p.get("rankedRank") is not None and p.get("rankedRankName")
    ]
    if not ranked:
        return None
    lowest = min(ranked, key=lambda p: p["rankedRank"])
    highest = max(ranked, key=lambda p: p["rankedRank"])
    tiers: dict[str, int] = {}
    for p in ranked:
        tier = p["rankedRankName"].split()[0]
        tiers[tier] = tiers.get(tier, 0) + 1
    return {
        "min_rank": lowest["rankedRank"],
        "min_rank_name": lowest["rankedRankName"],
        "max_rank": highest["rankedRank"],
        "max_rank_name": highest["rankedRankName"],
        "tier_counts": tiers,
        "players_counted": len(ranked),
    }


def _rank_lookup(items: list[dict]) -> dict[str, int]:
    return {bs.normalize_tag(item["tag"]): item["rank"] for item in items}


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
        # The 30-minute loop and /club-add or /club-remove share this, so two
        # refreshes never run (or edit the club-list messages) at once.
        self._refresh_lock = asyncio.Lock()

    async def cog_load(self):
        self.club_refresh_loop.start()
        self.ranked_loop.start()
        self.country_scan_loop.start()

    async def cog_unload(self):
        self.club_refresh_loop.cancel()
        self.ranked_loop.cancel()
        self.country_scan_loop.cancel()
        await bs.close()

    # --- 30-minute club refresh ---

    async def request_refresh(self):
        """Refresh now, after /club-add or /club-remove."""
        await self.refresh_clubs()

    async def on_refresh_complete(self):
        """Runs after every refresh. History (#617) and the embeds (#618) hook in here."""

    async def refresh_clubs(self):
        async with self._refresh_lock:
            clubs = await list_tracked_clubs()

            global_ranks = None
            try:
                global_ranks = _rank_lookup(await bs.get_global_club_rankings())
            except bs.BrawlStarsError as e:
                print(f"Club refresh: global rankings failed: {e}")

            country_ranks: dict[str, dict[str, int] | None] = {}
            for code in sorted(
                {c["country_code"] for c in clubs if c.get("country_code")}
            ):
                try:
                    country_ranks[code] = _rank_lookup(
                        await bs.get_country_club_rankings(code)
                    )
                except bs.BrawlStarsError as e:
                    print(f"Club refresh: {code} rankings failed: {e}")
                    country_ranks[code] = None

            for tracked in clubs:
                tag = tracked["_id"]
                previous = tracked.get("snapshot") or {}
                code = tracked.get("country_code")
                # A failed rankings call keeps the previous rank instead of
                # showing the club as unranked.
                if code is None:
                    country_rank = None
                elif country_ranks.get(code) is None:
                    country_rank = previous.get("country_rank")
                else:
                    country_rank = country_ranks[code].get(tag)
                if global_ranks is None:
                    global_rank = previous.get("global_rank")
                else:
                    global_rank = global_ranks.get(tag)

                try:
                    club = await bs.get_club(tag)
                except bs.BrawlStarsError as e:
                    print(
                        f"Club refresh: {tag} failed: {type(e).__name__} ({e.reason})"
                    )
                    await mark_club_failing(tag)
                    continue
                await save_club_refresh(
                    tag,
                    club.get("name") or tracked.get("name") or tag,
                    build_snapshot(club, country_rank, global_rank),
                )

            await self.on_refresh_complete()

    @tasks.loop(minutes=30)
    async def club_refresh_loop(self):
        try:
            await self.refresh_clubs()
        except Exception as e:
            print(f"Club refresh loop error: {e}")

    # --- Ranked update ---

    async def run_ranked_update(self):
        members_by_club: dict[str, list[str]] = {}
        for tracked in await list_tracked_clubs():
            tag = tracked["_id"]
            try:
                club = await bs.get_club(tag)
            except bs.BrawlStarsError as e:
                print(f"Ranked update: {tag} failed: {e}")
                continue
            members_by_club[tag] = [m["tag"] for m in club.get("members") or []]

        total = sum(len(tags) for tags in members_by_club.values())
        spacing = RANKED_SPREAD_SECONDS / total if total else 0
        for club_tag, member_tags in members_by_club.items():
            players = []
            for member_tag in member_tags:
                try:
                    players.append(await bs.get_player(member_tag))
                except bs.BrawlStarsError as e:
                    print(f"Ranked update: player {member_tag} failed: {e}")
                await _pause(spacing)
            await save_club_ranked(club_tag, build_ranked(players))

    @tasks.loop(hours=3)
    async def ranked_loop(self):
        try:
            await self.run_ranked_update()
        except Exception as e:
            print(f"Ranked update loop error: {e}")

    # --- Daily country scan ---

    async def run_country_scan_if_due(self) -> bool:
        """Detect each club's country if the last scan was a day ago. Returns True if it ran."""
        last = await get_setting(COUNTRY_SCAN_SETTING)
        if last and _utcnow() - datetime.fromisoformat(last) < COUNTRY_SCAN_INTERVAL:
            return False

        try:
            locations = await bs.get_locations()
        except bs.BrawlStarsError as e:
            print(f"Country scan: locations failed: {e}")
            return False

        clubs = await list_tracked_clubs()
        tracked_tags = {c["_id"] for c in clubs}
        found: dict[str, str] = {}
        failed: set[str] = set()
        for location in locations:
            code = location["countryCode"]
            try:
                for item in await bs.get_country_club_rankings(code):
                    tag = bs.normalize_tag(item["tag"])
                    if tag in tracked_tags:
                        found[tag] = code
            except bs.BrawlStarsError as e:
                print(f"Country scan: {code} failed: {e}")
                failed.add(code)
            await _pause(COUNTRY_SCAN_SPACING_SECONDS)

        countries = {}
        for club in clubs:
            previous = club.get("country_code")
            # Keep a country we could not re-check rather than clearing it.
            keep = previous if previous in failed else None
            countries[club["_id"]] = found.get(club["_id"], keep)

        await save_club_countries(countries)
        await set_setting(COUNTRY_SCAN_SETTING, _utcnow().isoformat())
        return True

    @tasks.loop(hours=1)
    async def country_scan_loop(self):
        try:
            # Refresh straight after a scan so new country ranks show without
            # waiting up to 30 minutes for the next club refresh.
            if await self.run_country_scan_if_due():
                await self.refresh_clubs()
        except Exception as e:
            print(f"Country scan loop error: {e}")

    @club_refresh_loop.before_loop
    @ranked_loop.before_loop
    @country_scan_loop.before_loop
    async def _wait_until_ready(self):
        await self.bot.wait_until_ready()

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
