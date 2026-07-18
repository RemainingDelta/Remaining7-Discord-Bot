# Brawl Drops

## Overview
The Brawl Stars minigame has two drop types: Mega Box (10 items per open) and Starr Drop (1 item, rarity-gated). Both use `random.choices()` with weighted probabilities. All drop logic lives in `features/brawl/drops.py`. The brawler roster is loaded once at startup from `brawlers.json`.

---

## Core RNG Function

```python
def pick_weighted_item(loot_table):
    weights = [item["weight"] for item in loot_table]
    return random.choices(loot_table, weights=weights, k=1)[0]
```

Both drop types use this function. The `weight` field on each loot entry controls relative probability — higher weight = more likely.

---

## Mega Box (`/megabox`)

Opens **10 items** in a single call:

```python
async def open_mega_box(user_id: str):
    rewards_log = []
    for _ in range(10):
        item = pick_weighted_item(MEGA_BOX_LOOT)
        msg = await process_reward(user_id, item)
        rewards_log.append(msg)
    return rewards_log
```

`MEGA_BOX_LOOT` is defined in `features/config.py`. Each entry has a `type` and `weight`, plus type-specific fields:

- `coins` / `power_points` / `credits` → `amount` field
- `brawler` → `rarity` field (e.g. `"rare"`, `"epic"`)
- `gadget` / `star_power` / `hypercharge` → no additional fields (resolved at award time)

---

## Starr Drop (`/starrdrop`)

Two-stage roll:

```python
async def open_starr_drop(user_id: str):
    # Stage 1: Roll rarity tier
    rarity = random.choices(
        list(STARR_DROP_RARITIES.keys()),
        weights=list(STARR_DROP_RARITIES.values()),
        k=1
    )[0]

    # Stage 2: Roll reward from that rarity's table
    loot_table = STARR_DROP_LOOT.get(rarity)
    item = pick_weighted_item(loot_table)
    reward_msg = await process_reward(user_id, item)
    return rarity, reward_msg
```

`STARR_DROP_RARITIES` maps each rarity tier to its drop weight. `STARR_DROP_LOOT` maps each tier to its loot table. Both are defined in `features/config.py`.

Tiers (lowest to highest): `Rare → Super Rare → Epic → Mythic → Legendary → Ultra Legendary`

---

## `process_reward()` — Reward Resolution

The central award function handles all reward types:

### Currencies (`coins`, `power_points`, `credits`)
Direct DB write: `add_brawl_coins()`, `add_power_points()`, or `add_credits()`. Returns a formatted string with emoji and amount.

### Brawler
1. Filters `BRAWLER_ROSTER` by the reward's `rarity` field
2. `random.choice(eligible)` selects a specific brawler
3. `add_brawler_to_user()` returns `"new"` (not previously owned) or `"duplicate"`
4. If **new**: formatted as `{rarity_emoji} **NEW BRAWLER!** {brawler_emoji} {name} ({rarity})`
5. If **duplicate**: awards `fallback_credits` (default 100) Credits instead

### Gadget / Star Power / Hypercharge
1. Loads `user_doc["brawlers"]` from MongoDB
2. Iterates all owned brawlers to find eligible ones:
   - **Gadget**: brawler level ≥ 7, has missing gadgets
   - **Star Power**: brawler level ≥ 9, has missing star powers
   - **Hypercharge**: brawler level ≥ 11, has a `hypercharge` defined in `brawlers.json`, and it's not already owned
3. If no eligible brawlers: awards **1,000 Coins** as consolation
4. Otherwise: picks a random (brawler, ability) pair from the eligible list and calls `add_gadget_to_user()`, `add_star_power_to_user()`, or `add_hypercharge_to_user()`

---

## Brawler Roster Loading

```python
BRAWLER_ROSTER = load_brawlers()  # loaded once at module import time
```

`load_brawlers()` in `features/brawl/brawlers.py` reads `features/brawl/brawlers.json` and returns a list of `Brawler` dataclass objects with fields: `id`, `name`, `rarity`, `gadgets: list[str]`, `star_powers: list[str]`, `hypercharge: str`.

This in-memory roster is used for all eligibility checks — the bot never re-reads the JSON file after startup.

---

## Quest Trigger

After every Mega Box or Starr Drop open, `process_quest_update(user_id, channel, action_type="megabox")` is called from the `/megabox` and `/starrdrop` command handlers to increment megabox quest progress.

---

## Source File
`features/brawl/drops.py`
