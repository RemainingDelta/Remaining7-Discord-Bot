# Brawl Progression

## Overview
Each owned brawler upgrades from Level 1 to Level 11 using Coins and Power Points. At specific level thresholds, Gadgets, Star Powers, and Hypercharges unlock for separate purchase. All upgrade and ability data comes from `brawlers.json`.

---

## Upgrade Costs

Upgrade costs scale per level and are defined in `brawlers.py` or `brawlers.json`. Each level requires a certain amount of Power Points and Coins. The `/upgrade` command reads the user's current level, calculates what's needed for the next level, and shows it in an interactive dashboard.

---

## `/upgrade <brawler>`

1. Looks up the brawler in the user's collection (`get_user_data()`)
2. Checks ownership — if not owned, rejects with an error
3. Reads current level and the upgrade cost table
4. Builds an embed showing: current level, next level, PP required, Coins required
5. Attaches an `UpgradeView` with an Upgrade button
6. On button click: checks user has sufficient PP and Coins, deducts them, increments level in DB

The Upgrade button is disabled if the brawler is already at max level (11) or if the user lacks resources.

---

## Ability Unlock Levels

| Ability | Unlock Level |
|---------|-------------|
| Gadgets | Level 7 |
| Star Powers | Level 9 |
| Hypercharges | Level 11 |

These thresholds are enforced in both `process_reward()` (drop eligibility) and `/buy-ability` (purchase eligibility).

---

## `/buy-ability <brawler>`

1. Reads the brawler's available abilities from `brawlers.json` (`gadgets`, `star_powers`, `hypercharge`)
2. Cross-references against the user's currently owned abilities for that brawler
3. Checks brawler level meets the unlock threshold
4. Lists purchasable abilities with their Credits/Gems cost
5. On selection (after confirmation): `purchase_brawler_ability()` deducts the Coins **and** grants the gadget / star power / hypercharge in a **single atomic `update_one`** (mirroring `upgrade_brawler_level`), so a crash can never spend currency without granting the ability

---

## `brawlers.json` Structure

Each brawler entry:
```json
{
  "id": "shelly",
  "name": "Shelly",
  "rarity": "Starting",
  "gadgets": ["Fast Forward", "Clay Pigeon"],
  "star_powers": ["Shell Shock", "Band-Aid"],
  "hypercharge": "Hyperload"
}
```

The `hypercharge` field is a single string (one hypercharge per brawler) or empty string if none. Gadgets and Star Powers are lists since each brawler can have multiple.

---

## Progression DB Writes

| Operation | DB helper |
|-----------|-----------|
| Increment level | `update_brawler_level(user_id, brawler_id, new_level)` |
| Deduct coins | `spend_brawl_coins(user_id, amount)` |
| Deduct power points | `spend_power_points(user_id, amount)` |
| Add gadget | `add_gadget_to_user(user_id, brawler_id, gadget_name)` |
| Add star power | `add_star_power_to_user(user_id, brawler_id, sp_name)` |
| Add hypercharge | `add_hypercharge_to_user(user_id, brawler_id, hc_name)` |

---

## Source File
`features/brawl/brawlers.py`
