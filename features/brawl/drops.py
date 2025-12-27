import random
# Import the loot tables
from features.config import MEGA_BOX_LOOT, STARR_DROP_RARITIES, STARR_DROP_LOOT

from database.mongo import (
    add_brawl_coins, 
    add_power_points, 
    add_credits, 
    add_brawler_to_user
)

# --- RNG / GAMEPLAY LOGIC ---

def pick_weighted_item(loot_table):
    """Selects an item based on 'weight' key using standard RNG."""
    items = loot_table
    weights = [item['weight'] for item in items]
    return random.choices(items, weights=weights, k=1)[0]

async def process_reward(user_id: str, reward: dict):
    """Interprets the reward dict and updates DB."""
    r_type = reward["type"]
    
    # 1. Simple Currency
    if r_type == "coins":
        await add_brawl_coins(user_id, reward["amount"])
        return f"**{reward['amount']} Coins**"
    
    elif r_type == "power_points":
        await add_power_points(user_id, reward["amount"])
        return f"**{reward['amount']} Power Points**"
    
    elif r_type == "credits":
        await add_credits(user_id, reward["amount"])
        return f"**{reward['amount']} Credits**"

    # 2. Converted Items (Gadgets/Star Powers -> Coins)
    elif r_type in ["gadget", "star_power", "hypercharge"]:
        amount = reward["amount"]
        await add_brawl_coins(user_id, amount)
        name = r_type.replace("_", " ").title()
        return f"**Random {name}** (Converted to {amount} Coins)"

    # 3. Brawlers
    elif r_type == "brawler":
        # Placeholder ID. 
        brawler_id = f"random_{reward['rarity']}_brawler" 
        
        status = await add_brawler_to_user(user_id, brawler_id)
        
        if status == "new":
            return f"**NEW BRAWLER! ({reward['rarity'].title()})**"
        else:
            fb_amount = reward.get("fallback_credits", 100)
            await add_credits(user_id, fb_amount)
            return f"**Fallback Reward: {fb_amount} Credits** (Duplicate {reward['rarity'].title()} Brawler)"

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
    # 1. Determine Rarity
    rarity_names = list(STARR_DROP_RARITIES.keys())
    rarity_weights = list(STARR_DROP_RARITIES.values())
    rarity = random.choices(rarity_names, weights=rarity_weights, k=1)[0]
    
    # 2. Pick Reward
    loot_table = STARR_DROP_LOOT.get(rarity)
    if not loot_table: return rarity, "Error: Empty Loot Table"
        
    item = pick_weighted_item(loot_table)
    reward_msg = await process_reward(user_id, item)
    
    return rarity, reward_msg