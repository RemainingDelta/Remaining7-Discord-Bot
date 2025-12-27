import os
import random
from dotenv import load_dotenv


load_dotenv()

MODE = os.getenv('BOT_MODE', 'TEST').upper()

if MODE == "REAL":
    TOURNEY_CATEGORY_ID = 1442023447252176916   
    PRE_TOURNEY_CATEGORY_ID = 1448869532046200992
    TOURNEY_CLOSED_CATEGORY_ID = 1449608630402945055      
    PRE_TOURNEY_CLOSED_CATEGORY_ID = 1449608576858456134
    
    TOURNEY_SUPPORT_CHANNEL_ID = 1442037795987259464
    PRE_TOURNEY_SUPPORT_CHANNEL_ID = 1448917516071207133
    TOURNEY_ADMIN_CHANNEL_ID = 724835692395626516

    TOURNEY_ADMIN_ROLE_ID = 1160989152381251756
    FOUNDER_ROLE_ID = 663593813847179295
    ADMIN_ROLE_ID = 1317689015482187777
    MODERATOR_ROLE_ID = 663499255616634923

    MEMBER_ROLE_ID = 699305248568901652

    OTHER_TICKET_CHANNEL_ID = 1259649295649472602
    LOG_CHANNEL_ID = 1442374964144640090
    HALL_OF_FAME_CHANNEL_ID = 734197257267839047
    GENERAL_CHANNEL_ID = 294192597939912714
    MODERATOR_LOGS_CHANNEL_ID = 881042814736150559

    RED_EVENT_CHANNEL_ID = 1419791148960055317
    BLUE_EVENT_CHANNEL_ID = 1423866277931257907
    GREEN_EVENT_CHANNEL_ID = 1419791220053643384
    EVENT_STAFF_CHANNEL_ID = 811497227531845642
    EVENT_ANNOUNCEMENTS_CHANNEL_ID = 863649858120450088

    EVENT_STAFF_ROLE_ID = 811495204346789938

else:
    TOURNEY_CATEGORY_ID = 1442029102185054290    
    PRE_TOURNEY_CATEGORY_ID = 1448871112598618203
    TOURNEY_CLOSED_CATEGORY_ID = 1449594168006414398   
    PRE_TOURNEY_CLOSED_CATEGORY_ID = 1449594321031401544 

    TOURNEY_SUPPORT_CHANNEL_ID = 1448916985713791000
    PRE_TOURNEY_SUPPORT_CHANNEL_ID = 1448917121743716485
    TOURNEY_ADMIN_CHANNEL_ID = 1452338842798526514

    TOURNEY_ADMIN_ROLE_ID = 1442028161889079469   
    FOUNDER_ROLE_ID = 1442028361810444379
    ADMIN_ROLE_ID = 1442028239009615925
    MODERATOR_ROLE_ID = 528976783173877771

    MEMBER_ROLE_ID = 528976903080640523

    OTHER_TICKET_CHANNEL_ID = 1442218644015808633
    LOG_CHANNEL_ID = 1442227896302174298
    HALL_OF_FAME_CHANNEL_ID = 1442663794903089325
    GENERAL_CHANNEL_ID = 528717317526388758
    MODERATOR_LOGS_CHANNEL_ID = 1451300908867522611

    RED_EVENT_CHANNEL_ID = 1450350430201843826
    BLUE_EVENT_CHANNEL_ID = 1450350470446055535
    GREEN_EVENT_CHANNEL_ID = 1450350503467815034
    EVENT_STAFF_CHANNEL_ID = 1450350534279036979
    EVENT_ANNOUNCEMENTS_CHANNEL_ID = 1450923458342162677

    EVENT_STAFF_ROLE_ID = 1450350588209533019

ALLOWED_STAFF_ROLES = [
    TOURNEY_ADMIN_ROLE_ID,
    FOUNDER_ROLE_ID,
    ADMIN_ROLE_ID,
]

SHOP_DATA = {
    "brawl pass": {
        "display": "🎮 **Brawl Pass+**",
        "desc": "Unlock exclusive rewards in Brawl Stars!",
        "price": 17000
    },
    "nitro": {
        "display": "💎 **Discord Nitro**",
        "desc": "Get Discord Nitro for 1 month!",
        "price": 17000
    },
    "paypal": {
        "display": "💵 **15 USD PayPal**",
        "desc": "Redeem 15 USD via PayPal!",
        "price": 25500
    },
    "shoutout": {
        "display": "📣 **Shoutout**",
        "desc": "Get a personal shoutout in announcements!",
        "price": 12000
    }
}

MEGA_BOX_LOOT = [
    {"type": "coins", "amount": 50, "weight": 34.00},
    {"type": "coins", "amount": 1000, "weight": 0.10},  # Jackpot Coins
    {"type": "coins", "amount": 500, "weight": 0.50},   # Fallback for Gadget
    {"type": "coins", "amount": 1000, "weight": 0.30},  # Fallback for Star Power
    {"type": "coins", "amount": 1000, "weight": 0.10},  # Fallback for Hypercharge
    {"type": "power_points", "amount": 25, "weight": 20.00},
    {"type": "power_points", "amount": 1000, "weight": 0.10},
    {"type": "credits", "amount": 10, "weight": 15.00},
    {"type": "credits", "amount": 30, "weight": 1.00},
    # Brawlers (Weight matches drop rate)
    {"type": "brawler", "rarity": "rare", "fallback_credits": 100, "weight": 1.00},
    {"type": "brawler", "rarity": "super_rare", "fallback_credits": 200, "weight": 0.50},
    {"type": "brawler", "rarity": "epic", "fallback_credits": 500, "weight": 0.30},
    {"type": "brawler", "rarity": "mythic", "fallback_credits": 1000, "weight": 0.20},
    {"type": "brawler", "rarity": "legendary", "fallback_credits": 2000, "weight": 0.10},
]

# 2. STARR DROP RARITY CHANCES
STARR_DROP_RARITIES = {
    "Rare": 50,
    "Super Rare": 28,
    "Epic": 15,
    "Mythic": 5,
    "Legendary": 2
}

# 3. STARR DROP REWARDS (Per Rarity)
# Cosmetics/XP Doublers removed. 
# Weights based on your image/text but normalized for "Useful" items only.

STARR_DROP_LOOT = {
    "Rare": [
        {"type": "coins", "amount": 50, "weight": 41.9},
        {"type": "power_points", "amount": 25, "weight": 32.6},
        {"type": "credits", "amount": 10, "weight": 2.3},
    ],
    "Super Rare": [
        {"type": "coins", "amount": 100, "weight": 42.4},
        {"type": "power_points", "amount": 50, "weight": 33.1},
        {"type": "credits", "amount": 30, "weight": 3.3},
    ],
    "Epic": [
        {"type": "coins", "amount": 200, "weight": 21.0},
        {"type": "power_points", "amount": 100, "weight": 21.0},
        {"type": "credits", "amount": 150, "weight": 5.3},
        # Assuming "Random Brawler" slots here or Fallback Coins for Gadgets
        {"type": "coins", "amount": 500, "weight": 15.8}, # Gadget Fallback
    ],
    "Mythic": [
        {"type": "coins", "amount": 500, "weight": 9.5},
        {"type": "power_points", "amount": 200, "weight": 19.0},
        {"type": "credits", "amount": 500, "weight": 6.3}, # High credits
        {"type": "brawler", "rarity": "mythic", "fallback_credits": 1000, "weight": 2.5},
        {"type": "coins", "amount": 1000, "weight": 3.2}, # SP Fallback
    ],
    "Legendary": [
        {"type": "credits", "amount": 1000, "weight": 2.17}, # Fallback for Legendary Brawler logic often handled here
        {"type": "brawler", "rarity": "legendary", "fallback_credits": 2000, "weight": 2.17}, 
        {"type": "brawler", "rarity": "epic", "fallback_credits": 500, "weight": 8.86}, 
        {"type": "coins", "amount": 1000, "weight": 16.3}, # Hypercharge Fallback
        {"type": "coins", "amount": 1000, "weight": 38.0}, # Star Power Fallback
    ]
}