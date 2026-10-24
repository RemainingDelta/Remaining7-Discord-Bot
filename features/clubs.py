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
import json
import re
import time
import unicodedata
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
from features.brawl.commands import SUPERCELL_DISCLAIMER
from features.config import (
    CLUB_EMOJIS,
    CLUB_LIST_CHANNEL_ID,
    CLUB_MANAGER_ROLES,
    MAX_TRACKED_CLUBS,
)

EMBED_DESCRIPTION_LIMIT = 4096
EMBEDS_PER_MESSAGE = 10
NO_PERMISSION = "❌ You don't have permission to manage tracked clubs."
API_UNAVAILABLE = "❌ The Brawl Stars API is unavailable right now. Try again later."

# Player requests for the ranked update are spread evenly over this window.
RANKED_SPREAD_SECONDS = 2 * 60 * 60
COUNTRY_SCAN_INTERVAL = timedelta(hours=24)
COUNTRY_SCAN_SPACING_SECONDS = 1
COUNTRY_SCAN_SETTING = "club_country_scan_at"

# ISO 3166-1 alpha-2 codes. The Brawl Stars API has no endpoint that lists
# countries, so the daily scan walks this list; codes the rankings do not
# cover return 404 and are skipped.
COUNTRY_CODES = (
    "AD",
    "AE",
    "AF",
    "AG",
    "AI",
    "AL",
    "AM",
    "AO",
    "AQ",
    "AR",
    "AS",
    "AT",
    "AU",
    "AW",
    "AX",
    "AZ",
    "BA",
    "BB",
    "BD",
    "BE",
    "BF",
    "BG",
    "BH",
    "BI",
    "BJ",
    "BL",
    "BM",
    "BN",
    "BO",
    "BQ",
    "BR",
    "BS",
    "BT",
    "BV",
    "BW",
    "BY",
    "BZ",
    "CA",
    "CC",
    "CD",
    "CF",
    "CG",
    "CH",
    "CI",
    "CK",
    "CL",
    "CM",
    "CN",
    "CO",
    "CR",
    "CU",
    "CV",
    "CW",
    "CX",
    "CY",
    "CZ",
    "DE",
    "DJ",
    "DK",
    "DM",
    "DO",
    "DZ",
    "EC",
    "EE",
    "EG",
    "EH",
    "ER",
    "ES",
    "ET",
    "FI",
    "FJ",
    "FK",
    "FM",
    "FO",
    "FR",
    "GA",
    "GB",
    "GD",
    "GE",
    "GF",
    "GG",
    "GH",
    "GI",
    "GL",
    "GM",
    "GN",
    "GP",
    "GQ",
    "GR",
    "GS",
    "GT",
    "GU",
    "GW",
    "GY",
    "HK",
    "HM",
    "HN",
    "HR",
    "HT",
    "HU",
    "ID",
    "IE",
    "IL",
    "IM",
    "IN",
    "IO",
    "IQ",
    "IR",
    "IS",
    "IT",
    "JE",
    "JM",
    "JO",
    "JP",
    "KE",
    "KG",
    "KH",
    "KI",
    "KM",
    "KN",
    "KP",
    "KR",
    "KW",
    "KY",
    "KZ",
    "LA",
    "LB",
    "LC",
    "LI",
    "LK",
    "LR",
    "LS",
    "LT",
    "LU",
    "LV",
    "LY",
    "MA",
    "MC",
    "MD",
    "ME",
    "MF",
    "MG",
    "MH",
    "MK",
    "ML",
    "MM",
    "MN",
    "MO",
    "MP",
    "MQ",
    "MR",
    "MS",
    "MT",
    "MU",
    "MV",
    "MW",
    "MX",
    "MY",
    "MZ",
    "NA",
    "NC",
    "NE",
    "NF",
    "NG",
    "NI",
    "NL",
    "NO",
    "NP",
    "NR",
    "NU",
    "NZ",
    "OM",
    "PA",
    "PE",
    "PF",
    "PG",
    "PH",
    "PK",
    "PL",
    "PM",
    "PN",
    "PR",
    "PS",
    "PT",
    "PW",
    "PY",
    "QA",
    "RE",
    "RO",
    "RS",
    "RU",
    "RW",
    "SA",
    "SB",
    "SC",
    "SD",
    "SE",
    "SG",
    "SH",
    "SI",
    "SJ",
    "SK",
    "SL",
    "SM",
    "SN",
    "SO",
    "SR",
    "SS",
    "ST",
    "SV",
    "SX",
    "SY",
    "SZ",
    "TC",
    "TD",
    "TF",
    "TG",
    "TH",
    "TJ",
    "TK",
    "TL",
    "TM",
    "TN",
    "TO",
    "TR",
    "TT",
    "TV",
    "TW",
    "TZ",
    "UA",
    "UG",
    "UM",
    "US",
    "UY",
    "UZ",
    "VA",
    "VC",
    "VE",
    "VG",
    "VI",
    "VN",
    "VU",
    "WF",
    "WS",
    "YE",
    "YT",
    "ZA",
    "ZM",
    "ZW",
)


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _monotonic() -> float:
    return time.monotonic()


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
        "president": clean_name(president.get("name")) if president else None,
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


_COLOR_TAG = re.compile(r"</?c[0-9a-fA-F]*>")


def clean_name(name: str | None) -> str | None:
    """Display form of an in-game name, matching how BrawlTools showed it.

    Strips color codes like <c4>...</c> and turns decorative letters
    (e.g. math-script) into normal ones. Emoji and other scripts are kept.
    """
    if not name:
        return name
    cleaned = unicodedata.normalize("NFKC", _COLOR_TAG.sub("", name)).strip()
    return cleaned or name


def _rank_lookup(items: list[dict]) -> dict[str, int]:
    return {bs.normalize_tag(item["tag"]): item["rank"] for item in items}


# --- Club-list board (#618) ---
# One overview message plus a fixed set of club messages, posted once and then
# edited in place on every refresh. The count never changes, so adding or
# removing a club only changes what each message holds.

CLUB_MESSAGES = 6
CLUB_CAPACITY = 30
# Keyed by channel: DEV and PROD share one database, so each keeps its own IDs.
BOARD_MESSAGES_SETTING = f"club_list_message_ids:{CLUB_LIST_CHANNEL_ID}"
BOARD_TITLE = "Remaining 7 Esports"
BOARD_FOOTER = f"Updating every 30 minutes · {SUPERCELL_DISCLAIMER}"
BOARD_COLOR = discord.Color.gold()
RANKED_TIERS = (
    "BRONZE",
    "SILVER",
    "GOLD",
    "DIAMOND",
    "MYTHIC",
    "LEGENDARY",
    "MASTERS",
    "PRO",
)


def _thousands(n: int) -> str:
    return f"{n / 1000:.1f}k"


def _flag(country_code: str) -> str:
    """'US' -> the US flag emoji."""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in country_code.upper())


def _rank_label(rank_name: str) -> str:
    """'SILVER I' -> 'Silver I'."""
    tier, _, division = rank_name.partition(" ")
    return f"{tier.title()} {division}".strip()


def _sorted_by_trophies(clubs: list[dict]) -> list[dict]:
    return sorted(
        clubs,
        key=lambda c: (c.get("snapshot") or {}).get("trophies") or 0,
        reverse=True,
    )


def _club_card(club: dict) -> str:
    e = CLUB_EMOJIS
    snap = club.get("snapshot")
    if not snap:
        return "Not fetched yet"

    ranks = []
    if snap.get("country_rank") and club.get("country_code"):
        ranks.append(f"{snap['country_rank']} in {_flag(club['country_code'])}")
    if snap.get("global_rank"):
        ranks.append(f"{e['global']} {snap['global_rank']}")

    lines = [
        f"{e['president']} {snap.get('president') or '—'}",
        f"{e['trophy']} {snap.get('trophies', 0):,}",
        f"{e['rank']} {' | '.join(ranks) if ranks else 'Not Ranked'}",
    ]
    if snap.get("min_member_trophies") is not None:
        lines.append(
            f"{e['range']} {_thousands(snap['min_member_trophies'])} - "
            f"{_thousands(snap['max_member_trophies'])}"
        )
    ranked = club.get("ranked")
    if ranked:
        lines.append(
            f"{e['ranked']} {_rank_label(ranked['min_rank_name'])} - "
            f"{_rank_label(ranked['max_rank_name'])}"
        )
    lines += [
        f"{e['required']} Req: {snap.get('required_trophies', 0):,}",
        f"{e['vice_president']} {snap.get('vice_presidents', 0)}  "
        f"{e['senior']} {snap.get('seniors', 0)}",
        f"{e['members']} {snap.get('member_count', 0)}/{CLUB_CAPACITY}",
    ]
    return "\n".join(lines)


def build_club_embeds(clubs: list[dict]) -> list[discord.Embed]:
    """CLUB_MESSAGES embeds with the clubs spread evenly, highest trophies first."""
    ordered = _sorted_by_trophies(clubs)
    per_message, extra = divmod(len(ordered), CLUB_MESSAGES)
    embeds, start = [], 0
    for i in range(CLUB_MESSAGES):
        size = per_message + (1 if i < extra else 0)
        chunk = ordered[start : start + size]
        start += size
        embed = discord.Embed(
            title=f"{BOARD_TITLE} | Club Stats" if i == 0 else None,
            color=BOARD_COLOR,
        )
        for club in chunk:
            embed.add_field(
                name=(club.get("name") or club["_id"])[:256],
                value=_club_card(club)[:1024],
                inline=True,
            )
        if not chunk:
            embed.description = "—"
        embeds.append(embed)
    embeds[-1].set_footer(text=BOARD_FOOTER)
    embeds[-1].timestamp = datetime.now(timezone.utc)
    return embeds


def _ranked_distribution(clubs: list[dict]) -> str:
    totals: dict[str, int] = {}
    for club in clubs:
        for tier, count in (
            (club.get("ranked") or {}).get("tier_counts") or {}
        ).items():
            totals[tier] = totals.get(tier, 0) + count
    players = sum(totals.values())
    if not players:
        return "No ranked data yet"
    order = {tier: i for i, tier in enumerate(RANKED_TIERS)}
    return " · ".join(
        f"{tier.title()} {round(100 * count / players)}%"
        for tier, count in sorted(totals.items(), key=lambda t: order.get(t[0], 99))
    )


def build_overview_embed(clubs: list[dict]) -> discord.Embed:
    e = CLUB_EMOJIS
    snaps = [c["snapshot"] for c in clubs if c.get("snapshot")]
    n = len(snaps) or 1

    def total(key):
        return sum(s.get(key) or 0 for s in snaps)

    members = total("member_count")
    embed = discord.Embed(title=f"{BOARD_TITLE} | Overview", color=BOARD_COLOR)
    fields = [
        ("Total Clubs", f"{e['clubs']} {len(clubs)}"),
        ("Total Trophies", f"{e['trophy']} {total('trophies'):,}"),
        ("Members", f"{e['members']} {members}/{len(clubs) * CLUB_CAPACITY}"),
        ("Average Trophies", f"{e['trophy']} {round(total('trophies') / n):,}"),
        (
            "Average Required",
            f"{e['required']} {round(total('required_trophies') / n):,}",
        ),
        (
            "Average Vice-Presidents",
            f"{e['vice_president']} {round(total('vice_presidents') / n)}",
        ),
        ("Average Seniors", f"{e['senior']} {round(total('seniors') / n)}"),
        (
            "Average Members",
            f"{e['members']} {round(members / n)}/{CLUB_CAPACITY}",
        ),
    ]
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=True)
    embed.add_field(
        name=f"{e['ranked']} Ranked Distribution",
        value=_ranked_distribution(clubs),
        inline=False,
    )
    embed.set_footer(text=BOARD_FOOTER)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


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
        """Runs after every refresh. History (#617) also hooks in here."""
        try:
            await self.update_club_board()
        except Exception as e:
            print(f"Club board update error: {e}")

    async def update_club_board(self):
        """Edit the club-list messages in place, posting only ones that don't exist yet."""
        channel = self.bot.get_channel(CLUB_LIST_CHANNEL_ID)
        if channel is None:
            print(f"Club board: channel {CLUB_LIST_CHANNEL_ID} not found")
            return

        clubs = await list_tracked_clubs()
        embeds = [build_overview_embed(clubs), *build_club_embeds(clubs)]
        try:
            stored = [
                int(i)
                for i in json.loads(await get_setting(BOARD_MESSAGES_SETTING) or "[]")
            ]
        except (TypeError, ValueError):
            stored = []

        message_ids = []
        for i, embed in enumerate(embeds):
            message_id = stored[i] if i < len(stored) else None
            if message_id is not None:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=embed)
                    message_ids.append(message_id)
                    continue
                except discord.NotFound:
                    pass  # Deleted by hand: post a replacement below.
                except discord.HTTPException as e:
                    # Keep the message and try again next refresh.
                    print(f"Club board: could not edit {message_id}: {e}")
                    message_ids.append(message_id)
                    continue
            message = await channel.send(embed=embed)
            message_ids.append(message.id)

        if message_ids != stored:
            await set_setting(
                BOARD_MESSAGES_SETTING, json.dumps([str(i) for i in message_ids])
            )

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
                    clean_name(club.get("name")) or tracked.get("name") or tag,
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
        # Each request gets a fixed slot on a schedule, so the time a request
        # takes counts toward its slot and the whole update fits the window.
        start = _monotonic()
        done = 0
        for club_tag, member_tags in members_by_club.items():
            players = []
            for member_tag in member_tags:
                try:
                    players.append(await bs.get_player(member_tag))
                except bs.BrawlStarsError as e:
                    print(f"Ranked update: player {member_tag} failed: {e}")
                done += 1
                await _pause(max(0.0, start + done * spacing - _monotonic()))
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

        clubs = await list_tracked_clubs()
        tracked_tags = {c["_id"] for c in clubs}
        found: dict[str, str] = {}
        failed: set[str] = set()
        for code in COUNTRY_CODES:
            try:
                for item in await bs.get_country_club_rankings(code):
                    tag = bs.normalize_tag(item["tag"])
                    if tag in tracked_tags:
                        found[tag] = code
            except bs.NotFoundError:
                pass  # The rankings do not cover this country.
            except bs.BrawlStarsError as e:
                print(f"Country scan: {code} failed: {e}")
                failed.add(code)
            await _pause(COUNTRY_SCAN_SPACING_SECONDS)

        if len(failed) == len(COUNTRY_CODES):
            # The API was down or rejected the key: keep every country as it
            # is and try again next hour instead of waiting a day.
            print("Country scan: every country failed, will retry")
            return False

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

        name = clean_name(club.get("name")) or tag
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
