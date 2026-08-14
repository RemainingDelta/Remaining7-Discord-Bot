from datetime import datetime, timedelta
import os
import re
import uuid
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
    message_id: str, user_id: str, amount: int, admin_id: str, source: str = "event"
) -> bool:
    """Atomically claim one recipient's payout, writing paid:False before payment.

    Returns True if this call newly claimed the payout (caller should pay now).
    Returns False if a doc already exists for this message+user (already paid, or
    claimed-but-stuck) — the caller should skip it. Keyed message_id+user_id so a
    re-run after a crash skips already-handled users instead of double-paying.
    `source` ("event"/"poll") is informational, so a stuck-row report can point
    staff at the right command; recovery is /give either way.
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
                "amount": int(amount),
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


# --- LEADERBOARD HELPERS ---


async def get_leaderboard_page(offset: int, limit: int):
    """Get a slice of users sorted by balance."""
    if db is None:
        return []
    cursor = db.users.find().sort("balance", -1).skip(offset).limit(limit)
    return await cursor.to_list(length=limit)


async def get_levels_page(offset: int, limit: int):
    """Get a slice of users sorted by level then exp."""
    if db is None:
        return []
    # Sort by level DESC, then exp DESC
    cursor = (
        db.users.find().sort([("level", -1), ("exp", -1)]).skip(offset).limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_total_users():
    if db is None:
        return 0
    return await db.users.count_documents({})


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
    lvl, exp = await get_leveling_data(user_id)
    # Complex count: People with higher level OR (same level AND higher exp)
    count = await db.users.count_documents(
        {"$or": [{"level": {"$gt": lvl}}, {"level": lvl, "exp": {"$gt": exp}}]}
    )
    return count + 1


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


async def add_payout_batch(amount: float, user_ids: list[str], reason: str):
    """
    1. Logs the batch globally with a unique ID.
    2. Adds funds AND the Batch ID to every user's profile.
    """
    if db is None:
        return

    # Generate a unique receipt ID (e.g., "a1b2c3d4")
    batch_id = str(uuid.uuid4())[:8]

    # 1. Save Global Log
    log_entry = {
        "batch_id": batch_id,
        "timestamp": datetime.utcnow(),
        "amount": amount,
        "user_ids": user_ids,
        "reason": reason,
    }
    await db.payout_logs.insert_one(log_entry)

    # 2. Update Users (Loop ensures everyone gets updated/created)
    for uid in user_ids:
        await db.payouts.update_one(
            {"_id": uid},
            {"$inc": {"amount": amount}, "$push": {"unpaid_batches": batch_id}},
            upsert=True,
        )


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
