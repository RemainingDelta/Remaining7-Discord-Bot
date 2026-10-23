#!/usr/bin/env python3
"""One-time load of the org's Brawl Stars clubs into tracked_clubs (#615).

Run from the repo root with MONGO_URI and BRAWL_STARS_TOKEN set, and BOT_MODE
matching the database you mean to fill:

    python scripts/seed_tracked_clubs.py

Each tag is checked against the API before it is saved. Clubs already tracked
are reported and skipped, so running it again is safe. Later changes go
through /club-add and /club-remove.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database.mongo as mongo  # noqa: E402
from database.mongo import add_tracked_club, count_tracked_clubs  # noqa: E402
from features import brawl_stars_client as bs  # noqa: E402
from features.config import MAX_TRACKED_CLUBS  # noqa: E402

CLUB_TAGS = [
    "2YYJJV9PC",  # 7 Dwarves
    "829PVPUQ2",  # Arctic Blitz
    "2RLJC0C92",  # dragon's den
    "2PVRGRR2R",  # Toxic灵
    "2VU2L9CUP",  # Enemy Complex
    "CCQCUYJJ",  # Legendogs
    "2YGQ9C920",  # Nebulic Nomands
    "2VR98PL0C",  # Rise Of Legions
    "R9C8LPVP",  # Liars
    "2CL8P22RV",  # R7 Alpha
    "RLUUP9UP",  # ROL | Telugu
    "29LRGYYYP",  # Renaissance
    "29GUCU0V2",  # Remaining Few
    "2V8RYLRCJ",  # Sp5der
    "2G800LU08",  # Rise Of Legends
    "2GRV8LJYR",  # Remaining Nova
    "VYCJ0LQU",  # AOA|champion
    "Q229P980",  # ROL | Dynasty
    "2U2Y8QLUP",  # Overdogs
    "2PV9QUCV9",  # Royal Lords
    "VCC22GYG",  # 7 Hounds
    "2QQ8C20C2",  # Remaining Ace
    "2ULLC92CV",  # Rise of Gods
    "QQGLJU2R",  # Remaining Delta
    "2GYJ08RUR",  # Remaining Chaos
    "2L9CPLLRC",  # R7|Phantoms
    "2GV9UPGQ9",  # 7 Ogres
    "80GLC0CU9",  # Underdogs
    "CGGYGVJJ",  # Trophidogs
    "2GLCUVJ8C",  # Remaining Beta
    "29PUPV998",  # Remaining Xeno
    "2GJV9VVCJ",  # 7 Tarkans
    "2RUL2GC0G",  # Remaining David
    "2CCR2JVUC",  # R7 Kaiser
    "2JGQ9G29J",  # R7 Dark
    "2J29982VG",  # Hexlone
    "2CCP9GYR9",  # Arctic Alpine
    "2L0GLPGUR",  # Repeat 1st DIV
    "2V8QUL8Y8",  # RNS-SLIME
    "2L8GU90U2",  # Remaining 7
    "28V0GLCJG",  # Minibru
    "2VRCYQRQC",  # Chicken Crusade
    "2C2PCJR0L",  # R7 Posers
    "2YQ9RVVLQ",  # ROL | Rebels
    "2P22LR8J9",  # ROL |Meow
]


async def seed(tags: list[str]) -> list[tuple[str, str]]:
    """Validate and add each tag. Returns (normalized tag, outcome) per tag."""
    results = []
    tracked = await count_tracked_clubs()
    for raw in tags:
        tag = bs.normalize_tag(raw)
        if tracked >= MAX_TRACKED_CLUBS:
            results.append((tag, f"skipped: {MAX_TRACKED_CLUBS}-club limit reached"))
            continue
        try:
            club = await bs.get_club(tag)
        except bs.NotFoundError:
            results.append((tag, "not found"))
            continue
        except bs.BrawlStarsError as e:
            print(f"   {tag}: {type(e).__name__} ({e.reason})")
            results.append((tag, "API error"))
            continue
        if await add_tracked_club(tag, club.get("name") or tag):
            tracked += 1
            results.append((tag, "added"))
        else:
            results.append((tag, "already tracked"))
    return results


async def main() -> None:
    if mongo.db is None:
        sys.exit("❌ No database connection. Set MONGO_URI (and BOT_MODE) first.")
    try:
        results = await seed(CLUB_TAGS)
    finally:
        await bs.close()
    for tag, outcome in results:
        print(f"{tag:12} {outcome}")
    added = sum(1 for _, outcome in results if outcome == "added")
    print(f"\n{added} added, {len(results) - added} not added")


if __name__ == "__main__":
    asyncio.run(main())
