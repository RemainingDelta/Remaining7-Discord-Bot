"""The stored shape of a tracked club and the pure builders that fill it (#616).

`tracked_clubs` documents (database/mongo.py) hold a `ClubSnapshot` from the
30-minute refresh and a `RankedSummary` from the ranked update. Everything
that renders a club reads these shapes, so the optional fields below are the
only ones a reader has to handle.
"""

import re
import unicodedata
from datetime import datetime
from typing import TypedDict

from features import brawl_stars_client as bs


# Optional keys use a `total=False` subclass (Python 3.10 has no NotRequired).


class _ClubSnapshotRequired(TypedDict):
    trophies: int
    required_trophies: int
    member_count: int
    president: str | None
    vice_presidents: int
    seniors: int
    min_member_trophies: int | None  # None when the club has no members
    max_member_trophies: int | None
    country_rank: int | None  # None outside the country's top 200
    global_rank: int | None  # None outside the global top 200


class ClubSnapshot(_ClubSnapshotRequired, total=False):
    # Missing on snapshots saved before the ticket that added them.
    president_tag: str | None  # #618
    badge_id: int | None  # #619, for the badge image
    type: str  # #619: "open", "inviteOnly" or "closed"
    description: str  # #619


class RankedSummary(TypedDict):
    min_rank: int
    min_rank_name: str  # e.g. "SILVER I"
    max_rank: int
    max_rank_name: str
    tier_counts: dict[str, int]  # e.g. {"SILVER": 12, "GOLD": 5}
    players_counted: int


class _TrackedClubRequired(TypedDict):
    _id: str  # normalized tag, e.g. "#2YYJJV9PC"
    name: str
    country_code: str | None  # set by the daily country scan
    snapshot: ClubSnapshot | None  # None until the first successful refresh
    fetched_at: datetime | None
    failing_since: datetime | None


class TrackedClub(_TrackedClubRequired, total=False):
    # Added by the ranked update; None when no member has ranked data.
    ranked: RankedSummary | None


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


def build_snapshot(club: dict, country_rank, global_rank) -> ClubSnapshot:
    """The stats shown for one club, from an API club. Member names and tags are not kept."""
    members = club.get("members") or []
    trophies = [m.get("trophies", 0) for m in members]
    president = next((m for m in members if m.get("role") == "president"), None)
    return {
        "trophies": club.get("trophies", 0),
        "required_trophies": club.get("requiredTrophies", 0),
        "member_count": len(members),
        "president": clean_name(president.get("name")) if president else None,
        "president_tag": president.get("tag") if president else None,
        "vice_presidents": sum(1 for m in members if m.get("role") == "vicePresident"),
        "seniors": sum(1 for m in members if m.get("role") == "senior"),
        "min_member_trophies": min(trophies) if trophies else None,
        "max_member_trophies": max(trophies) if trophies else None,
        "country_rank": country_rank,
        "global_rank": global_rank,
        "badge_id": club.get("badgeId"),
        "type": club.get("type", ""),
        "description": club.get("description") or "",
    }


def build_ranked(players: list[dict]) -> RankedSummary | None:
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


def rank_lookup(items: list[dict]) -> dict[str, int]:
    """Tag -> rank from a rankings response."""
    return {bs.normalize_tag(item["tag"]): item["rank"] for item in items}
