from datetime import datetime
import os
import motor.motor_asyncio
import certifi
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    print("⚠️ CRITICAL: MONGO_URI missing in .env or Pella variables.")
    db = None
else:
    try:
        # Connect to MongoDB with the Mac/SSL fix
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
        db = client["r7_bot_db"]
        print("✅ Connected to Cloud Database (MongoDB)")
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        db = None

# --- CORE USER HELPERS ---

async def get_user_data(user_id: str):
    """Fetch user doc, creating default if missing."""
    if db is None: return {}
    doc = await db.users.find_one({"_id": user_id})
    if not doc:
        doc = {
            "_id": user_id, 
            "balance": 0, 
            "level": 1, 
            "exp": 0, 
            "inventory": {} 
        }
        await db.users.insert_one(doc)
    return doc

async def get_user_balance(user_id: str) -> int:
    doc = await get_user_data(user_id)
    return doc.get("balance", 0)

async def update_user_balance(user_id: str, amount: int):
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"balance": amount}},
        upsert=True
    )

# --- LEVELING HELPERS ---

async def get_leveling_data(user_id: str):
    doc = await get_user_data(user_id)
    return doc.get("level", 1), doc.get("exp", 0)

async def update_leveling_data(user_id: str, level: int, exp: int):
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"level": level, "exp": exp}},
        upsert=True
    )

# --- INVENTORY & SETTINGS HELPERS ---

async def add_item_token(user_id: str, item_name: str, quantity: int = 1):
    """Adds an item to the user's inventory."""
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {f"inventory.{item_name}": quantity}},
        upsert=True
    )

async def get_item_count(user_id: str, item_name: str) -> int:
    """Checks how many of an item a user has."""
    doc = await get_user_data(user_id)
    inventory = doc.get("inventory", {})
    return inventory.get(item_name, 0)

async def remove_item_token(user_id: str, item_name: str, quantity: int = 1):
    """Removes an item from inventory."""
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {f"inventory.{item_name}": -quantity}}
    )

async def get_setting(key: str, default: str = None):
    if db is None: return default
    doc = await db.settings.find_one({"_id": key})
    return doc["value"] if doc else default

async def set_setting(key: str, value: str):
    if db is None: return
    await db.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

# --- LEADERBOARD HELPERS ---

async def get_leaderboard_page(offset: int, limit: int):
    """Get a slice of users sorted by balance."""
    if db is None: return []
    cursor = db.users.find().sort("balance", -1).skip(offset).limit(limit)
    return await cursor.to_list(length=limit)

async def get_levels_page(offset: int, limit: int):
    """Get a slice of users sorted by level then exp."""
    if db is None: return []
    # Sort by level DESC, then exp DESC
    cursor = db.users.find().sort([("level", -1), ("exp", -1)]).skip(offset).limit(limit)
    return await cursor.to_list(length=limit)

async def get_total_users():
    if db is None: return 0
    return await db.users.count_documents({})

async def get_user_rank(user_id: str):
    if db is None: return 0
    bal = await get_user_balance(user_id)
    # Count how many people have strictly MORE money
    count = await db.users.count_documents({"balance": {"$gt": bal}})
    return count + 1

async def get_user_level_rank(user_id: str):
    if db is None: return 0
    lvl, exp = await get_leveling_data(user_id)
    # Complex count: People with higher level OR (same level AND higher exp)
    count = await db.users.count_documents({
        "$or": [
            {"level": {"$gt": lvl}},
            {"level": lvl, "exp": {"$gt": exp}}
        ]
    })
    return count + 1

# --- SECURITY / HACKED USER TRACKING ---

async def add_hacked_user(user_id: str, reason: str = "Compromised Account"):
    """Tags a user as hacked in the database."""
    await db.hacked_users.update_one(
        {"_id": user_id},
        {"$set": {
            "status": "hacked", 
            "reason": reason, 
            "timestamp": datetime.utcnow()
        }},
        upsert=True
    )

async def get_hacked_users():
    """Retrieves all currently hacked users."""
    cursor = db.hacked_users.find({"status": "hacked"})
    return await cursor.to_list(length=100)

async def remove_hacked_user(user_id: str):
    """Removes the hacked tag (e.g., after they recover account)."""
    await db.hacked_users.delete_one({"_id": user_id})
    
# --- PAYOUT / ADMIN COMPENSATION HELPERS ---

async def add_pending_payout(user_id: str, amount: float):
    """Adds an amount to a staff member's pending payout."""
    if db is None: return
    await db.payouts.update_one(
        {"_id": user_id},
        {"$inc": {"amount": amount}},
        upsert=True
    )

async def get_all_pending_payouts():
    """Returns a list of all users with a positive pending balance."""
    if db is None: return []
    cursor = db.payouts.find({"amount": {"$gt": 0}}).sort("amount", -1)
    return await cursor.to_list(length=None)

async def clear_pending_payout(user_id: str = None):
    """
    Clears payout for a specific user. 
    If user_id is None, clears ALL payouts.
    """
    if db is None: return
    if user_id:
        await db.payouts.delete_one({"_id": user_id})
    else:
        await db.payouts.delete_many({})