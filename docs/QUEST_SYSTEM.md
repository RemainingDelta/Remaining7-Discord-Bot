# Quest System

## Overview
Every member always has exactly 4 active quests (one slot per category: `daily_message`, `weekly_message`, `daily_megabox`, `weekly_megabox`). Quest definitions live in MongoDB and are seeded at startup. Progress is tracked per-user, and completed quests are replaced instantly by a new randomly selected quest of the same category.

---

## Quest Definitions

Defined in `DEFAULT_QUESTS` inside `features/quests.py` and seeded into the `quests` MongoDB collection on `cog_load()` via `init_default_quests()`:

| Name | Target | Tokens | XP | Frequency | Category |
|------|--------|--------|----|-----------|----------|
| Daily Chatter | 80 messages | 50 | 100 | Daily | message |
| Quick Convo | 160 messages | 115 | 200 | Daily | message |
| Engaged Today | 240 messages | 250 | 300 | Daily | message |
| Mega Box Maniac | 100 box opens | 50 | 100 | Daily | megabox |
| Weekly Regular | 500 messages | 225 | 1000 | Weekly | message |
| Consistent Contributor | 750 messages | 400 | 2000 | Weekly | message |
| Server Pillar | 1000 messages | 640 | 3000 | Weekly | message |
| Mega Box Grinder | 500 box opens | 250 | 500 | Weekly | megabox |

---

## Booster Threshold Reduction

Server boosters (holders of `SERVER_BOOSTER_ROLE_ID`) get a **20% reduced target** on all quest types:

| Quest | Base Target | Booster Target |
|-------|-------------|----------------|
| Daily Chatter / Quick Convo / Engaged Today | 80 / 160 / 240 | 64 / 128 / 192 |
| Mega Box Maniac (daily) | 100 | 80 |
| Weekly Regular / Consistent Contributor / Server Pillar | 500 / 750 / 1000 | 400 / 600 / 800 |
| Mega Box Grinder (weekly) | 500 | 400 |

Mechanics:
- The booster role is checked **at assignment time** inside `assign_random_quest(user_id, q_key, is_booster)`. The reduced target (and a description rewritten with the reduced count) is stored on the `user_quests` record along with a `booster_reduced` flag — it is **not** recomputed at progress-check time.
- Because assignment is lazy (expired quests reassign on the next message/box open/`/quests`), reductions take effect at the **next quest cycle** after boosting, and revert to standard targets at the next cycle after the boost lapses. An in-flight quest keeps its stored target either way.
- `/reset-quests` deletes the user's quest doc, so the forced reassignment re-evaluates booster status at that moment.
- Reduction math: `booster_quest_target()` in `database/mongo.py` (`max(1, round(target * 0.8))`).

> When changing this perk, also update the `/booster-perks` embed in `features/general.py`.

---

## Progress Tracking

`process_quest_update(user_id, channel, action_type)` is called from:
- The `on_message` listener (with `action_type="message"`)
- After every Mega Box or Starr Drop open (with `action_type="megabox"`)

For each relevant quest slot (`daily_message` + `weekly_message` for messages; `daily_megabox` + `weekly_megabox` for box opens):

1. `get_active_quest(user_id, q_key)` — fetches the current active quest for that slot from `user_quests`
2. If no quest exists, `assign_random_quest(user_id, q_key)` randomly picks one from the `quests` collection matching the slot's frequency+category, assigns it, and returns it
3. `update_quest_progress(user_id, q_key)` — increments the progress counter by 1 and returns `(completed: bool, quest_data: dict)`
4. If completed:
   - Token reward added via `update_user_balance()`
   - XP reward added via `update_leveling_data()`
   - A "Quest Completed!" embed is sent in the channel where the completion trigger occurred
   - A new quest is auto-assigned for the same slot (the `update_quest_progress` function handles the reassignment internally)

---

## Quest Key → Slot Mapping

| Key | Frequency | Category |
|-----|-----------|----------|
| `daily_message` | Daily (resets midnight UTC) | message |
| `weekly_message` | Weekly (resets Monday midnight UTC) | message |
| `daily_megabox` | Daily | megabox |
| `weekly_megabox` | Weekly | megabox |

---

## `/quests` Display

Shows 4 progress bars, one per slot. Each bar renders as a sequence of filled/empty emoji squares representing `progress / target`. The embed also shows the quest name, description, and current reward values.

---

## Admin Reset

`/reset-quests <user>` calls `reset_user_quests(user_id)` which deletes the user's `user_quests` document. On their next message or box open, all four slots are freshly assigned.

---

## Source File
`features/quests.py` — `Quests` cog with `process_quest_update()`
