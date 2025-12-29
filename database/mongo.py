from datetime import datetime
import os
import uuid
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
    """
    Fetches user data and performs self-healing checks 
    to ensure Shelly is always present.
    """
    if db is None: return None
    
    data = await db.users.find_one({"_id": str(user_id)})
    
    if not data:
        # New User: Create with Shelly Level 1 and empty lists
        new_user = {
            "_id": str(user_id),
            "currencies": {"coins": 100, "power_points": 0, "credits": 0, "gems": 0},
            "brawlers": {
                "shelly": {
                    "level": 1, 
                    "gadgets": [], 
                    "star_powers": []
                }
            } 
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
            {"$set": {"brawlers.shelly": {"level": 1, "gadgets": [], "star_powers": []}}}
        )
        
    return data

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

async def get_user_rank(user_id: str) -> int:
    """
    Calculates rank by checking the 'users' collection.
    Handles String vs Int ID mismatch to prevent Rank 0 errors.
    """
    if db is None: return 0
    
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
    higher_balance_count = await collection.count_documents({
        "balance": {"$gt": user_balance}
    })
    
    # 5. Rank is the number of people above you + 1
    return higher_balance_count + 1

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

async def add_payout_batch(amount: float, user_ids: list[str], reason: str):
    """
    1. Logs the batch globally with a unique ID.
    2. Adds funds AND the Batch ID to every user's profile.
    """
    if db is None: return

    # Generate a unique receipt ID (e.g., "a1b2c3d4")
    batch_id = str(uuid.uuid4())[:8]

    # 1. Save Global Log
    log_entry = {
        "batch_id": batch_id,
        "timestamp": datetime.utcnow(),
        "amount": amount,
        "user_ids": user_ids,
        "reason": reason
    }
    await db.payout_logs.insert_one(log_entry)

    # 2. Update Users (Loop ensures everyone gets updated/created)
    for uid in user_ids:
        await db.payouts.update_one(
            {"_id": uid},
            {
                "$inc": {"amount": amount},
                "$push": {"unpaid_batches": batch_id}
            },
            upsert=True
        )

async def get_payout_logs(limit: int = 25):
    """Fetches global payout history."""
    if db is None: return []
    cursor = db.payout_logs.find().sort("timestamp", -1).limit(limit)
    return await cursor.to_list(length=limit)

async def get_user_unpaid_batches(user_id: str):
    """Returns the list of batch_ids the user currently owes."""
    if db is None: return []
    doc = await db.payouts.find_one({"_id": user_id})
    if doc:
        return doc.get("unpaid_batches", [])
    return []

async def get_all_pending_payouts():
    """Returns a list of all users with a positive pending balance."""
    if db is None: return []
    cursor = db.payouts.find({"amount": {"$gt": 0}}).sort("amount", -1)
    return await cursor.to_list(length=None)

async def clear_pending_payout(user_id: str = None):
    """
    Resets balance to 0 and clears the 'unpaid_batches' list.
    If user_id is None, clears ALL payouts.
    """
    if db is None: return
    
    update_data = {"$set": {"amount": 0, "unpaid_batches": []}}
    
    if user_id:
        await db.payouts.update_one({"_id": user_id}, update_data)
    else:
        await db.payouts.update_many({}, update_data)
        

# --- BLACKLIST HELPERS ---

async def add_blacklisted_user(user_id: str, reason: str, admin_id: str, matcherino: str = None, alts: list[str] = None):
    """
    Adds or updates a user in the blacklist.
    """
    if db is None: return
    
    doc = {
        "_id": user_id,
        "reason": reason,
        "admin_id": admin_id,
        "matcherino": matcherino,
        "alts": alts or [],
        "timestamp": datetime.utcnow()
    }
    
    # Use replace_one with upsert to completely overwrite if they exist (updating details)
    await db.blacklist.replace_one({"_id": user_id}, doc, upsert=True)

async def remove_blacklisted_user(user_id: str):
    """Removes a user from the blacklist."""
    if db is None: return
    await db.blacklist.delete_one({"_id": user_id})

async def get_blacklisted_user(user_id: str):
    """Returns the blacklist document if the user is banned, else None."""
    if db is None: return None
    # Ensure we search by string ID
    return await db.blacklist.find_one({"_id": str(user_id)})

async def get_all_blacklisted_users():
    """Returns a list of all blacklisted users."""
    if db is None: return []
    cursor = db.blacklist.find().sort("timestamp", -1)
    return await cursor.to_list(length=None)


# --- BRAWLER COLLECTION HELPERS ---

async def add_brawler_to_user(user_id: str, brawler_id: str):
    """
    Adds a brawler to the 'brawlers' field.
    If they already have it, gives Power Points instead.
    """
    if db is None: return

    # 1. Check if user already has this brawler in the 'brawlers' object
    #    We check "brawlers.shelly" instead of "inventory.shelly"
    user_doc = await db.users.find_one(
        {"_id": user_id, f"brawlers.{brawler_id}": {"$exists": True}}
    )

    if user_doc:
        # --- DUPLICATE LOGIC ---
        # Give 15 Power Points (stored in currencies)
        await db.users.update_one(
            {"_id": user_id},
            {"$inc": {"currencies.power_points": 15}}
        )
        return "duplicate"
    else:
        # --- NEW BRAWLER LOGIC ---
        # Add the brawler object to the 'brawlers' field
        new_brawler_entry = {
            "level": 1,
            "obtained_at": datetime.utcnow()
        }
        
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {f"brawlers.{brawler_id}": new_brawler_entry}},
            upsert=True
        )
        return "new"

async def get_user_brawlers(user_id: str):
    """Correctly fetches the list of brawler IDs and ensures Shelly is present."""
    if db is None: return []
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
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {"currencies.coins": amount}}
    )

async def add_power_points(user_id: str, amount: int):
    """Adds Universal Power Points."""
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {"currencies.power_points": amount}}
    )

async def add_brawl_gems(user_id: str, amount: int):
    """Adds Brawl Gems."""
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {"currencies.gems": amount}}
    )
    
async def add_credits(user_id: str, amount: int):
    """Adds (or removes) Credits for unlocking Brawlers."""
    if db is None: return
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {"currencies.credits": amount}}
    )
    
async def get_brawl_currencies(user_id: str):
    """Returns a dictionary of all brawl currencies."""
    doc = await get_user_data(user_id)
    return doc.get("currencies", {
        "coins": 0, 
        "power_points": 0, 
        "gems": 0, 
        "credits": 0 
    })

async def deduct_credits(user_id: str, amount: int) -> bool:
    """Deducts credits if user has enough. Returns True if successful."""
    if db is None: return False
    user_data = await get_user_data(user_id)
    current_credits = user_data.get("currencies", {}).get("credits", 0)
    
    if current_credits < amount:
        return False
        
    await db.users.update_one(
        {"_id": str(user_id)},
        {"$inc": {"currencies.credits": -amount}}
    )
    return True

async def upgrade_brawler_level(user_id: str, brawler_id: str):
    """
    Attempts to upgrade a brawler. 
    Returns a tuple: (Success: bool, Message: str, NewLevel: int)
    """
    if db is None: return False, "Database not connected", 0
    
    # 1. Fetch User Data
    user_data = await get_user_data(user_id)
    if not user_data: return False, "User not found", 0
    
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
        return False, f"Not enough Power Points! Need **{missing}** more {pp_icon}.", current_level
        
    if user_coins < required_coins:
        missing = required_coins - user_coins
        return False, f"Not enough Coins! Need **{missing}** more {coin_icon}.", current_level

    # 4. Perform Transaction
    await db.users.update_one(
        {"_id": str(user_id)},
        {
            "$inc": {
                "currencies.power_points": -required_pp,
                "currencies.coins": -required_coins,
                f"brawlers.{brawler_id}.level": 1
            }
        }
    )
    
    return True, "Upgrade Successful!", next_level

async def add_gadget_to_user(user_id: str, brawler_id: str, gadget_name: str):
    """Adds a gadget to a brawler's gadgets array."""
    if db is None: return
    await db.users.update_one(
        {"_id": str(user_id)},
        {"$addToSet": {f"brawlers.{brawler_id}.gadgets": gadget_name}} # Prevents duplicates
    )

async def add_star_power_to_user(user_id: str, brawler_id: str, sp_name: str):
    """Adds a star power to a brawler's star_powers array."""
    if db is None: return
    await db.users.update_one(
        {"_id": str(user_id)},
        {"$addToSet": {f"brawlers.{brawler_id}.star_powers": sp_name}}
    )