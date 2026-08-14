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
| `booster_discount_month` | str | `"YYYY-MM"` of the last booster shop discount use |
| `booster_shoutout_month` | str | `"YYYY-MM"` of the last auto-created booster shoutout ticket |
| `brawlers` | dict | Map of `brawler_id → {level, gadgets, star_powers, hypercharge, coins, power_points}` |
| `coins` | int | Brawl coins |
| `power_points` | int | Brawl power points |
| `credits` | int | Brawl credits |
| `gems` | int | Brawl gems |
| `inventory` | list | Shop items purchased |
| `queue_refunds_done` | list | Entry-id receipts guarding redemption-queue refund idempotency — an id is added atomically with the refund `$inc` (`apply_queue_refund`), so a reconcile replay after a crash is a no-op. Append-only (not pruned). |

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

Restart-recovery fields (persisted by `!starttourney`, read by the boot-time resume routine): `region`, `admin_role_original_name`, `slowmode_ends_at`, `lock_reopens_at`. The two `*_at` fields are absolute UTC deadlines so a restart can re-arm the remaining time (or act immediately if already elapsed).

---

### `tourney_staff_stats`
Per-staff per-session ticket closure counts. Indexed by `session_id + user_id`.

---

### `support_ticket_counters`
Auto-increment counters for support ticket channels. One document per ticket type (`_id = "bug"`, `"support"`, `"staff_app"`, `"partnership"`). Contains a single `count` field. Booster shoutout tickets share this collection under `_id = "booster_shoutout"`.

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
| `booster_drop_message_id` | Message ID of the live booster-channel drop; cleared on claim/expiry |
| `last_message_{user_id}` | Epoch-seconds of the user's last passive token award (20s cooldown) |
| `pending_winner_announcement` | JSON marker (`matcherino_id`, `updates_channel_id`, `expires_at`) driving the crash-safe `!endtourney` winner retry |
| `last_monthly_report_month` | `"YYYY-MM"` of the last month a tournament report was generated for (idempotent gate + catch-up) |
| `last_event_cleanup_day` | `"YYYY-MM-DD"` (ET) of the last event-channel cleanup run (missed-run logging) |

---

### `processed_poll_rewards`
Audit log for poll reward distributions. Tracks `message_id` of processed polls to prevent double-paying. This is the fast-path whole-message gate; the per-voter `reward_payouts` ledger sits **beneath** it for crash-safety when a run dies mid-loop before this gate is written.

---

### `reward_payouts`
Per-recipient, two-state ledger **shared by `/event-rewards` and `/poll-rewards`** — prevents double-paying when either command is re-run after a crash/restart. One document per recipient per source message. (Message IDs are globally-unique Discord snowflakes, so event and poll rows never collide on the composite key.)

`_id = "{message_id}:{user_id}"` (composite key; each user appears at most once per source message).

| Field | Type | Purpose |
|-------|------|---------|
| `message_id` | str | Source announcement or poll message |
| `user_id` | str | Recipient |
| `amount` | int | Tokens owed on this line |
| `admin_id` | str | Admin who ran the payout |
| `source` | str | `"event"` or `"poll"` — which command claimed the row (informational; recovery is `/give` either way) |
| `paid` | bool | `False` at claim (before the balance `$inc`), flipped `True` after it lands |
| `claimed_at` | datetime | When the row was claimed |
| `paid_at` | datetime | When confirmed paid (or resolved) |
| `manually_resolved` | bool | Set when a stuck row was cleared via `/check-stuck-payouts resolve:True` |
| `resolved_by` | str | Admin who manually resolved it |

The payout loop **claims → pays → commits** per recipient: the claim writes a `paid:False` row atomically (`find_one_and_update` + `$setOnInsert`); a pre-existing row makes the claim skip, so a re-run only pays never-claimed recipients. Rows stuck at `paid:False` (a crash between claim and `$inc`) are **never auto-repaid** — a `paid:False` row can't distinguish "crashed before the `$inc`" from "crashed after it". They are surfaced to staff by a cold-boot reconcile report and the `/check-stuck-payouts` command, and recovered manually via `/give`.

---

### `drop_claims`
Atomic single-claim guard for token supply/booster/admin drops. One document per drop **message**, keyed by the drop message's ID, recording the first (and only) claimer. Replaces the old in-memory `DropView.claimed` flag so the guard survives a restart and serializes two near-simultaneous clicks.

`_id = "{message_id}"`.

| Field | Type | Purpose |
|-------|------|---------|
| `claimed_by` | str | User ID of the winning claimer |
| `ts` | datetime | Claim time; a TTL index (`expireAfterSeconds=604800`) auto-expires the record after 7 days |

`claim_drop(message_id, user_id)` does a `find_one_and_update` + `$setOnInsert`: `None` returned means no prior record (this caller won and gets paid via `increment_user_balance`); a returned doc means it was already claimed. `ensure_drop_claims_ttl_index()` (called from `Economy.cog_load`) creates the TTL index.

---

### `redemption_queue`
FIFO queue of redemptions deferred to next month when `/redeem` exceeds the available budget. One document per queued item; `_id` is an ObjectId.

| Field | Type | Purpose |
|-------|------|---------|
| `user_id` | str | Opener (matches `users` convention) |
| `item` | str | `SHOP_DATA` key |
| `budget_usd` | float | USD cost snapshot at queue time (audit/display; processing recomputes) |
| `queued_at` | datetime | FIFO sort key |
| `claimed_at` | datetime | **Crash-safety marker** — stamped atomically *before* the ticket is created **or** before a refund is paid; absent until then |
| `channel_id` | int \| null | Ticket path only: the created ticket's channel id, recorded after creation (or `null` while claimed) |
| `refund_kind` | str | Refund path only: `"tokens"` (member left) or `"item"` (staff `/redemption-queue-remove`). Mutually exclusive with `channel_id`; routes the entry to the reconcile refund branch |

Monthly processing is **crash-safe** (claim → create ticket → record `channel_id` → remove entry), mirroring the `pending_redemptions` markers used by the interactive `/redeem` path. A claimed entry is never reprocessed by later runs, so a crash between ticket creation and entry removal can't create a duplicate ticket or double-spend the budget. The two **refund** paths (member-left drop and staff `/redemption-queue-remove`) are crash-safe the same way — claim (`refund_kind`) → apply refund → remove — but their payout is a bare `$inc` on the user doc (not an observable ticket), so idempotency comes from `apply_queue_refund` recording the entry id in `users.queue_refunds_done` **atomically with the `$inc`**. Claimed leftovers are resolved once at cold boot by `reconcile_redemption_queue()` (decidably: `refund_kind` present → pay the refund idempotently and drop; else `channel_id` present → drop; otherwise topic-scan the redemption category → drop if a ticket exists, else return the item to inventory).

---

### `scam_purge_sessions`
Crash-safety record for the scam-image cross-channel purge (`features/scam_detection.py`). One document per purge job; `_id` is an ObjectId. See `docs/SCAM_DETECTION.md` → **Crash-Safe Purge**.

| Field | Type | Purpose |
|-------|------|---------|
| `guild_id` | int | Guild being purged |
| `author_id` | int | Poster whose copies are removed |
| `image_md5` | str | MD5 the purge matches on |
| `image_size` | int | Attachment size pre-filter |
| `skip_message_id` | int | The already-deleted flagged message (skipped during purge) |
| `cutoff` | datetime | Persisted lookback window, reused on resume so a restart doesn't shift it |
| `channels` | list[int] | Immutable target list (text channels + threads) captured at session start |
| `completed` | list[int] | **Cursor** — channel ids already processed |
| `created_at` | datetime | Session creation time |

The purge writes this doc **before any deletes**, `$addToSet`s each channel into `completed` as it finishes, and deletes the doc once every channel is done. Leftovers (a crash mid-purge) are resumed once at cold boot by `scam_purge_reconcile_task` from the `completed` cursor; re-runs are safe because MD5 deletes are idempotent. **No TTL** — an unfinished session must persist until resolved.

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
