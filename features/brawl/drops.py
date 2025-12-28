import random
# Import your new config dictionaries
from features.config import (
    MEGA_BOX_LOOT, STARR_DROP_RARITIES, STARR_DROP_LOOT, 
    EMOJIS_CURRENCY, EMOJIS_RARITIES, EMOJIS_BRAWLERS,     
    EMOJI_GADGET_DEFAULT, EMOJI_STARPOWER_DEFAULT 
)
from database.mongo import (
    add_brawl_coins, 
    add_power_points, 
    add_credits, 
    add_brawler_to_user,
    get_user_data,           # Add these
    add_gadget_to_user, 
    add_star_power_to_user
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
        raw_rarity = reward['rarity']
        formatted_rarity = raw_rarity.replace("_", " ").title()
        rarity_key = raw_rarity.lower().replace(" ", "_")
        rarity_emoji = EMOJIS_RARITIES.get(rarity_key, "🥊")

        eligible = [b for b in BRAWLER_ROSTER if b.rarity.lower() == formatted_rarity.lower()]
        
        if not eligible:
            return f"❌ Error: No brawlers found for rarity '{formatted_rarity}'"

        selected_brawler = random.choice(eligible)
        status = await add_brawler_to_user(user_id, selected_brawler.id.lower())
        
        if status == "new":
            return f"{rarity_emoji} **NEW BRAWLER! {selected_brawler.name} ({formatted_rarity})**"
        else:
            fb_amount = reward.get("fallback_credits", 100)
            await add_credits(user_id, fb_amount)
            credit_icon = EMOJIS_CURRENCY.get("credits", "💳")
            return f"{credit_icon} **{fb_amount} Credits** (Duplicate {selected_brawler.name})"

    # --- Gadget & Star Power Logic ---
    if r_type in ["gadget", "star_power"]:
        # Use the global get_user_data imported at the top
        user_doc = await get_user_data(user_id)
        owned_brawlers = user_doc.get("brawlers", {})

        req_lvl = 7 if r_type == "gadget" else 9
        db_field = "gadgets" if r_type == "gadget" else "star_powers"
        
        # Use the global default icons imported at the top
        default_icon = EMOJI_GADGET_DEFAULT if r_type == "gadget" else EMOJI_STARPOWER_DEFAULT
        
        eligible = []
        for b_id, data in owned_brawlers.items():
            b_info = next((b for b in BRAWLER_ROSTER if b.id == b_id), None)
            if not b_info: continue
            
            master_list = b_info.gadgets if r_type == "gadget" else b_info.star_powers
            current_owned = data.get(db_field, [])
            
            if data.get("level", 1) >= req_lvl and len(current_owned) < len(master_list):
                missing = [item for item in master_list if item not in current_owned]
                if missing:
                    eligible.append((b_id, b_info.name, missing))

        if not eligible:
            coin_icon = EMOJIS_CURRENCY.get("coins", "💰")
            await add_brawl_coins(user_id, 1000)
            return f"{coin_icon} **1,000 Coins** (No eligible brawlers)"

        b_id, b_name, missing = random.choice(eligible)
        choice = random.choice(missing)
        
        # Update database using globally imported functions
        if r_type == "gadget":
            await add_gadget_to_user(user_id, b_id, choice)
        else:
            await add_star_power_to_user(user_id, b_id, choice)

        readable_type = r_type.replace('_', ' ').upper()
        return f"{default_icon} **NEW {readable_type}: {choice}** ({b_name})"

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