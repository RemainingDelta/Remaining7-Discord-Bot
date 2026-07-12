# Database

## Overview
The bot uses MongoDB Atlas via the `motor` async driver. All database logic is centralized in `database/mongo.py` — cogs never import `motor` directly. The connection is established once at startup and shared. Every helper function is `async`, uses `await`, and makes a direct collection call. There are no ORM layers or connection pools to manage beyond what motor handles.

---

## Connection

```python
client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = client["remaining7"]  # database name
```

All collections are accessed as attributes of `db`:

```python
users_col = db["users"]
quests_col = db["quests"]
# etc.
```

---

## Collections

### `users`
Primary user document. One document per Discord user ID (`_id = str(user_id)`).

Key fields:
| Field | Type | Purpose |
|-------|------|---------|
| `balance` | int | R7 Token balance |
| `level` | int | Server level |
| `exp` | int | Total XP |
| `daily_last_claimed` | datetime | Last `/daily` claim timestamp |
| `daily_message_count` | int | Messages since last `/daily` |
| `brawlers` | dict | Map of `brawler_id → {level, gadgets, star_powers, hypercharge, coins, power_points}` |
| `coins` | int | Brawl coins |
| `power_points` | int | Brawl power points |
| `credits` | int | Brawl credits |
| `gems` | int | Brawl gems |
| `inventory` | list | Shop items purchased |

**Self-healing**: `get_user_data()` upserts a default document if one doesn't exist, including Shelly at Level 1. This means any command can safely call `get_user_data()` without checking for existence first.

---

### `user_quests`
One document per user (`_id = str(user_id)`). Contains one nested object per quest slot.

```json
{
  "_id": "123456789",
  "daily_message": {
    "quest_id": "ObjectId...",
    "progress": 45,
    "assigned_at": "2026-06-21T00:00:00Z"
  },
  "weekly_message": { ... },
  "daily_megabox": { ... },
  "weekly_megabox": { ... }
}
```

---

### `quests`
Quest definitions seeded at startup by `init_default_quests()`. Never modified at runtime. Each document:

```json
{
  "name": "Daily Chatter",
  "description": "Send 80 messages today.",
  "reward_tokens": 50,
  "reward_exp": 100,
  "target": 80,
  "frequency": "daily",
  "category": "message"
}
```

---

### `hacked_users`
Simple collection of flagged accounts. `_id = str(user_id)`. Contains just the user ID — the flag itself is presence in this collection.

---

### `blacklist`
Tournament ban list. `_id = str(user_id)`.

Fields: `reason`, `matcherino`, `alts: list[str]`, `admin_id`, `timestamp`.

---

### `payouts`
Pending staff payouts. One document per staff member with a non-zero balance.

Fields: `user_id`, `balance` (float, USD), `name`.

---

### `payout_logs`
Archived batch payout records. Each document is a batch:

Fields: `batch_id`, `users: list[{user_id, name, amount}]`, `mode` (`"split"` or `"flat"`), `timestamp`, `total`.

---

### `tourney_sessions`
One document per tournament session.

Key fields: `start_time`, `matcherino_id`, `total_tickets`, `total_messages`, `peak_queue`, `collect_data`.

---

### `tourney_staff_stats`
Per-staff per-session ticket closure counts. Indexed by `session_id + user_id`.

---

### `support_ticket_counters`
Auto-increment counters for support ticket channels. One document per ticket type (`_id = "bug"`, `"support"`, `"staff_app"`, `"partnership"`). Contains a single `count` field.

---

### `settings`
Global key-value store. `_id = key`, `value = string`.

Key entries:
| Key | Purpose |
|-----|---------|
| `budget_month_key` | `"YYYY-MM"` for current month |
| `monthly_budget` | Budget cap as float string |
| `manual_total_spent` | Cumulative USD spent this month |
| `brawlpass_redeemed_count` | Legacy per-item counter |

---

### `processed_poll_rewards`
Audit log for poll reward distributions. Tracks `message_id` of processed polls to prevent double-paying.

---

### `sticky`
Sticky message data per channel. `_id = str(channel_id)`.

Fields: `content`, `attachment_url`, `message_id` (last posted sticky message to delete on repost).

---

### `counting_state`
Single document tracking the current count game state.

Fields: `count` (int), `last_user_id` (str).

---

### `tourney_snapshots`
Bracket progress snapshots for POC data collection (optional).

Fields: `tourney_id`, `snapshot_at`, `dominant_round`, `round_position_from_end`, `match_count_in_round`, `round_duration`, `duration_per_match`, `bottleneck_count`, `time_of_day`, `day_of_week`.

---

## Helper Function Patterns

All helpers follow the same pattern — no complex abstractions:

```python
async def get_user_balance(user_id: str) -> int:
    doc = await users_col.find_one({"_id": user_id})
    if not doc:
        return 0
    return int(doc.get("balance", 0))

async def update_user_balance(user_id: str, new_balance: int) -> None:
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"balance": new_balance}},
        upsert=True
    )
```

There are 150+ functions following this pattern. To add a new field: add a helper in `mongo.py`, call it from the cog.

---

## Source File
`database/mongo.py`
