# XP and Leveling

## Overview
XP is earned alongside tokens on every message (same `on_message` listener, same 20-second cooldown). Level is derived from cumulative XP using a formula — it is not stored as a separate counter that increments discretely. Higher level increases the daily token reward.

---

## XP Earning

In the `on_message` listener (same cooldown gate as token earning):

1. A random XP amount is chosen (exact range defined in the listener, similar to token range)
2. `get_leveling_data(user_id)` fetches `(level, exp)` from the `users` collection
3. New XP total is calculated: `new_exp = exp + xp_gained`
4. New level is derived from `new_exp` using the level formula
5. `update_leveling_data(user_id, new_level, new_exp)` writes both back

XP earning happens in the same single `on_message` handler as tokens. The two are not separate listeners — one fire updates both.

---

## Level Formula

Level is calculated from total XP. The exact formula is in `database/mongo.py` or `features/economy.py` (wherever `get_leveling_data` / `update_leveling_data` compute the level). Higher XP thresholds are required per level — the curve gets steeper as levels increase.

---

## Impact of Level

`/daily` reward scales with level:
```
tokens = 80 + (level * 5), capped at 160
```

So a Level 16+ member earns the max 160 tokens from `/daily`, while a Level 0 member earns 80.

---

## Commands

### `/level [user]`
Reads `(level, exp)` via `get_leveling_data()` and displays an embed showing the user's current level, total XP, and XP needed for the next level.

### `/levels-leaderboard [page]`
Paginates with `LevelsLeaderboardView` (10 per page). Uses `get_levels_page(offset, per_page)` — a MongoDB `find()` sorted by `exp` descending. The viewer's own level rank is fetched with `get_user_level_rank()` and shown in the footer.

---

## Source File
`features/economy.py` — `on_message` listener and `/level`, `/levels-leaderboard` commands
