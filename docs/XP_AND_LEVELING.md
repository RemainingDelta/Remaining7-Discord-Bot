# XP and Leveling

## Overview
XP is earned alongside tokens in the same `on_message` listener, restricted to the same channels as passive token earning — the general chat channel (`GENERAL_CHANNEL_ID`) and the booster-only channel (`BOOSTER_CHANNEL_ID`). Level is derived from cumulative XP using a formula — it is not stored as a separate counter that increments discretely. Higher level increases the daily token reward.

---

## XP Earning

In the `on_message` listener, gated by the same channel restriction as token earning (not the 20-second token cooldown — XP accrues on every qualifying message):

1. A flat `EXP_PER_MESSAGE = 10` is awarded
2. `get_leveling_data(user_id)` fetches `(level, exp)` from the `users` collection
3. New XP total is calculated: `new_exp = exp + xp_gained`
4. New level is derived from `new_exp` using the level formula
5. `update_leveling_data(user_id, new_level, new_exp)` writes both back

Server Boosters additionally roll a **35% chance of +1 bonus XP** per general/booster-channel message (independent of the token cooldown). When changing this perk, also update the `/booster-perks` embed in `features/general.py`.

XP earning happens in the same single `on_message` handler as tokens. The two are not separate listeners — one fire updates both.

---

## Level Formula

The XP required to advance from level `N` to `N + 1` is a pure exponential:

```
required = int(100 * 1.5 ** (level - 1))
```

`_exp_required_for_level(level)` in `features/economy.py` is the **single source of truth** for this value. Both the `on_message` level-up loop and the `/level` display call it, so the "XP needed" the display shows can never diverge from the requirement the loop actually checks against — at every level. The curve grows exponentially forever with no linear phase (an earlier display-only linear phase past level 20 understated the real requirement and is gone).

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
Reads `(level, exp)` via `get_leveling_data()` and displays an embed showing the user's current level, total XP, and XP needed for the next level. The "XP needed" and progress bar are computed from `_exp_required_for_level(level)` — the same helper the level-up loop uses — so the bar reaches 100% only when the user is within one message's XP of leveling up.

### `/leaderboard level`
Paginates with `LevelsLeaderboardView` (10 per page). Uses `get_levels_page(offset, per_page)` — a MongoDB `find()` sorted by `level` descending with `exp` as the tiebreak, restricted to users that have a `level` field. Page bounds come from `get_levels_total()`, which counts the same filtered set. The viewer's own level rank is fetched with `get_user_level_rank()` and shown in the footer.

`get_user_level_rank()` reads the viewer's document directly rather than through `get_leveling_data()`, which creates a document when one is missing — ranking is a read, and making it write meant viewing this board produced field-less user documents.

The view shares `BaseLeaderboardView` with the token board, so pagination, buttons and the footer are defined once and cannot drift between the two.

---

## Source File
`features/economy.py` — `on_message` listener and `/level`, `/leaderboard level` commands
