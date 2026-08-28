# Brawl Collection

## Overview
Each user has a brawler collection stored under `users.brawlers` in MongoDB — a dict mapping `brawler_id → {level, gadgets, star_powers, hypercharge, ...}`. The collection commands read this document and format it for display.

---

## User Brawler Document

```json
{
  "brawlers": {
    "shelly": {
      "level": 5,
      "gadgets": ["Fast Forward"],
      "star_powers": [],
      "hypercharge": "",
      "coins": 0,
      "power_points": 120
    },
    "colt": {
      "level": 11,
      "gadgets": ["Speedloader", "Slick Boots"],
      "star_powers": ["Magnum Special", "Slick Boots"],
      "hypercharge": "Bullet Storm"
    }
  }
}
```

---

## `/profile [user]`

Reads the full `users` document and displays:
- R7 Token balance
- Brawl currencies (Coins, Power Points, Credits, Gems)
- Collection count: `owned / total` brawlers
- Average brawler level
- Level 11 brawler count

---

## `/brawlers [user]`

Paginated 2-page embed displaying all owned brawlers grouped by rarity, with their current levels. Uses a `BrawlersView` with Previous/Next buttons.

Page 1 and Page 2 each display roughly half the roster. Each brawler entry shows: `{brawler_emoji} **{Name}** (Lvl {level})`.

Brawlers are fetched from `users.brawlers` in the DB. The full roster order is determined by `BRAWLER_ROSTER` (loaded from `brawlers.json`), sorted by rarity tier.

---

## `/brawler <brawler>`

Full details for a single brawler, resolved from `BRAWLER_ROSTER` by id or name (case-insensitive) with autocomplete over the **entire** roster (owned or not). The embed shows:

- The brawler's rarity (with its `EMOJIS_RARITIES` emoji)
- Ownership status: `✅ Owned • Lvl {level}` for a brawler in `users.brawlers`, or `❌ Not owned`
- All of the brawler's gadgets, star powers, and hypercharge from `brawlers.json` (via the `Brawler` dataclass), each marked `✅` if the caller owns it and `▫️` otherwise

An unknown/misspelled name returns an ephemeral error (no DB read, no exception). The command reuses `get_user_data()` — it does not add any new MongoDB helper.

---

## `/buy-brawler <brawler>`

1. Looks up the brawler in `BRAWLER_ROSTER` to get its rarity
2. Determines the Credits cost based on rarity (cost table defined in the command or config)
3. Checks the user has enough Credits (`get_credits(user_id)`)
4. Checks the user doesn't already own the brawler (`get_user_data()`)
5. `purchase_brawler()` deducts the Credits **and** grants the brawler in a **single atomic `update_one`** (mirroring `upgrade_brawler_level`), so a crash can never spend Credits without granting the brawler. It returns `"new"` normally, or `"duplicate"` (grants 15 Power Points instead, matching `add_brawler_to_user`) if the brawler is somehow already owned
6. Replies with a confirmation embed

---

## New User Initialization

`get_user_data()` in `database/mongo.py` upserts a new user document if one doesn't exist. The default document includes Shelly at Level 1:

```python
default_brawlers = {
    "shelly": {"level": 1, "gadgets": [], "star_powers": [], "hypercharge": ""}
}
```

This means every user who interacts with the bot for the first time automatically has Shelly — no separate setup step needed.

---

## `add_brawler_to_user(user_id, brawler_id)` Return Values

| Return | Meaning |
|--------|---------|
| `"new"` | Brawler was not owned; added to collection |
| `"duplicate"` | Already owned; caller awards Credits instead |

---

## Source File
`features/brawl/commands.py`
