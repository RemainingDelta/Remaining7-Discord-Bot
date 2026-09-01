from datetime import datetime, timedelta
import hashlib
import os
import re
import aiohttp
import motor.motor_asyncio
import certifi
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    print("⚠️ CRITICAL: MONGO_URI missing in .env or RamNaym Cloud variables.")
    db = None
else:
    try:
        # Connect to MongoDB with the Mac/SSL fix
        client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGO_URI, tlsCAFile=certifi.where()
        )
        db = client["r7_bot_db"]
        global tourney_sessions
        tourney_sessions = db["tourney_sessions"]
        print("✅ Connected to Cloud Database (MongoDB)")
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        db = None

# --- CORE USER HELPERS ---


async def get_user_data(user_id: str):
    """
    Fetches user data and performs self-healing checks
    to ensure Shelly is always present.
    """
    if db is None:
        return None

    data = await db.users.find_one({"_id": str(user_id)})

    if not data:
        # New User: Create with Shelly Level 1 and empty lists
        new_user = {
            "_id": str(user_id),
            "currencies": {"coins": 100, "power_points": 0, "credits": 0, "gems": 0},
            "brawlers": {"shelly": {"level": 1, "gadgets": [], "star_powers": []}},
        }
        await db.users.insert_one(new_user)
        return new_user

    # --- SELF-HEALING LOGIC ---
    # Check if user is missing Shelly (case-insensitive check)
    brawlers = data.get("brawlers", {})
    has_shelly = any(k.lower() == "shelly" for k in brawlers.keys())

    if not has_shelly:
        await db.users.update_one(
            {"_id": str(user_id)},
            {
                "$set": {
                    "brawlers.shelly": {"level": 1, "gadgets": [], "star_powers": []}
                }
            },
        )

    return data


async def get_user_balance(user_id: str) -> int:
    doc = await get_user_data(user_id)
    return doc.get("balance", 0)


async def update_user_balance(user_id: str, amount: int):
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$set": {"balance": amount}}, upsert=True
    )


async def increment_user_balance(user_id: str, amount: int):
    """Atomically increments a user's balance using $inc."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": str(user_id)}, {"$inc": {"balance": amount}}, upsert=True
    )


async def claim_daily_reward(
    user_id: str, amount: int, cutoff_ts: float, now_ts: float
):
    """Atomically grant the daily reward and stamp the cooldown in one write.

    The token grant ($inc balance) and the cooldown stamp ($set daily_last_claimed)
    happen in a single find_one_and_update guarded by a cooldown predicate, so a crash
    can no longer land between "tokens granted" and "cooldown stamped" and let the user
    claim twice. Returns the updated user doc (with the new balance) if this call won
    the claim, or None if the user has already claimed since cutoff_ts (a concurrent or
    duplicate invoke). Caller must ensure the user doc exists first — get_user_data /
    get_user_balance create it — since upsert is intentionally off here (an upsert whose
    filter excludes an existing doc would raise a duplicate-key error).

    Note: only the cooldown lives on the user doc. The daily message counter stays in
    settings (daily_msg_count_{uid}); it doesn't need to be part of this atomic guard.
    """
    if db is None:
        return None
    return await db.users.find_one_and_update(
        {
            "_id": str(user_id),
            "$or": [
                {"daily_last_claimed": {"$exists": False}},
                {"daily_last_claimed": {"$lt": cutoff_ts}},
            ],
        },
        {"$inc": {"balance": int(amount)}, "$set": {"daily_last_claimed": now_ts}},
        return_document=True,  # AFTER — surface the new balance for the embed
    )


# --- POLL REWARD HELPERS ---


async def is_poll_reward_processed(message_id: str) -> bool:
    """Checks if a poll reward has already been distributed for this message."""
    if db is None:
        return False
    doc = await db.processed_poll_rewards.find_one({"_id": str(message_id)})
    return doc is not None


async def mark_poll_reward_processed(
    message_id: str,
    admin_id: str,
    answer_text: str,
    amount: int,
    voter_count: int,
):
    """Records that poll rewards were distributed for this message."""
    if db is None:
        return
    await db.processed_poll_rewards.insert_one(
        {
            "_id": str(message_id),
            "admin_id": str(admin_id),
            "answer_text": answer_text,
            "amount_per_user": amount,
            "voter_count": voter_count,
            "total_distributed": amount * voter_count,
            "processed_at": datetime.utcnow(),
        }
    )


# --- REWARD PAYOUT LEDGER (per-recipient, two-state, crash-safe) ---
# Shared by /event-rewards and /poll-rewards. Message IDs are globally-unique
# Discord snowflakes, so event and poll rows never collide on the composite key.


async def claim_reward_payout(
    message_id: str, user_id: str, amount: float, admin_id: str, source: str = "event"
) -> bool:
    """Atomically claim one recipient's payout, writing paid:False before payment.

    Returns True if this call newly claimed the payout (caller should pay now).
    Returns False if a doc already exists for this message+user (already paid, or
    claimed-but-stuck) — the caller should skip it. Keyed message_id+user_id so a
    re-run after a crash skips already-handled users instead of double-paying.
    `source` ("event"/"poll"/"payout") is informational, so a stuck-row report
    can give source-correct recovery steps. `amount` is stored as passed (int
    tokens for event/poll, float currency for payouts) — do not truncate.
    """
    if db is None:
        return False
    key = f"{message_id}:{user_id}"
    result = await db.reward_payouts.find_one_and_update(
        {"_id": key},
        {
            "$setOnInsert": {
                "_id": key,
                "message_id": str(message_id),
                "user_id": str(user_id),
                "amount": amount,
                "admin_id": str(admin_id),
                "source": str(source),
                "paid": False,
                "claimed_at": datetime.utcnow(),
            }
        },
        upsert=True,
        return_document=False,
    )
    return result is None  # None = doc didn't exist before — we own this payout


async def mark_reward_paid(message_id: str, user_id: str):
    """Commit point: flag the recipient's tokens as confirmed paid."""
    if db is None:
        return
    await db.reward_payouts.update_one(
        {"_id": f"{message_id}:{user_id}"},
        {"$set": {"paid": True, "paid_at": datetime.utcnow()}},
    )


async def get_stuck_reward_payouts(older_than_seconds: int = 60) -> list:
    """Rows claimed but never confirmed paid — a crash between the claim and the
    balance $inc. The age gate skips in-flight payouts so an on-demand check run
    during a live payout doesn't false-positive on a row about to be committed.
    """
    if db is None:
        return []
    cutoff = datetime.utcnow() - timedelta(seconds=older_than_seconds)
    cursor = db.reward_payouts.find({"paid": False, "claimed_at": {"$lt": cutoff}})
    return await cursor.to_list(length=None)


async def resolve_stuck_reward_payout(message_id: str, user_id: str, resolver_id: str):
    """Marks a stuck row resolved after a staff manual /give, so it stops being
    reported. Records who resolved it for audit — does NOT move any tokens.
    """
    if db is None:
        return
    await db.reward_payouts.update_one(
        {"_id": f"{message_id}:{user_id}", "paid": False},
        {
            "$set": {
                "paid": True,
                "manually_resolved": True,
                "resolved_by": str(resolver_id),
                "paid_at": datetime.utcnow(),
            }
        },
    )


# --- REDEMPTION CLOSURE GUARD (single-state, crash-safe) ---


async def claim_redemption_closure(channel_id, action: str) -> bool:
    """Atomically claim a redemption-ticket close so its financial side effect (refund
    or budget deduction) runs at most once, even if the persistent close button is
    re-clicked after a crash that killed the bot before the channel was deleted.

    Returns True only if this call newly owns the closure — the caller should run the
    money + transcript, then delete the channel. Returns False if a doc already exists
    (a previous attempt already ran the money) — the caller should skip straight to
    deleting the channel. Keyed by channel id; no boot reconcile is needed because the
    surviving channel and its live buttons ARE the retry path (staff naturally re-click,
    and this guard makes the re-click a delete-only no-op on the finances).
    """
    if db is None:
        return False
    key = str(channel_id)
    result = await db.redemption_closures.find_one_and_update(
        {"_id": key},
        {
            "$setOnInsert": {
                "_id": key,
                "action": str(action),
                "claimed_at": datetime.utcnow(),
            }
        },
        upsert=True,
        return_document=False,
    )
    return result is None  # None = doc didn't exist before — we own this closure


# --- LEVELING HELPERS ---


async def get_leveling_data(user_id: str):
    doc = await get_user_data(user_id)
    return doc.get("level", 1), doc.get("exp", 0)


async def update_leveling_data(user_id: str, level: int, exp: int):
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$set": {"level": level, "exp": exp}}, upsert=True
    )


# --- INVENTORY & SETTINGS HELPERS ---


async def add_item_token(user_id: str, item_name: str, quantity: int = 1):
    """Adds an item to the user's inventory."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$inc": {f"inventory.{item_name}": quantity}}, upsert=True
    )


async def get_booster_discount_month(user_id: str) -> str | None:
    """Returns the "YYYY-MM" month key of the user's last booster discount use."""
    doc = await get_user_data(user_id)
    return doc.get("booster_discount_month")


async def set_booster_discount_month(user_id: str, month_key: str):
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$set": {"booster_discount_month": month_key}}, upsert=True
    )


async def get_booster_shoutout_month(user_id: str) -> str | None:
    """Returns the "YYYY-MM" month key of the user's last booster shoutout ticket."""
    doc = await get_user_data(user_id)
    return doc.get("booster_shoutout_month")


async def set_booster_shoutout_month(user_id: str, month_key: str):
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$set": {"booster_shoutout_month": month_key}}, upsert=True
    )


async def claim_booster_shoutout_month(user_id: str, month_key: str):
    """Atomically claim this month's booster-shoutout slot for the user.

    Returns (won, previous): `won` is True if this caller set the marker (the doc
    was not already at month_key), False if another concurrent boost event already
    claimed it. `previous` is the marker's prior value, so the caller can roll it
    back with set_booster_shoutout_month if the channel creation then fails —
    preserving the "retry later this month" intent the old set-after-success code had.

    Closes the check-then-set race in on_member_update where two rapid boost events
    both read no marker and each create a ticket. The user doc is ensured first
    (get_user_data upserts it) because the $ne filter would make an upsert here try
    to insert a duplicate _id.
    """
    if db is None:
        return True, None
    await get_user_data(user_id)  # ensure the doc exists (upsert-unsafe filter below)
    before = await db.users.find_one_and_update(
        {"_id": str(user_id), "booster_shoutout_month": {"$ne": month_key}},
        {"$set": {"booster_shoutout_month": month_key}},
        return_document=False,  # BEFORE — None means the predicate excluded the doc
    )
    if before is None:
        return False, None  # already claimed this month
    return True, before.get("booster_shoutout_month")


async def get_item_count(user_id: str, item_name: str) -> int:
    """Checks how many of an item a user has."""
    doc = await get_user_data(user_id)
    inventory = doc.get("inventory", {})
    return inventory.get(item_name, 0)


async def remove_item_token(user_id: str, item_name: str, quantity: int = 1):
    """Removes an item from inventory."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$inc": {f"inventory.{item_name}": -quantity}}
    )


async def purchase_item(
    user_id: str, item_name: str, price: int, discount_month: str | None = None
) -> bool:
    """Atomically deduct `price` tokens and grant one `item_name`, only if the
    balance still covers the price. Optionally stamp the booster-discount month in
    the same write. All three fields live on the one users doc, so a single
    update_one is atomic — a crash can never deduct without granting (or vice
    versa), and the `balance >= price` guard blocks double-spend / negative
    balances under concurrency. Returns False (no-op) if the balance no longer
    covers the price."""
    if db is None:
        return False
    update = {"$inc": {"balance": -price, f"inventory.{item_name}": 1}}
    if discount_month is not None:
        update["$set"] = {"booster_discount_month": discount_month}
    result = await db.users.update_one(
        {"_id": user_id, "balance": {"$gte": price}},
        update,
    )
    return result.modified_count > 0


# --- PENDING REDEMPTION HELPERS ---
# Crash-safety for /redeem: a durable marker written atomically with the token
# removal, reconciled once at startup so a hard crash mid-redeem can never lose
# the item silently (see reconcile_pending_redemptions in features/economy.py).


async def begin_pending_redemption(
    user_id: str, item: str, budget_usd: float
) -> str | None:
    """Atomically consume one item token and record a pending-redemption marker.

    The decrement and the marker are a single-document update, so there is no
    window where the token is gone without a durable marker (or vice versa). The
    conditional match also prevents two concurrent /redeem calls from driving the
    inventory below zero. Returns the pending id, or None if the user no longer
    owns the item (caller should abort).
    """
    if db is None:
        return None
    pending_id = str(ObjectId())
    result = await db.users.update_one(
        {"_id": user_id, f"inventory.{item}": {"$gte": 1}},
        {
            "$inc": {f"inventory.{item}": -1},
            "$push": {
                "pending_redemptions": {
                    "id": pending_id,
                    "item": item,
                    "budget_usd": budget_usd,
                    "channel_id": None,
                    "created_at": datetime.utcnow(),
                }
            },
        },
    )
    return pending_id if result.modified_count else None


async def set_pending_redemption_channel(
    user_id: str, pending_id: str, channel_id: int
):
    """Record the created ticket's channel id on the pending marker, so a crash
    after ticket creation is decidable on reconcile (ticket exists → no refund)."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"pending_redemptions.$[e].channel_id": channel_id}},
        array_filters=[{"e.id": pending_id}],
    )


async def clear_pending_redemption(user_id: str, pending_id: str):
    """Remove a pending-redemption marker by id (happy-path cleanup or reconcile)."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id},
        {"$pull": {"pending_redemptions": {"id": pending_id}}},
    )


async def get_all_pending_redemptions() -> list[dict]:
    """Returns every outstanding pending-redemption marker, flattened to rows of
    {user_id, id, item, budget_usd, channel_id, created_at}."""
    if db is None:
        return []
    rows: list[dict] = []
    cursor = db.users.find(
        {"pending_redemptions": {"$exists": True, "$ne": []}},
        {"pending_redemptions": 1},
    )
    async for doc in cursor:
        for entry in doc.get("pending_redemptions", []):
            rows.append({"user_id": doc["_id"], **entry})
    return rows


async def get_setting(key: str, default: str = None):
    if db is None:
        return default
    doc = await db.settings.find_one({"_id": key})
    return doc["value"] if doc else default


async def set_setting(key: str, value: str):
    if db is None:
        return
    await db.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)


async def ensure_drop_claims_ttl_index():
    """TTL index so per-drop claim records auto-expire ~7 days after creation.
    Drops are single-claim and infrequent, but without this the records would
    accumulate forever; 7 days is far longer than any drop stays live."""
    if db is None:
        return
    await db.drop_claims.create_index("ts", expireAfterSeconds=604800)


async def claim_drop(message_id: str, user_id: str) -> bool:
    """Atomically record the first claimer of a supply/booster/admin drop.

    Returns True if this caller won the claim (should be paid), False if the drop
    was already claimed. Keyed by the drop's message id, so it survives a restart —
    unlike the in-memory DropView.claimed flag it replaces — and serializes the
    race between two near-simultaneous clicks (both pass the old in-memory guard
    because the claim callback awaits a defer before checking it). Same
    find_one_and_update / $setOnInsert pattern as acquire_scam_detection_lock.
    """
    if db is None:
        return True  # DB down: nothing persists anyway, let the click through
    before = await db.drop_claims.find_one_and_update(
        {"_id": str(message_id)},
        {
            "$setOnInsert": {
                "_id": str(message_id),
                "claimed_by": str(user_id),
                "ts": datetime.utcnow(),
            }
        },
        upsert=True,
        return_document=False,
    )
    return before is None  # None means it didn't exist before — we claimed it


# --- REDEMPTION QUEUE HELPERS ---


async def add_redemption_queue_entry(
    user_id: str, item: str, budget_usd: float
) -> str | None:
    """Queues a redemption for the next month. Returns the entry id."""
    if db is None:
        return None
    result = await db.redemption_queue.insert_one(
        {
            "user_id": user_id,
            "item": item,
            "budget_usd": budget_usd,
            "queued_at": datetime.utcnow(),
        }
    )
    return str(result.inserted_id)


async def get_redemption_queue() -> list[dict]:
    """Returns all queued redemptions in FIFO order."""
    if db is None:
        return []
    return await db.redemption_queue.find({}).sort("queued_at", 1).to_list(length=None)


async def remove_redemption_queue_entry(entry_id: str) -> dict | None:
    """Removes a queue entry by id. Returns the removed document, or None."""
    if db is None:
        return None
    try:
        oid = ObjectId(entry_id)
    except (InvalidId, TypeError):
        return None
    return await db.redemption_queue.find_one_and_delete({"_id": oid})


# Two-state, crash-safe queue fulfilment (mirrors the pending_redemptions trio
# above): the queue processor claims an entry before creating its ticket and
# records the channel after, so a crash between the create and the removal is
# decidable on reconcile instead of re-creating a duplicate ticket. See
# reconcile_redemption_queue in features/economy.py.


async def claim_redemption_queue_entry(entry_id: str) -> bool:
    """Atomically mark a queue entry as ticket-creation-in-progress.

    Sets `claimed_at` only if it is not already set, in one atomic op. Returns
    True if we claimed it (was unclaimed → we own the ticket creation), or False
    if an earlier — possibly crashed — run already claimed it, in which case the
    caller must skip it so a restart can never create a second ticket.
    """
    if db is None:
        return False
    try:
        oid = ObjectId(entry_id)
    except (InvalidId, TypeError):
        return False
    result = await db.redemption_queue.find_one_and_update(
        {"_id": oid, "claimed_at": {"$exists": False}},
        {"$set": {"claimed_at": datetime.utcnow(), "channel_id": None}},
    )
    return result is not None  # None = filter didn't match → already claimed


async def set_redemption_queue_entry_channel(entry_id: str, channel_id: int):
    """Record the created ticket's channel id on a claimed queue entry, so a
    crash after ticket creation is decidable on reconcile (channel_id present →
    ticket exists → no refund)."""
    if db is None:
        return
    try:
        oid = ObjectId(entry_id)
    except (InvalidId, TypeError):
        return
    await db.redemption_queue.update_one(
        {"_id": oid}, {"$set": {"channel_id": channel_id}}
    )


async def get_stuck_redemption_queue_entries() -> list[dict]:
    """Queue entries claimed for ticket creation but never removed — a crash
    between the claim and the entry removal. Resolved once at cold boot by
    reconcile_redemption_queue. No age gate: the reconcile is cold-boot only, so
    nothing is in flight."""
    if db is None:
        return []
    return await db.redemption_queue.find({"claimed_at": {"$exists": True}}).to_list(
        length=None
    )


async def claim_redemption_queue_refund(entry_id: str, kind: str) -> dict | None:
    """Atomically claim a queue entry for REFUND (not ticket creation).

    Stamps `claimed_at` + `refund_kind` only if the entry is unclaimed, in one op.
    Unlike claim_redemption_queue_entry it does NOT set `channel_id`, so the
    cold-boot reconcile routes it to the refund branch (ahead of the channel_id /
    topic-scan ticket logic). Returns the updated doc (for its user_id/item) if we
    newly claimed it, or None if the entry was not found or was already claimed —
    in which case the caller must not pay (a restart's reconcile, or a racing
    staff/queue action, owns it).
    """
    if db is None:
        return None
    try:
        oid = ObjectId(entry_id)
    except (InvalidId, TypeError):
        return None
    return await db.redemption_queue.find_one_and_update(
        {"_id": oid, "claimed_at": {"$exists": False}},
        {"$set": {"claimed_at": datetime.utcnow(), "refund_kind": kind}},
        return_document=True,  # AFTER — surface user_id/item for the payout
    )


async def apply_queue_refund(
    user_id: str, entry_id: str, *, item: str | None = None, tokens: int = 0
) -> bool:
    """Idempotently pay a claimed queue refund and record its receipt in one write.

    Grants the item and/or tokens AND adds `entry_id` to `queue_refunds_done` in a
    single atomic update gated by `queue_refunds_done: {$ne: entry_id}`, so a
    re-run with the same entry_id (a reconcile after a crash between pay and entry
    removal) is a no-op — the $inc and its receipt land together or not at all.
    Mirrors claim_daily_reward (atomic $inc + guard on the users doc). Returns True
    if this call performed the payout, False if it was already applied.

    The user doc is ensured to exist first via get_user_data: upsert is off here
    (an upsert whose $ne filter excludes an existing doc raises a duplicate-key
    error on _id), so a missing doc would otherwise make the refund silently
    no-op. Owning that precondition here keeps callers from having to remember it.
    """
    if db is None:
        return False
    await get_user_data(str(user_id))  # pre-create so the upsert-off write lands
    inc = {}
    if item:
        inc[f"inventory.{item}"] = 1
    if tokens:
        inc["balance"] = tokens
    update: dict = {"$addToSet": {"queue_refunds_done": entry_id}}
    if inc:
        update["$inc"] = inc
    result = await db.users.update_one(
        {"_id": str(user_id), "queue_refunds_done": {"$ne": entry_id}}, update
    )
    return result.modified_count > 0


# --- SCAM PURGE SESSION HELPERS ---
#
# Crash-safe cross-channel purge (mirrors the redemption-queue crash-safety
# idiom above). When a scam image is detected, the purge session records the
# full target channel list and a `completed` cursor before any deletes start,
# and marks each channel done as it finishes, so a crash mid-purge is resumable
# on cold boot instead of silently abandoning the remaining channels. See
# reconcile_scam_purge_sessions in features/scam_detection.py.


async def create_scam_purge_session(
    guild_id: int,
    author_id: int,
    image_md5: str,
    image_size: int,
    skip_message_id: int,
    cutoff: datetime,
    channel_ids: list[int],
) -> str | None:
    """Persist a purge job before any deletes, so an interrupted purge can be
    resumed. Returns the session id, or None if the DB is unavailable."""
    if db is None:
        return None
    result = await db.scam_purge_sessions.insert_one(
        {
            "guild_id": guild_id,
            "author_id": author_id,
            "image_md5": image_md5,
            "image_size": image_size,
            "skip_message_id": skip_message_id,
            "cutoff": cutoff,
            "channels": channel_ids,
            "completed": [],
            "created_at": datetime.utcnow(),
        }
    )
    return str(result.inserted_id)


async def mark_scam_purge_channel_done(session_id: str, channel_id: int):
    """Advance the completed cursor by one channel. Idempotent via $addToSet so
    a resumed run can't record a channel twice."""
    if db is None:
        return
    try:
        oid = ObjectId(session_id)
    except (InvalidId, TypeError):
        return
    await db.scam_purge_sessions.update_one(
        {"_id": oid}, {"$addToSet": {"completed": channel_id}}
    )


async def delete_scam_purge_session(session_id: str) -> dict | None:
    """Remove a purge session once every target channel is done. Returns the
    removed document, or None."""
    if db is None:
        return None
    try:
        oid = ObjectId(session_id)
    except (InvalidId, TypeError):
        return None
    return await db.scam_purge_sessions.find_one_and_delete({"_id": oid})


async def get_incomplete_scam_purge_sessions() -> list[dict]:
    """Purge sessions that were never finished — a crash between session
    creation and its deletion. Resolved once at cold boot by
    reconcile_scam_purge_sessions. No age gate: the reconcile is cold-boot only,
    so nothing is in flight, and sessions must persist until resolved."""
    if db is None:
        return []
    return await db.scam_purge_sessions.find({}).to_list(length=None)


# --- COUNTING HELPERS ---


async def get_counting_state() -> dict:
    if db is None:
        return {"current_count": 0, "last_user_id": None}
    doc = await db.counting.find_one({"_id": "state"})
    if not doc:
        return {"current_count": 0, "last_user_id": None}
    return {
        "current_count": doc.get("current_count", 0),
        "last_user_id": doc.get("last_user_id"),
    }


async def update_counting_state(current_count: int, last_user_id: int | None):
    if db is None:
        return
    await db.counting.update_one(
        {"_id": "state"},
        {
            "$set": {
                "current_count": current_count,
                "last_user_id": last_user_id,
            }
        },
        upsert=True,
    )


# --- STORY HELPERS ---

# Seeded so users can't smuggle multi-word entries like "I_am_a_noob"
# past the one-word check. Applies only until a banned_chars doc exists.
STORY_DEFAULT_BANNED_CHARS = ["_"]

STORY_BANNED_WORDS_URL = (
    "https://raw.githubusercontent.com/LDNOOBW/"
    "List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words/master/en"
)


def parse_banned_words(text: str) -> list[str]:
    """Parse a newline-delimited word list into a deduped, lowercased list,
    skipping blank and comment lines."""
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        word = line.strip().lower()
        if not word or word.startswith("#") or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


async def seed_default_banned_words() -> bool:
    """Fetch the default profanity list from a public URL and store it in
    story_config once. No-op if a banned_words document already exists (so staff
    edits are never clobbered), if there's no DB, or if the fetch fails. Returns
    True only when it actually seeds. The word list itself is never committed to
    this repo; only its source URL lives here."""
    if db is None:
        return False
    if await db.story_config.find_one({"_id": "banned_words"}):
        return False
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(STORY_BANNED_WORDS_URL) as resp:
                resp.raise_for_status()
                text = await resp.text()
    except Exception as e:
        print(f"⚠️ Story: could not fetch default banned-words list: {e}")
        return False
    words = parse_banned_words(text)
    if not words:
        return False
    await db.story_config.update_one(
        {"_id": "banned_words"}, {"$set": {"items": words}}, upsert=True
    )
    print(f"✅ Story: seeded {len(words)} default banned words")
    return True


async def get_story_state() -> dict:
    if db is None:
        return {"words": [], "last_user_id": None, "active": False}
    doc = await db.story.find_one({"_id": "state"})
    if not doc:
        return {"words": [], "last_user_id": None, "active": False}
    return {
        "words": doc.get("words", []),
        "last_user_id": doc.get("last_user_id"),
        "active": doc.get("active", False),
    }


async def set_story_active(active: bool):
    if db is None:
        return
    await db.story.update_one(
        {"_id": "state"}, {"$set": {"active": active}}, upsert=True
    )


async def append_story_word(word: str, user_id: int):
    if db is None:
        return
    await db.story.update_one(
        {"_id": "state"},
        {
            "$push": {"words": word},
            "$set": {"last_user_id": user_id},
        },
        upsert=True,
    )


async def reset_story():
    """Archive the current story (if any words) to story_archive, then clear
    the live state document."""
    if db is None:
        return
    doc = await db.story.find_one({"_id": "state"})
    if doc and doc.get("words"):
        await db.story_archive.insert_one(
            {
                "words": doc.get("words", []),
                "archived_at": datetime.utcnow(),
            }
        )
    await db.story.delete_one({"_id": "state"})


async def get_story_banlist(kind: str) -> list[str]:
    """kind is 'banned_words' or 'banned_chars'. Returns the seeded default
    only when no config document exists yet. The banned_words list has no
    in-repo default — it's fetched into the DB by seed_default_banned_words()."""
    default = STORY_DEFAULT_BANNED_CHARS if kind == "banned_chars" else []
    if db is None:
        return list(default)
    doc = await db.story_config.find_one({"_id": kind})
    if not doc:
        return list(default)
    return doc.get("items", [])


async def add_story_banlist_item(kind: str, item: str) -> bool:
    """Returns True if added, False if already present (or no DB)."""
    if db is None:
        return False
    items = await get_story_banlist(kind)
    if item in items:
        return False
    items.append(item)
    await db.story_config.update_one(
        {"_id": kind}, {"$set": {"items": items}}, upsert=True
    )
    return True


async def remove_story_banlist_item(kind: str, item: str) -> bool:
    """Returns True if removed, False if not present (or no DB)."""
    if db is None:
        return False
    items = await get_story_banlist(kind)
    if item not in items:
        return False
    items.remove(item)
    await db.story_config.update_one(
        {"_id": kind}, {"$set": {"items": items}}, upsert=True
    )
    return True


# --- LEADERBOARD HELPERS ---


# get_user_data creates docs holding only _id/currencies/brawlers, so plenty of
# users have no balance/level/exp at all. Mongo sorts missing fields last under
# -1, which parked those docs on the final pages of both boards. Filtering them
# out here keeps the boards to users who actually have a score.
HAS_BALANCE = {"balance": {"$exists": True}}
HAS_LEVEL = {"level": {"$exists": True}}


async def get_leaderboard_page(offset: int, limit: int):
    """Get a slice of users sorted by balance."""
    if db is None:
        return []
    cursor = db.users.find(HAS_BALANCE).sort("balance", -1).skip(offset).limit(limit)
    return await cursor.to_list(length=limit)


async def get_levels_page(offset: int, limit: int):
    """Get a slice of users sorted by level then exp."""
    if db is None:
        return []
    # Sort by level DESC, then exp DESC
    cursor = (
        db.users.find(HAS_LEVEL)
        .sort([("level", -1), ("exp", -1)])
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_leaderboard_total():
    """Counts only users the token board actually pages over."""
    if db is None:
        return 0
    return await db.users.count_documents(HAS_BALANCE)


async def get_levels_total():
    """Counts only users the level board actually pages over."""
    if db is None:
        return 0
    return await db.users.count_documents(HAS_LEVEL)


async def get_user_rank(user_id: str) -> int:
    """
    Calculates rank by checking the 'users' collection.
    Handles String vs Int ID mismatch to prevent Rank 0 errors.
    """
    if db is None:
        return 0

    # 1. Ensure we look in the 'users' collection
    collection = db["users"]

    # 2. Try to find the user to get their balance
    user_doc = await collection.find_one({"_id": str(user_id)})

    # If not found, try Integer (legacy data fix)
    if not user_doc:
        try:
            user_doc = await collection.find_one({"_id": int(user_id)})
        except ValueError:
            pass

    # 3. Determine the balance (default 0 if not found)
    user_balance = user_doc.get("balance", 0) if user_doc else 0

    # 4. Count how many people have strictly MORE money
    higher_balance_count = await collection.count_documents(
        {"balance": {"$gt": user_balance}}
    )

    # 5. Rank is the number of people above you + 1
    return higher_balance_count + 1


async def get_user_level_rank(user_id: str):
    if db is None:
        return 0
    # Read the viewer directly rather than via get_leveling_data -> get_user_data,
    # which *inserts* a doc when one is missing. Ranking is a read; making it
    # write meant merely viewing the level board minted the field-less documents
    # that then had to be filtered back out of both boards.
    doc = await db.users.find_one({"_id": str(user_id)})
    lvl = doc.get("level", 1) if doc else 1
    exp = doc.get("exp", 0) if doc else 0
    # Complex count: People with higher level OR (same level AND higher exp)
    count = await db.users.count_documents(
        {"$or": [{"level": {"$gt": lvl}}, {"level": lvl, "exp": {"$gt": exp}}]}
    )
    return count + 1


# --- SUPPLY DROP LEADERBOARD HELPERS ---

# Users only appear on the supply-drop board once they have actually claimed a
# drop. `supply_drops_total` is a denormalized running sum of the two per-type
# counters, kept in step by increment_supply_drop_count, so the board can page
# and sort with a plain find().sort() like the token board rather than summing
# the two fields on every read.
HAS_SUPPLY_DROPS = {"supply_drops_total": {"$gt": 0}}


async def increment_supply_drop_count(user_id: str, is_booster: bool):
    """Atomically record one claimed supply drop for the leaderboard.

    Bumps the per-type counter (`supply_drops_booster` or `supply_drops_normal`)
    and the denormalized `supply_drops_total` in a single $inc. Tracking starts
    from zero: drops claimed before this feature shipped are not backfilled.
    """
    if db is None:
        return
    field = "supply_drops_booster" if is_booster else "supply_drops_normal"
    await db.users.update_one(
        {"_id": str(user_id)},
        {"$inc": {field: 1, "supply_drops_total": 1}},
        upsert=True,
    )


async def get_supply_drops_page(offset: int, limit: int):
    """Get a slice of users sorted by their total supply drops."""
    if db is None:
        return []
    cursor = (
        db.users.find(HAS_SUPPLY_DROPS)
        .sort("supply_drops_total", -1)
        .skip(offset)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_supply_drops_total():
    """Counts only users the supply-drop board actually pages over."""
    if db is None:
        return 0
    return await db.users.count_documents(HAS_SUPPLY_DROPS)


async def get_user_supply_drop_rank(user_id: str) -> int:
    """Rank a user by total supply drops (people with strictly more, + 1)."""
    if db is None:
        return 0
    doc = await db.users.find_one({"_id": str(user_id)})
    total = doc.get("supply_drops_total", 0) if doc else 0
    higher = await db.users.count_documents({"supply_drops_total": {"$gt": total}})
    return higher + 1


# --- SECURITY / HACKED USER TRACKING ---


async def add_hacked_user(user_id: str, reason: str = "Compromised Account"):
    """Tags a user as hacked in the database."""
    await db.hacked_users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "status": "hacked",
                "reason": reason,
                "timestamp": datetime.utcnow(),
            }
        },
        upsert=True,
    )


async def get_hacked_users():
    """Retrieves all currently hacked users."""
    cursor = db.hacked_users.find({"status": "hacked"})
    return await cursor.to_list(length=None)


async def remove_hacked_user(user_id: str):
    """Removes the hacked tag (e.g., after they recover account)."""
    await db.hacked_users.delete_one({"_id": user_id})


# --- SCAM IMAGE BLACKLIST ---


async def add_scam_image(filename: str, data: bytes, md5: str):
    # _id is the MD5 hash so two different images with the same filename
    # are stored as separate documents rather than overwriting each other.
    await db.scam_images.update_one(
        {"_id": md5},
        {"$set": {"filename": filename, "data": data, "md5": md5}},
        upsert=True,
    )


async def get_scam_images(include_data: bool = True):
    # scam-list only needs filenames/hashes — skip the binary blobs there.
    projection = None if include_data else {"data": 0}
    cursor = db.scam_images.find({}, projection)
    return await cursor.to_list(length=None)


async def remove_scam_image(md5_prefix: str) -> int:
    result = await db.scam_images.delete_many(
        {"md5": {"$regex": f"^{re.escape(md5_prefix)}"}}
    )
    return result.deleted_count


async def rename_scam_image(md5_prefix: str, new_filename: str) -> bool:
    result = await db.scam_images.update_one(
        {"md5": {"$regex": f"^{re.escape(md5_prefix)}"}},
        {"$set": {"filename": new_filename}},
    )
    return result.matched_count > 0


async def ensure_scam_lock_ttl_index():
    """TTL index so detection locks auto-expire ~60s after creation.
    Without this, a user+image lock lives forever and re-posts of the
    same scam image by the same user would be silently ignored.
    """
    await db.scam_detection_locks.create_index("ts", expireAfterSeconds=60)


async def acquire_scam_detection_lock(author_id: int, image_md5: str) -> bool:
    """Atomically claim a detection slot for (author, image).
    Returns True if this caller claimed it (should proceed).
    Returns False if another handler already claimed it (should skip).
    Lock expires after 60 seconds via TTL index on 'ts'.
    """
    key = f"{author_id}:{image_md5}"
    result = await db.scam_detection_locks.find_one_and_update(
        {"_id": key},
        {"$setOnInsert": {"_id": key, "ts": datetime.utcnow()}},
        upsert=True,
        return_document=False,
    )
    return result is None  # None means doc didn't exist before — we claimed it


# --- PAYOUT / ADMIN COMPENSATION HELPERS ---


async def add_payout_batch(
    amount: float, user_ids: list[str], reason: str, admin_id: str
):
    """Crash-safe staff payout batch.

    The receipt id is derived deterministically from the batch inputs (sorted
    user ids + per-person amount + reason), so re-running the identical
    /payout-add after a mid-loop crash reuses the same batch id. Each recipient
    is claimed in the shared reward_payouts ledger (source="payout") before the
    payouts $inc, so a re-run credits only users who were never reached and
    never double-pays anyone already credited for this batch.

    Trade-off: two *intentionally* identical payouts (same users, same
    per-person amount, same reason) hash to the same batch id, so the second is
    treated as a retry and skipped. Vary the reason to force a distinct batch.

    Returns (batch_id, credited, skipped) so the caller can report accurately.
    """
    if db is None:
        return None, [], []

    # Deterministic receipt id: independent of caller set() ordering and of a
    # random uuid, so an identical re-run collides on the same key and dedupes.
    payload = "|".join(sorted(user_ids)) + f"|{amount:.2f}|{reason}"
    batch_id = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]

    # 1. Save Global Log (idempotent: a re-run must not append a duplicate row,
    # since /payout-history reads these).
    await db.payout_logs.update_one(
        {"batch_id": batch_id},
        {
            "$setOnInsert": {
                "batch_id": batch_id,
                "timestamp": datetime.utcnow(),
                "amount": amount,
                "user_ids": user_ids,
                "reason": reason,
            }
        },
        upsert=True,
    )

    # 2. Credit each user at most once per batch. The ledger claim gates the
    # $inc/$push so a re-run skips anyone already credited for this batch id.
    credited, skipped = [], []
    for uid in user_ids:
        if not await claim_reward_payout(
            batch_id, uid, amount, admin_id, source="payout"
        ):
            skipped.append(uid)
            continue
        await db.payouts.update_one(
            {"_id": uid},
            {"$inc": {"amount": amount}, "$push": {"unpaid_batches": batch_id}},
            upsert=True,
        )
        await mark_reward_paid(batch_id, uid)
        credited.append(uid)

    return batch_id, credited, skipped


async def get_payout_logs(limit: int = 25):
    """Fetches global payout history."""
    if db is None:
        return []
    cursor = db.payout_logs.find().sort("timestamp", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def get_user_unpaid_batches(user_id: str):
    """Returns the list of batch_ids the user currently owes."""
    if db is None:
        return []
    doc = await db.payouts.find_one({"_id": user_id})
    if doc:
        return doc.get("unpaid_batches", [])
    return []


async def get_all_pending_payouts():
    """Returns a list of all users with a positive pending balance."""
    if db is None:
        return []
    cursor = db.payouts.find({"amount": {"$gt": 0}}).sort("amount", -1)
    return await cursor.to_list(length=None)


async def clear_pending_payout(user_id: str = None):
    """
    Resets balance to 0 and clears the 'unpaid_batches' list.
    If user_id is None, clears ALL payouts.
    """
    if db is None:
        return

    update_data = {"$set": {"amount": 0, "unpaid_batches": []}}

    if user_id:
        await db.payouts.update_one({"_id": user_id}, update_data)
    else:
        await db.payouts.update_many({}, update_data)


# --- BLACKLIST HELPERS ---


async def add_blacklisted_user(
    user_id: str,
    reason: str,
    admin_id: str,
    matcherino: str = None,
    alts: list[str] = None,
):
    """
    Adds or updates a user in the blacklist.
    """
    if db is None:
        return

    doc = {
        "_id": user_id,
        "reason": reason,
        "admin_id": admin_id,
        "matcherino": matcherino,
        "alts": alts or [],
        "timestamp": datetime.utcnow(),
    }

    # Use replace_one with upsert to completely overwrite if they exist (updating details)
    await db.blacklist.replace_one({"_id": user_id}, doc, upsert=True)


async def remove_blacklisted_user(user_id: str):
    """Removes a user from the blacklist."""
    if db is None:
        return
    await db.blacklist.delete_one({"_id": user_id})


async def get_blacklisted_user(user_id: str):
    """Returns the blacklist document if the user is banned, else None."""
    if db is None:
        return None
    # Ensure we search by string ID
    return await db.blacklist.find_one({"_id": str(user_id)})


async def get_all_blacklisted_users():
    """Returns a list of all blacklisted users."""
    if db is None:
        return []
    cursor = db.blacklist.find().sort("timestamp", -1)
    return await cursor.to_list(length=None)


# --- BRAWLER COLLECTION HELPERS ---


async def add_brawler_to_user(user_id: str, brawler_id: str):
    """
    Adds a brawler to the 'brawlers' field.
    If they already have it, gives Power Points instead.
    """
    if db is None:
        return

    # 1. Check if user already has this brawler in the 'brawlers' object
    #    We check "brawlers.shelly" instead of "inventory.shelly"
    user_doc = await db.users.find_one(
        {"_id": user_id, f"brawlers.{brawler_id}": {"$exists": True}}
    )

    if user_doc:
        # --- DUPLICATE LOGIC ---
        # Give 15 Power Points (stored in currencies)
        await db.users.update_one(
            {"_id": user_id}, {"$inc": {"currencies.power_points": 15}}
        )
        return "duplicate"
    else:
        # --- NEW BRAWLER LOGIC ---
        # Add the brawler object to the 'brawlers' field
        new_brawler_entry = {"level": 1, "obtained_at": datetime.utcnow()}

        await db.users.update_one(
            {"_id": user_id},
            {"$set": {f"brawlers.{brawler_id}": new_brawler_entry}},
            upsert=True,
        )
        return "new"


async def get_user_brawlers(user_id: str):
    """Correctly fetches the list of brawler IDs and ensures Shelly is present."""
    if db is None:
        return []
    user_data = await db.users.find_one({"_id": str(user_id)})

    if user_data and "brawlers" in user_data:
        owned = list(user_data["brawlers"].keys())
        # Force add 'shelly' to the list if she's missing for some reason
        if "shelly" not in [id.lower() for id in owned]:
            owned.append("shelly")
        return owned

    # If user doesn't exist yet, they still technically own Shelly
    return ["shelly"]


# --- BRAWL CURRENCY HELPERS ---


async def add_brawl_coins(user_id: str, amount: int):
    """Adds (or removes) Brawl Coins."""
    if db is None:
        return
    await db.users.update_one({"_id": user_id}, {"$inc": {"currencies.coins": amount}})


async def add_power_points(user_id: str, amount: int):
    """Adds Universal Power Points."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$inc": {"currencies.power_points": amount}}
    )


async def add_brawl_gems(user_id: str, amount: int):
    """Adds Brawl Gems."""
    if db is None:
        return
    await db.users.update_one({"_id": user_id}, {"$inc": {"currencies.gems": amount}})


async def add_credits(user_id: str, amount: int):
    """Adds (or removes) Credits for unlocking Brawlers."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": user_id}, {"$inc": {"currencies.credits": amount}}
    )


async def get_brawl_currencies(user_id: str):
    """Returns a dictionary of all brawl currencies."""
    doc = await get_user_data(user_id)
    return doc.get(
        "currencies", {"coins": 0, "power_points": 0, "gems": 0, "credits": 0}
    )


async def deduct_credits(user_id: str, amount: int) -> bool:
    """Deducts credits if user has enough. Returns True if successful."""
    if db is None:
        return False
    user_data = await get_user_data(user_id)
    current_credits = user_data.get("currencies", {}).get("credits", 0)

    if current_credits < amount:
        return False

    await db.users.update_one(
        {"_id": str(user_id)}, {"$inc": {"currencies.credits": -amount}}
    )
    return True


async def deduct_coins(user_id, amount):
    """Safely deducts coins if balance is sufficient."""
    if db is None:
        return False

    user_data = await get_user_data(user_id)
    current_coins = user_data.get("currencies", {}).get("coins", 0)

    if current_coins >= amount:
        new_balance = current_coins - amount
        await db.users.update_one(
            {"_id": str(user_id)}, {"$set": {"currencies.coins": new_balance}}
        )
        return True
    return False


async def purchase_brawler_ability(
    user_id: str, brawler_id: str, item_type: str, item_name: str, cost: int
) -> bool:
    """
    Atomically deducts Coins and grants a gadget / star power / hypercharge in a
    single update_one, mirroring upgrade_brawler_level. Returns True on success,
    False if the ability type is unknown or the user can't afford it.
    """
    if db is None:
        return False

    user_data = await get_user_data(user_id)
    current_coins = user_data.get("currencies", {}).get("coins", 0)
    if current_coins < cost:
        return False

    # Deduct + grant fold into one update document; the currency $inc and the
    # ability grant touch different field paths, so MongoDB applies both atomically.
    update = {"$inc": {"currencies.coins": -cost}}
    if item_type == "gadget":
        update["$addToSet"] = {f"brawlers.{brawler_id}.gadgets": item_name}
    elif item_type == "star_power":
        update["$addToSet"] = {f"brawlers.{brawler_id}.star_powers": item_name}
    elif item_type == "hypercharge":
        update["$set"] = {f"brawlers.{brawler_id}.hypercharge": item_name}
    else:
        return False

    await db.users.update_one({"_id": str(user_id)}, update)
    return True


async def purchase_brawler(user_id: str, brawler_id: str, price: int):
    """
    Atomically deducts Credits and grants the brawler in a single update_one,
    mirroring upgrade_brawler_level. Preserves add_brawler_to_user's semantics:
    a duplicate purchase grants 15 Power Points instead of the brawler.

    Returns "new" or "duplicate" on success, or False if the user can't afford it.
    """
    if db is None:
        return False

    user_data = await get_user_data(user_id)
    current_credits = user_data.get("currencies", {}).get("credits", 0)
    if current_credits < price:
        return False

    if brawler_id in user_data.get("brawlers", {}):
        # Duplicate: deduct Credits and grant 15 Power Points in one write.
        await db.users.update_one(
            {"_id": str(user_id)},
            {"$inc": {"currencies.credits": -price, "currencies.power_points": 15}},
        )
        return "duplicate"

    # New brawler: deduct Credits and set the brawler entry in one write.
    await db.users.update_one(
        {"_id": str(user_id)},
        {
            "$inc": {"currencies.credits": -price},
            "$set": {
                f"brawlers.{brawler_id}": {"level": 1, "obtained_at": datetime.utcnow()}
            },
        },
    )
    return "new"


async def upgrade_brawler_level(user_id: str, brawler_id: str):
    """
    Attempts to upgrade a brawler.
    Returns a tuple: (Success: bool, Message: str, NewLevel: int)
    """
    if db is None:
        return False, "Database not connected", 0

    # 1. Fetch User Data
    user_data = await get_user_data(user_id)
    if not user_data:
        return False, "User not found", 0

    brawlers = user_data.get("brawlers", {})
    if brawler_id not in brawlers:
        return False, "You don't own this brawler!", 0

    current_level = brawlers[brawler_id].get("level", 1)

    if current_level >= 11:
        return False, "This brawler is already at MAX Level (11)!", 11

    # 2. Determine Costs & Import Emojis
    from features.config import BRAWLER_UPGRADE_COSTS, EMOJIS_CURRENCY

    # Get custom icons
    pp_icon = EMOJIS_CURRENCY.get("power_points", "⚡")
    coin_icon = EMOJIS_CURRENCY.get("coins", "💰")

    next_level = current_level + 1
    costs = BRAWLER_UPGRADE_COSTS.get(next_level)

    if not costs:
        return False, "Error calculating upgrade costs.", current_level

    required_pp = costs["pp"]
    required_coins = costs["coins"]

    user_pp = user_data.get("currencies", {}).get("power_points", 0)
    user_coins = user_data.get("currencies", {}).get("coins", 0)

    # 3. Check Balances with Custom Emojis
    if user_pp < required_pp:
        missing = required_pp - user_pp
        return (
            False,
            f"Not enough Power Points! Need **{missing}** more {pp_icon}.",
            current_level,
        )

    if user_coins < required_coins:
        missing = required_coins - user_coins
        return (
            False,
            f"Not enough Coins! Need **{missing}** more {coin_icon}.",
            current_level,
        )

    # 4. Perform Transaction
    await db.users.update_one(
        {"_id": str(user_id)},
        {
            "$inc": {
                "currencies.power_points": -required_pp,
                "currencies.coins": -required_coins,
                f"brawlers.{brawler_id}.level": 1,
            }
        },
    )

    return True, "Upgrade Successful!", next_level


async def add_gadget_to_user(user_id: str, brawler_id: str, gadget_name: str):
    """Adds a gadget to a brawler's gadgets array."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": str(user_id)},
        {
            "$addToSet": {f"brawlers.{brawler_id}.gadgets": gadget_name}
        },  # Prevents duplicates
    )


async def add_star_power_to_user(user_id: str, brawler_id: str, sp_name: str):
    """Adds a star power to a brawler's star_powers array."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": str(user_id)},
        {"$addToSet": {f"brawlers.{brawler_id}.star_powers": sp_name}},
    )


async def add_hypercharge_to_user(user_id: str, brawler_id: str, hc_name: str):
    """Adds a hypercharge to a brawler's data."""
    if db is None:
        return
    await db.users.update_one(
        {"_id": str(user_id)}, {"$set": {f"brawlers.{brawler_id}.hypercharge": hc_name}}
    )


# --- QUEST SYSTEM HELPERS ---


async def init_default_quests(default_quests_list):
    """Upserts default quests into the DB, syncing rewards to code on every startup."""
    if db is None:
        return
    for q in default_quests_list:
        await db.quests.update_one(
            {"name": q[0]},
            {
                "$set": {
                    "description": q[1],
                    "reward_tokens": q[2],
                    "reward_exp": q[3],
                    "target_count": q[4],
                    "quest_type": q[5],
                    "quest_category": q[6],
                    "is_active": True,
                }
            },
            upsert=True,
        )
    print("✅ Default Quests synced to MongoDB")


async def get_active_quest(user_id: str, q_key: str):
    """Retrieves the user's current active quest status.

    q_key is one of: daily_message, weekly_message, daily_megabox, weekly_megabox
    """
    if db is None:
        return None

    user_q = await db.user_quests.find_one({"_id": user_id})
    if not user_q:
        return None

    quest_entry = user_q.get(q_key)
    if not quest_entry:
        return None

    period = q_key.split("_")[0]  # "daily" or "weekly"
    now = datetime.utcnow()
    stored_date = quest_entry.get("date_assigned")

    if not stored_date:
        return None

    is_expired = False
    if period == "daily":
        if stored_date.date() != now.date():
            is_expired = True
    elif period == "weekly":
        if stored_date.isocalendar()[1] != now.isocalendar()[1]:
            is_expired = True

    if is_expired:
        return None

    return quest_entry


BOOSTER_QUEST_TARGET_MULTIPLIER = 0.8


def booster_quest_target(target: int) -> int:
    """Returns the reduced quest target for server boosters (20% off)."""
    return max(1, round(target * BOOSTER_QUEST_TARGET_MULTIPLIER))


async def assign_random_quest(user_id: str, q_key: str, is_booster: bool = False):
    """Picks a random active quest from the DB and assigns it to the user.

    q_key is one of: daily_message, weekly_message, daily_megabox, weekly_megabox
    Boosters get a reduced target, stored on the assignment record so the
    threshold is fixed for the quest's lifetime regardless of boost changes.
    """
    if db is None:
        return None

    period, category = q_key.split("_", 1)  # e.g. "daily", "message"

    cursor = db.quests.find({})
    all_quests = await cursor.to_list(length=None)

    matching_quests = [
        q
        for q in all_quests
        if str(q.get("quest_type", "")).lower() == period
        and str(q.get("quest_category", "")).lower() == category
    ]

    if not matching_quests:
        print(f"⚠️ No matching quests found for key '{q_key}'")
        return None

    import random

    quest = random.choice(matching_quests)

    target = quest.get("target_count", quest.get("target", 100))
    description = quest["description"]
    if is_booster:
        reduced = booster_quest_target(target)
        description = description.replace(str(target), str(reduced), 1)
        target = reduced

    new_entry = {
        "quest_id": quest["_id"],
        "name": quest["name"],
        "description": description,
        "target_count": target,
        "reward_tokens": quest.get("reward_tokens", 0),
        "reward_exp": quest.get("reward_exp", 0),
        "progress": 0,
        "completed": False,
        "rewarded": False,
        "booster_reduced": is_booster,
        "date_assigned": datetime.utcnow(),
    }

    await db.user_quests.update_one(
        {"_id": user_id}, {"$set": {q_key: new_entry}}, upsert=True
    )

    return new_entry


async def reset_user_quests(user_id: str):
    """Deletes a user's quest assignments so they get freshly assigned on next /quests."""
    if db is None:
        return
    await db.user_quests.delete_one({"_id": user_id})


async def update_quest_progress(user_id: str, q_key: str, amount: int = 1):
    """Increments progress and checks for completion.

    q_key is one of: daily_message, weekly_message, daily_megabox, weekly_megabox
    """
    if db is None:
        return False, None

    user_q = await db.user_quests.find_one({"_id": user_id})
    if not user_q or q_key not in user_q:
        return False, None

    quest = user_q[q_key]
    if quest["completed"]:
        # Legacy completed quests (assigned before the rewarded field existed)
        # default to paid, so they are never re-granted. Only an explicit
        # rewarded:False — a crash between the completed write and the payout —
        # re-signals a payout so the caller can retry it.
        if quest.get("rewarded", True):
            return False, None
        return True, quest

    new_progress = quest["progress"] + amount
    target = quest["target_count"]

    if new_progress >= target:
        await db.user_quests.update_one(
            {"_id": user_id},
            {"$set": {f"{q_key}.progress": target, f"{q_key}.completed": True}},
        )
        return True, quest
    else:
        await db.user_quests.update_one(
            {"_id": user_id}, {"$inc": {f"{q_key}.progress": amount}}
        )
        return False, None


QUEST_KEYS = ("daily_message", "weekly_message", "daily_megabox", "weekly_megabox")


async def add_quest_reward(user_id: str, tokens: int, exp: int):
    """Atomically grant a quest's tokens + XP in a single users-doc $inc.

    balance and exp both live on the one users doc, so this can never pay tokens
    without XP (or vice versa). Paid before the rewarded flag is set so a crash
    leaves the quest re-payable rather than losing the reward.
    """
    if db is None:
        return
    inc = {}
    if tokens:
        inc["balance"] = tokens
    if exp:
        inc["exp"] = exp
    if not inc:
        return
    await db.users.update_one({"_id": str(user_id)}, {"$inc": inc}, upsert=True)


async def mark_quest_rewarded(user_id: str, q_key: str):
    """Flags a completed quest's reward as paid out (commit point of the payout)."""
    if db is None:
        return
    await db.user_quests.update_one(
        {"_id": user_id}, {"$set": {f"{q_key}.rewarded": True}}
    )


async def get_unrewarded_completed_quests():
    """Returns [(user_id, q_key, quest_entry), ...] for quests flagged completed
    whose reward never landed — a crash between the completed write and the
    payout. Matching rewarded:False (not $ne True) excludes legacy quests that
    predate the field and were already paid under the old code path.
    """
    if db is None:
        return []
    query = {
        "$or": [{f"{k}.completed": True, f"{k}.rewarded": False} for k in QUEST_KEYS]
    }
    out = []
    async for doc in db.user_quests.find(query):
        for k in QUEST_KEYS:
            q = doc.get(k)
            if q and q.get("completed") and q.get("rewarded") is False:
                out.append((doc["_id"], k, q))
    return out


# --- TOURNAMENT STATS HELPERS ---


async def create_tourney_session():
    """Starts a new tournament session."""
    if db is None:
        return None
    try:
        new_session = {
            "status": "active",
            "start_time": datetime.utcnow(),
            "total_tickets": 0,
            "total_messages": 0,
            "peak_queue": 0,
            "current_queue": 0,
        }
        result = await db.tourney_sessions.insert_one(new_session)
        return result.inserted_id
    except Exception as e:
        print(f"⚠️ DB Error (Create Session): {e}")
        return None


async def get_active_tourney_session():
    """Returns the currently active session document, or None."""
    if db is None:
        return None
    try:
        return await db.tourney_sessions.find_one({"status": "active"})
    except Exception as e:
        print(f"⚠️ DB Error (Get Session): {e}")
        return None


async def end_tourney_session(session_id):
    """Marks the session as finished."""
    if db is None:
        return
    try:
        await db.tourney_sessions.update_one(
            {"_id": session_id},
            {"$set": {"status": "finished", "end_time": datetime.utcnow()}},
        )
    except Exception as e:
        print(f"⚠️ DB Error (End Session): {e}")


async def reset_tourney_session_start_time(session_id):
    """Force-resets an existing active session start_time to now."""
    if db is None:
        return False
    try:
        result = await db.tourney_sessions.update_one(
            {"_id": session_id, "status": "active"},
            {"$set": {"start_time": datetime.utcnow(), "matcherino_id": None}},
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"⚠️ DB Error (Reset Session Start Time): {e}")
        return False


async def update_tourney_runtime_state(session_id, **fields):
    """Persist recovery fields on the active session so runtime state can be
    rehydrated after a bot restart (region, admin_role_original_name,
    slowmode_ends_at, lock_reopens_at). SILENT FAIL enabled."""
    if db is None or not fields:
        return
    try:
        await db.tourney_sessions.update_one({"_id": session_id}, {"$set": fields})
    except Exception as e:
        print(f"⚠️ DB Error (Runtime State): {e}")


async def increment_tourney_message_count(session_id):
    """Increments the global message counter. SILENT FAIL enabled."""
    if db is None:
        return
    try:
        await db.tourney_sessions.update_one(
            {"_id": session_id}, {"$inc": {"total_messages": 1}}
        )
    except Exception as e:
        # We assume this is high-volume, so we just log and move on
        print(f"⚠️ DB Error (Msg Count): {e}")


async def update_tourney_queue(session_id, change: int):
    """Updates current queue size. SILENT FAIL enabled."""
    if db is None:
        return
    try:
        # Update current queue and return the new document
        updated_doc = await db.tourney_sessions.find_one_and_update(
            {"_id": session_id},
            {
                "$inc": {
                    "current_queue": change,
                    "total_tickets": 1 if change > 0 else 0,
                }
            },
            return_document=True,
        )

        # Check peak queue
        if updated_doc:
            current = updated_doc.get("current_queue", 0)
            peak = updated_doc.get("peak_queue", 0)

            if current > peak:
                await db.tourney_sessions.update_one(
                    {"_id": session_id}, {"$set": {"peak_queue": current}}
                )
    except Exception as e:
        print(f"⚠️ DB Error (Update Queue): {e}")


async def increment_staff_closure(session_id, user_id: str, username: str):
    """Tracks staff stats. SILENT FAIL enabled."""
    if db is None:
        return
    try:
        await db.tourney_staff_stats.update_one(
            {"session_id": session_id, "user_id": str(user_id)},
            {"$inc": {"tickets_closed": 1}, "$set": {"username": username}},
            upsert=True,
        )
    except Exception as e:
        print(f"⚠️ DB Error (Staff Closure): {e}")


async def get_top_staff_stats(session_id, limit: int = 12):
    """Fetches the leaderboard. Default limit bumped to 12 just to be safe."""
    if db is None:
        return []
    try:
        cursor = (
            db.tourney_staff_stats.find({"session_id": session_id})
            .sort("tickets_closed", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)
    except Exception as e:
        print(f"⚠️ DB Error (Get Stats): {e}")
        return []


async def update_matcherino_id(
    session_id: str, matcherino_id: str, collect_data: bool = None
):
    """Saves the Matcherino ID to the active tournament session."""
    if tourney_sessions is None:
        return
    update_fields = {"matcherino_id": matcherino_id}
    if collect_data is not None:
        update_fields["collect_data"] = collect_data
    await tourney_sessions.update_one({"_id": session_id}, {"$set": update_fields})


async def set_tourney_collect_data(session_id, enabled: bool):
    """Sets the collect_data flag on a tournament session."""
    if tourney_sessions is None:
        return
    await tourney_sessions.update_one(
        {"_id": session_id}, {"$set": {"collect_data": enabled}}
    )


async def insert_tourney_snapshot(snapshot: dict):
    """Inserts a single snapshot document into tourney_snapshots."""
    if db is None:
        return
    await db["tourney_snapshots"].insert_one(snapshot)


async def get_last_tourney_snapshot(tourney_id: str):
    """Returns the most recent snapshot for a tourney, or None."""
    if db is None:
        return None
    return await db["tourney_snapshots"].find_one(
        {"tourney_id": tourney_id},
        sort=[("snapshot_at", -1)],
    )


async def get_matcherino_id_from_active():
    """Retrieves the Matcherino ID from the currently active session."""
    session = await get_active_tourney_session()
    if session:
        return session.get("matcherino_id")
    return None


async def get_next_support_ticket_number(counter_key: str) -> int:
    """Returns the next support ticket sequence for a specific ticket category."""
    if db is None:
        return 1

    try:
        doc = await db.support_ticket_counters.find_one_and_update(
            {"_id": counter_key},
            {
                "$inc": {"value": 1},
                "$setOnInsert": {
                    "created_at": datetime.utcnow(),
                },
                "$set": {
                    "updated_at": datetime.utcnow(),
                },
            },
            upsert=True,
            return_document=True,
        )
        if not doc:
            return 1
        return int(doc.get("value", 1))
    except Exception as e:
        print(f"⚠️ DB Error (Support Counter): {e}")


# --- STICKY MESSAGES ---


async def get_sticky(channel_id: int):
    if db is None:
        return None
    return await db.sticky_messages.find_one({"_id": str(channel_id)})


async def set_sticky(
    channel_id: int, content: str, attachments: list, bot_message_id: int
):
    if db is None:
        return
    await db.sticky_messages.update_one(
        {"_id": str(channel_id)},
        {
            "$set": {
                "content": content,
                "attachments": attachments,
                "bot_message_id": bot_message_id,
            }
        },
        upsert=True,
    )


async def update_sticky_message_id(channel_id: int, bot_message_id: int):
    if db is None:
        return
    await db.sticky_messages.update_one(
        {"_id": str(channel_id)},
        {"$set": {"bot_message_id": bot_message_id}},
    )


async def delete_sticky(channel_id: int):
    if db is None:
        return
    await db.sticky_messages.delete_one({"_id": str(channel_id)})
