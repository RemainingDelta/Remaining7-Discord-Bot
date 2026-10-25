"""Club-list board rendering (#618): pure functions from tracked clubs to embeds.

Two messages, like BrawlTools: the org overview and the top clubs by trophies.
The cog posts them once and edits them in place on every refresh; nothing here
talks to Discord or the database.
"""

from datetime import datetime, timezone

import discord

from features.clubs.snapshots import ClubSnapshot, TrackedClub
from features.config import CLUB_EMOJIS, CLUB_RANK_EMOJIS

CLUBS_ON_BOARD = 9  # 3 full rows of 3
CLUB_CAPACITY = 30
BOARD_TITLE = "Overview from Remaining 7 Esports"
BOARD_FOOTER = "Updating every 30 minutes. Posted at"  # Discord appends the timestamp
OVERVIEW_COLOR = discord.Color.orange()
CLUB_STATS_COLOR = discord.Color.gold()
DETAIL_COLOR = discord.Color.green()
BRAWLIFY_CLUB_URL = "https://brawlify.com/club/{}"
BRAWLIFY_PLAYER_URL = "https://brawlify.com/player/{}"
BADGE_URL = "https://cdn.brawlify.com/club-badges/regular/{}.png"
CLUB_TYPES = {"open": "Open", "inviteOnly": "Invite Only", "closed": "Closed"}


def _box(value) -> str:
    """Show a value in a code box, like BrawlTools' number pills."""
    return f"`{value}`"


def _thousands(n: int) -> str:
    return f"{n / 1000:.1f}k"


def _flag(country_code: str) -> str:
    """'US' -> the US flag emoji."""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in country_code.upper())


def _link_text(name: str) -> str:
    """Make a name safe as [text](url) link text.

    Discord shows backslash escapes literally inside link text, so names are
    sent as typed. Only square brackets, which would end the link early, are
    swapped for look-alike full-width brackets.
    """
    return name.replace("[", "［").replace("]", "］")


def _tier_icon(tier: str) -> str:
    """The icon for a ranked tier such as 'SILVER'.

    Falls back to the tier's name for a tier the API adds that has no icon
    yet, so one unknown tier can't stop the whole board from rendering.
    """
    return CLUB_RANK_EMOJIS.get(tier, tier.title())


def _rank_badge(rank_name: str) -> str:
    """'SILVER I' -> the Silver icon plus `I`, short enough for a 3-column card."""
    tier, _, division = rank_name.partition(" ")
    icon = _tier_icon(tier.upper())
    return f"{icon}{_box(division)}" if division else icon


def club_trophies(club: TrackedClub) -> int:
    """A club's trophies, or 0 before its first refresh."""
    return club["snapshot"]["trophies"] if club["snapshot"] else 0


def sorted_by_trophies(clubs: list[TrackedClub]) -> list[TrackedClub]:
    """Highest trophies first: the order of the cards and the dropdowns."""
    return sorted(clubs, key=club_trophies, reverse=True)


def _president(snap: ClubSnapshot) -> str:
    """The president's name, linked to Brawlify when the tag is known."""
    name = _link_text(snap["president"] or "—")
    if not snap.get("president_tag"):
        return name
    return f"[{name}]({BRAWLIFY_PLAYER_URL.format(snap['president_tag'].lstrip('#'))})"


def _club_card(club: TrackedClub) -> str:
    e = CLUB_EMOJIS
    tag = club["_id"].lstrip("#")
    header = f"**[{_link_text(club['name'])}]({BRAWLIFY_CLUB_URL.format(tag)})**"
    snap = club["snapshot"]
    if not snap:
        return f"{header}\nNot fetched yet"

    president = _president(snap)
    ranks = []
    if snap["country_rank"] and club["country_code"]:
        ranks.append(f"{_box(snap['country_rank'])} in {_flag(club['country_code'])}")
    if snap["global_rank"]:
        ranks.append(f"{e['global']} {_box(snap['global_rank'])}")

    trophies = f"{snap['trophies']:,}"
    required = f"{snap['required_trophies']:,}"
    members = f"{snap['member_count']}/{CLUB_CAPACITY}"
    lines = [
        header,
        f"{e['president']} {president}",
        f"{e['club_trophies']} {_box(trophies)}",
        f"{e['rank']} {' | '.join(ranks) if ranks else _box('Not Ranked')}",
    ]
    if snap["min_member_trophies"] is not None:
        lines.append(
            f"{e['trophy']} {_box(_thousands(snap['min_member_trophies']))} - "
            f"{_box(_thousands(snap['max_member_trophies']))}"
        )
    if ranked := club.get("ranked"):
        lines.append(
            f"{e['ranked']} {_rank_badge(ranked['min_rank_name'])} - "
            f"{_rank_badge(ranked['max_rank_name'])}"
        )
    lines += [
        f"{e['required']} **Req:** {_box(required)}",
        f"{e['vice_president']} {_box(snap['vice_presidents'])}  "
        f"{e['senior']} {_box(snap['seniors'])}",
        f"{e['members']} {_box(members)}",
    ]
    return "\n".join(lines)


def build_club_stats_embed(clubs: list[TrackedClub]) -> discord.Embed:
    """The top CLUBS_ON_BOARD clubs by trophies, 3 per row, like BrawlTools.

    Every other club is reached through the "Choose a Club" dropdowns (#619).
    """
    embed = discord.Embed(title=f"{BOARD_TITLE} | Club Stats", color=CLUB_STATS_COLOR)
    for club in sorted_by_trophies(clubs)[:CLUBS_ON_BOARD]:
        # Field names can't hold links, so the linked name leads the value.
        embed.add_field(name="​", value=_club_card(club), inline=True)
    if not clubs:
        embed.description = "No clubs tracked yet. Add one with `/club-add`."
    embed.set_footer(text=BOARD_FOOTER)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def _ranked_distribution(clubs: list[TrackedClub]) -> str:
    totals: dict[str, int] = {}
    for club in clubs:
        for tier, count in (
            (club.get("ranked") or {}).get("tier_counts") or {}
        ).items():
            totals[tier] = totals.get(tier, 0) + count
    players = sum(totals.values())
    if not players:
        return "No ranked data yet"
    # Known tiers in ladder order (the config is ordered), then any new ones.
    tiers = [t for t in CLUB_RANK_EMOJIS if t in totals]
    tiers += [t for t in totals if t not in CLUB_RANK_EMOJIS]
    parts = []
    for tier in tiers:
        percent = round(100 * totals[tier] / players)
        if percent:  # BrawlTools leaves out tiers that round to 0%
            parts.append(f"{_tier_icon(tier)} {_box(f'{percent}%')}")
    # Three tiers per line, like BrawlTools.
    return "\n".join(" ".join(parts[i : i + 3]) for i in range(0, len(parts), 3))


def build_overview_embed(clubs: list[TrackedClub]) -> discord.Embed:
    e = CLUB_EMOJIS
    snaps = [c["snapshot"] for c in clubs if c["snapshot"]]
    n = len(snaps) or 1

    def total(key):
        return sum(s[key] for s in snaps)

    members = total("member_count")
    total_trophies = total("trophies")
    avg_trophies = round(total_trophies / n)
    avg_required = round(total("required_trophies") / n)
    capacity = len(clubs) * CLUB_CAPACITY
    fields = [
        ("Total Clubs", f"{e['clubs']} {_box(len(clubs))}"),
        ("Total Trophies", f"{e['club_trophies']} {_box(f'{total_trophies:,}')}"),
        ("Members", f"{e['members']} {_box(f'{members}/{capacity}')}"),
        ("Average Trophies", f"{e['trophy']} {_box(f'{avg_trophies:,}')}"),
        ("Average Required", f"{e['required']} {_box(f'{avg_required:,}')}"),
        (
            "Average Vice-Presidents",
            f"{e['vice_president']} {_box(round(total('vice_presidents') / n))}",
        ),
        ("Average Seniors", f"{e['senior']} {_box(round(total('seniors') / n))}"),
        (
            "Average Members",
            f"{e['members']} {_box(f'{round(members / n)}/{CLUB_CAPACITY}')}",
        ),
    ]
    embed = discord.Embed(title=f"{BOARD_TITLE} | Overview", color=OVERVIEW_COLOR)
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=True)
    # Pad the last row so Discord keeps the 3-column grid instead of
    # stretching the final fields wide.
    for _ in range(-len(fields) % 3):
        embed.add_field(name="​", value="​", inline=True)
    embed.add_field(
        name="Ranked Distribution", value=_ranked_distribution(clubs), inline=False
    )
    embed.set_footer(text=BOARD_FOOTER)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def build_club_detail_embed(club: TrackedClub) -> discord.Embed:
    """One club's details, shown privately when it's picked from the dropdowns (#619)."""
    e = CLUB_EMOJIS
    tag = club["_id"]
    embed = discord.Embed(
        title=f"{club['name']} ({tag})",
        url=BRAWLIFY_CLUB_URL.format(tag.lstrip("#")),
        color=DETAIL_COLOR,
    )
    snap = club["snapshot"]
    if not snap:
        embed.description = "Not fetched yet. Check back after the next refresh."
        return embed

    if snap.get("badge_id"):
        embed.set_thumbnail(url=BADGE_URL.format(snap["badge_id"]))

    trophies, members = snap["trophies"], snap["member_count"]
    average = round(trophies / members) if members else 0
    sections = [
        (
            "Trophies",
            f"{e['club_trophies']} {_box(f'{trophies:,}')} "
            f"**Average** {e['trophy']} {_box(f'{average:,}')}",
        )
    ]
    if snap["min_member_trophies"] is not None:
        low, high = snap["min_member_trophies"], snap["max_member_trophies"]
        sections.append(
            ("Trophy Range", f"{e['trophy']} {_box(f'{low:,}')} - {_box(f'{high:,}')}")
        )
    required = snap["required_trophies"]
    sections += [
        ("President", _president(snap)),
        ("Required Trophies", f"{e['required']} {_box(f'{required:,}')}"),
    ]
    if club_type := snap.get("type"):
        label = CLUB_TYPES.get(club_type, club_type)
        place = (
            f" {e['region']} {_flag(club['country_code'])}"
            if club["country_code"]
            else ""
        )
        sections.append(("Type", f"{e['type']} {_box(label)}{place}"))
    sections.append(
        (
            "Members",
            f"{e['members']} {_box(f'{members}/{CLUB_CAPACITY}')}\n"
            f"{e['vice_president']} **Vice-Presidents** {_box(snap['vice_presidents'])}\n"
            f"{e['senior']} **Seniors** {_box(snap['seniors'])}",
        )
    )

    for name, value in sections:
        # BrawlTools quotes each value, which draws the bar down its left side.
        embed.add_field(name=name, value=_quote(value), inline=False)
    if description := snap.get("description"):
        # Swap backticks so a description can't close its code block early.
        safe = description.replace("`", "ˋ")
        embed.add_field(name="Description", value=f"```\n{safe}\n```", inline=False)
    return embed


def _quote(value: str) -> str:
    return "\n".join(f"> {line}" for line in value.splitlines())
