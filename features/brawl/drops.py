import random
# Import your new config dictionaries
from features.config import (
    MEGA_BOX_LOOT, STARR_DROP_RARITIES, STARR_DROP_LOOT, 
    EMOJIS_CURRENCY, EMOJIS_RARITIES, EMOJIS_BRAWLERS
)
from database.mongo import (
    add_brawl_coins, 
    add_power_points, 
    add_credits, 
    add_brawler_to_user
)
from .brawlers import load_brawlers

# 1. Load the full roster into memory once when the bot starts
BRAWLER_ROSTER = load_brawlers()

def pick_weighted_item(loot_table):
    """Selects an item based on 'weight' key using standard RNG."""
    weights = [item['weight'] for item in loot_table]
    return random.choices(loot_table, weights=weights, k=1)[0]

async def process_reward(user_id: str, reward: dict):
    """Interprets the reward dict, picks specific brawlers, and updates DB."""
    r_type = reward["type"]
    
    # --- Currency Handling ---
    if r_type in ["coins", "power_points", "credits"]:
        icon = EMOJIS_CURRENCY.get(r_type, "")
        amount = reward["amount"]
        if r_type == "coins": await add_brawl_coins(user_id, amount)
        elif r_type == "power_points": await add_power_points(user_id, amount)
        elif r_type == "credits": await add_credits(user_id, amount)
        return f"{icon} **{amount} {r_type.replace('_', ' ').title()}**"

    # --- Specific Brawler Selection ---
    elif r_type == "brawler":
        rolled_rarity = reward['rarity'] # e.g., "mythic"
        rarity_key = rolled_rarity.lower().replace(" ", "_")
        rarity_emoji = EMOJIS_RARITIES.get(rarity_key, "🥊")

        # Filter the roster for brawlers matching the rolled rarity
        eligible = [b for b in BRAWLER_ROSTER if b.rarity.lower() == rolled_rarity.lower()]
        
        if not eligible:
            return f"❌ Error: No brawlers found for rarity {rolled_rarity}"

        # Pick a random brawler from that rarity
        selected_brawler = random.choice(eligible)
        # Look up the brawler's specific emoji from config using their ID
        b_emoji = EMOJIS_BRAWLERS.get(selected_brawler.id, "🥊")

        # Try to add to DB (logic handles "new" vs "duplicate")
        status = await add_brawler_to_user(user_id, selected_brawler.id)
        
        if status == "new":
            return f"{b_emoji} **NEW BRAWLER! {selected_brawler.name} ({rolled_rarity.title()})**"
        else:
            # Duplicate fallback logic
            fb_amount = reward.get("fallback_credits", 100)
            await add_credits(user_id, fb_amount)
            credit_icon = EMOJIS_CURRENCY.get("credits", "💳")
            return f"{credit_icon} **{fb_amount} Credits** (Duplicate {selected_brawler.name})"

    return "🎁 **Reward Received**"

# --- These functions MUST be defined here for commands.py to find them ---

async def open_mega_box(user_id: str):
    """Opens a Mega Box with 10 items."""
    rewards_log = []
    for _ in range(10):
        item = pick_weighted_item(MEGA_BOX_LOOT)
        msg = await process_reward(user_id, item)
        rewards_log.append(msg)
    return rewards_log

async def open_starr_drop(user_id: str):
    """Rolls rarity, then rolls reward from that rarity."""
    rarity_names = list(STARR_DROP_RARITIES.keys())
    rarity_weights = list(STARR_DROP_RARITIES.values())
    rarity = random.choices(rarity_names, weights=rarity_weights, k=1)[0]
    
    loot_table = STARR_DROP_LOOT.get(rarity)
    if not loot_table: return rarity, "Error: Empty Loot Table"
        
    item = pick_weighted_item(loot_table)
    reward_msg = await process_reward(user_id, item)
    
    return rarity, reward_msg