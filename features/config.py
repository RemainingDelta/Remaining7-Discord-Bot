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
    
    EMOJIS_CURRENCY = { 
        "coins": "<:bs_coin:1454305320015888516>",        
        "power_points": "<:bs_power_point:1454305322263908486>",
        "credits": "<:bs_credit:1454305320838103186>",
        "brawler": "🥊"
    }
    
    EMOJIS_RARITIES = {
        "rare": "<:bs_rare:1454351705150984274>",
        "super_rare": "<:bs_super_rare:1454351706707202049>",
        "epic": "<:bs_epic:1454351713623474239>",
        "mythic": "<:bs_mythic:1454351715053863024>",
        "legendary": "<:bs_legendary:1454351704240685117>",
        "ultra_legendary": "<:bs_ultra_legendary:1454351716446371880>"
    }
    
    EMOJIS_DROPS = {
        "starr_drop": "<:starr_drop:1454358502431785074>",
        "mega_box": "<:mega_box:1454358500271591556>",
    }
    
    EMOJIS_BRAWLERS = { 
        "pierce": "<:brawler_pierce:1454345574890606744>",
        "gigi": "<:brawler_gigi:1454345573707677746>",
        "mina": "<:brawler_mina:1454345571941875712>",
        "shelly": "<:brawler_shelly:1454345570843103303>",
        "ziggy": "<:brawler_ziggy:1454345569609711738>",
        "alli": "<:brawler_alli:1454345568066211952>",
        "trunk": "<:brawler_trunk:1454345566908846141>",
        "kaze": "<:brawler_kaze:1454606637880049724>",
        "jaeyong": "<:brawler_jaeyong:1454606639368769697>",
        "lumi": "<:brawler_lumi:1454345562173476947>",
        "finx": "<:brawler_finx:1454345560768253952>",
        "ollie": "<:brawler_ollie:1454345559778263221>",
        "meeple": "<:brawler_meeple:1454345558570303663>",
        "shade": "<:brawler_shade:1454345556989182009>",
        "juju": "<:brawler_juju:1454345555353534474>",
        "kenji": "<:brawler_kenji:1454345554388844707>",
        "moe": "<:brawler_moe:1454345553138815078>",
        "clancy": "<:brawler_clancy:1454345551926657230>",
        "berry": "<:brawler_berry:1454345542464311347>",
        "draco": "<:brawler_draco:1454345541097099470>",
        "lily": "<:brawler_lily:1454345540245651518>",
        "melodie": "<:brawler_melodie:1454345538832044150>",
        "angelo": "<:brawler_angelo:1454345537703772302>",
        "kit": "<:brawler_kit:1454345536734888019>",
        "larrylawrie": "<:brawler_larrylawrie:1454345535636115456>",
        "mico": "<:brawler_mico:1454345534784405624>",
        "charlie": "<:brawler_charlie:1454345533614198804>",
        "chuck": "<:brawler_chuck:1454345531299070044>",
        "pearl": "<:brawler_pearl:1454345530284179507>",
        "cordelius": "<:brawler_cordelius:1454345529210441799>",
        "doug": "<:brawler_doug:1454345528337895424>",
        "maisie": "<:brawler_maisie:1454345527155232841>",
        "hank": "<:brawler_hank:1454345526035349691>",
        "willow": "<:brawler_willow:1454345524617416765>",
        "rt": "<:brawler_rt:1454345523921289227>",
        "buster": "<:brawler_buster:1454345522889363657>",
        "mandy": "<:brawler_mandy:1454345521752838144>",
        "gray": "<:brawler_gray:1454345519710339072>",
        "chester": "<:brawler_chester:1454345518313635891>",
        "eve": "<:brawler_eve:1454345516891770981>",
        "darryl": "<:brawler_darryl:1454345515650125950>",
        "piper": "<:brawler_piper:1454345514907734076>",
        "gene": "<:brawler_gene:1454345513909485578>",
        "mortis": "<:brawler_mortis:1454345513041268878>",
        "8bit": "<:brawler_8bit:1454345511942357215>",
        "elprimo": "<:brawler_elprimo:1454345510964957348>",
        "colt": "<:brawler_colt:1454345509669179546>",
        "lola": "<:brawler_lola:1454345508335386732>",
        "fang": "<:brawler_fang:1454345507483947162>",
        "bo": "<:brawler_bo:1454345506372456683>",
        "squeak": "<:brawler_squeak:1454345505197789326>",
        "surge": "<:brawler_surge:1454345504652791899>",
        "stu": "<:brawler_stu:1454345503679709205>",
        "colette": "<:brawler_colette:1454345501796204584>",
        "bull": "<:brawler_bull:1454345500395311147>",
        "mrp": "<:brawler_mrp:1454345499242135774>",
        "leon": "<:brawler_leon:1454345498310869072>",
        "carl": "<:brawler_carl:1454345497081942086>",
        "bea": "<:brawler_bea:1454345495479718052>",
        "spike": "<:brawler_spike:1454345494485663938>",
        "tick": "<:brawler_tick:1454345493244285022>",
        "crow": "<:brawler_crow:1454345491335876711>",
        "dynamike": "<:brawler_dynamike:1454345490777772143>",
        "jessie": "<:brawler_jessie:1454345489746235454>",
        "jacky": "<:brawler_jacky:1454345488949317652>",
        "brock": "<:brawler_brock:1454345487980171445>",
        "ash": "<:brawler_ash:1454345487011414180>",
        "amber": "<:brawler_amber:1454345485925089444>",
        "nita": "<:brawler_nita:1454345484360486912>",
        "frank": "<:brawler_frank:1454345482838212700>",
        "bibi": "<:brawler_bibi:1454345481810481286>",
        "barley": "<:brawler_barley:1454345480325828638>",
        "nani": "<:brawler_nani:1454345478853623986>",
        "rosa": "<:brawler_rosa:1454345477368713288>",
        "emz": "<:brawler_emz:1454345476173201455>",
        "griff": "<:brawler_griff:1454345474482901022>",
        "belle": "<:brawler_belle:1454345473216217112>",
        "gale": "<:brawler_gale:1454345472331350037>",
        "pam": "<:brawler_pam:1454345471341629531>",
        "tara": "<:brawler_tara:1454345470506831932>",
        "ruffs": "<:brawler_ruffs:1454345469588279306>",
        "edgar": "<:brawler_edgar:1454345467868610754>",
        "byron": "<:brawler_byron:1454345466736283652>",
        "max": "<:brawler_max:1454345465762943017>",
        "lou": "<:brawler_lou:1454345464844517461>",
        "poco": "<:brawler_poco:1454345463255011486>",
        "sandy": "<:brawler_sandy:1454345461694599361>",
        "grom": "<:brawler_grom:1454345460637765652>",
        "buzz": "<:brawler_buzz:1454345459920539689>",
        "rico": "<:brawler_rico:1454345459068833824>",
        "meg": "<:brawler_meg:1454345458146213970>",
        "sprout": "<:brawler_sprout:1454345457257025679>",
        "otis": "<:brawler_otis:1454345456191537196>",
        "janet": "<:brawler_janet:1454345455340228648>",
        "bonnie": "<:brawler_bonnie:1454345454329528565>",
        "penny": "<:brawler_penny:1454345453175836742>",
        "gus": "<:brawler_gus:1454345452161077248>",
        "sam": "<:brawler_sam:1454345450646798487>"
    }
    
    EMOJI_GADGET_DEFAULT = "<:gadget_default:1454928295970738237>"
    EMOJI_STARPOWER_DEFAULT = "<:starpower_default:1454928295035670713>"
    EMOJI_HYPERCHARGE_DEFAULT = "<:hypercharge_default:1455686351466004694>"
    
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
    
    EMOJIS_CURRENCY = { 
        "coins": "<:bs_coin:1454290949780934678>",        
        "power_points": "<:bs_power_point:1454291060183400489>",
        "credits": "<:bs_credit:1454291577190224060>",
        "brawler": "🥊"
    }
    
    EMOJIS_RARITIES = {
        "rare": "<:bs_rare:1454353264958247043>",
        "super_rare": "<:bs_super_rare:1454353266241700070>",
        "epic": "<:bs_epic:1454353267155927052>",
        "mythic": "<:bs_mythic:1454353275771027476>",
        "legendary": "<:bs_legendary:1454353263666266152>",
        "ultra_legendary": "<:bs_ultra_legendary:1454353260956745920>"
    }
    
    EMOJIS_DROPS = {
        "starr_drop": "<:starr_drop:1454357223106023467>",
        "mega_box": "<:mega_box:1454356750797901896>",
    }
    
    EMOJIS_BRAWLERS = { 
        "pierce": "<:brawler_pierce:1454328096206487572>",
        "gigi": "<:brawler_gigi:1454328095413895168>",
        "mina": "<:brawler_mina:1454328094621176011>",
        "shelly": "<:brawler_shelly:1454328093660676270>",
        "ziggy": "<:brawler_ziggy:1454328092641329202>",
        "alli": "<:brawler_alli:1454328091328512181>",
        "trunk": "<:brawler_trunk:1454328089277501511>",
        "kaze": "<:brawler_kaze:1454606327790960824>",
        "jaeyong": "<:brawler_jaeyong:1454606350662504531>",
        "lumi": "<:brawler_lumi:1454328085078999123>",
        "finx": "<:brawler_finx:1454328083984420874>",
        "ollie": "<:brawler_ollie:1454328082822336604>",
        "meeple": "<:brawler_meeple:1454328081698521088>",
        "shade": "<:brawler_shade:1454328080922443897>",
        "juju": "<:brawler_juju:1454328079702032516>",
        "kenji": "<:brawler_kenji:1454328078351339681>",
        "moe": "<:brawler_moe:1454328075704602821>",
        "clancy": "<:brawler_clancy:1454328074807283774>",
        "berry": "<:brawler_berry:1454328073834070047>",
        "draco": "<:brawler_draco:1454328071904825511>",
        "lily": "<:brawler_lily:1454328070428299294>",
        "melodie": "<:brawler_melodie:1454328069459542098>",
        "angelo": "<:brawler_angelo:1454328067861385321>",
        "kit": "<:brawler_kit:1454328067043491891>",
        "larrylawrie": "<:brawler_larrylawrie:1454328064787087532>",
        "mico": "<:brawler_mico:1454328063864082525>",
        "charlie": "<:brawler_charlie:1454328062916165736>",
        "chuck": "<:brawler_chuck:1454328061909532834>",
        "pearl": "<:brawler_pearl:1454328060940783669>",
        "cordelius": "<:brawler_cordelius:1454328060198387984>",
        "doug": "<:brawler_doug:1454328058990432454>",
        "maisie": "<:brawler_maisie:1454328058017349642>",
        "hank": "<:brawler_hank:1454328057132482687>",
        "willow": "<:brawler_willow:1454328056188506327>",
        "rt": "<:brawler_rt:1454328054506852548>",
        "buster": "<:brawler_buster:1454328052925333565>",
        "mandy": "<:brawler_mandy:1454328051948326995>",
        "gray": "<:brawler_gray:1454328050329321700>",
        "chester": "<:brawler_chester:1454328048009740359>",
        "eve": "<:brawler_eve:1454328046978076682>",
        "darryl": "<:brawler_darryl:1454328045094568097>",
        "piper": "<:brawler_piper:1454328044042059919>",
        "gene": "<:brawler_gene:1454328042972516393>",
        "mortis": "<:brawler_mortis:1454328042171142420>",
        "8bit": "<:brawler_8bit:1454328040778891491>",
        "elprimo": "<:brawler_elprimo:1454328040086573157>",
        "colt": "<:brawler_colt:1454328038987661423>",
        "lola": "<:brawler_lola:1454328038002004030>",
        "fang": "<:brawler_fang:1454328036668346422>",
        "bo": "<:brawler_bo:1454328035666034899>",
        "squeak": "<:brawler_squeak:1454328034390704318>",
        "surge": "<:brawler_surge:1454328032922833018>",
        "stu": "<:brawler_stu:1454328031807017043>",
        "colette": "<:brawler_colette:1454328031056494645>",
        "bull": "<:brawler_bull:1454328030121038040>",
        "mrp": "<:brawler_mrp:1454328028472672290>",
        "leon": "<:brawler_leon:1454328027205861537>",
        "carl": "<:brawler_carl:1454328026107085012>",
        "bea": "<:brawler_bea:1454328024227905648>",
        "spike": "<:brawler_spike:1454328023066083509>",
        "tick": "<:brawler_tick:1454328021472251995>",
        "crow": "<:brawler_crow:1454328020381860028>",
        "dynamike": "<:brawler_dynamike:1454328019282821296>",
        "jessie": "<:brawler_jessie:1454328018301485269>",
        "jacky": "<:brawler_jacky:1454328017068228719>",
        "brock": "<:brawler_brock:1454328015604551795>",
        "ash": "<:brawler_ash:1454328014761492560>",
        "amber": "<:brawler_amber:1454328013784223755>",
        "nita": "<:brawler_nita:1454328012794236981>",
        "frank": "<:brawler_frank:1454328011917885503>",
        "bibi": "<:brawler_bibi:1454328010709667934>",
        "barley": "<:brawler_barley:1454328009309028629>",
        "nani": "<:brawler_nani:1454328008230965312>",
        "rosa": "<:brawler_rosa:1454328006914080938>",
        "emz": "<:brawler_emz:1454328005529833552>",
        "griff": "<:brawler_griff:1454328004644704413>",
        "belle": "<:brawler_bella:1454328003315368089>",
        "gale": "<:brawler_gale:1454328001536987296>",
        "pam": "<:brawler_pam:1454327999913787505>",
        "tara": "<:brawler_tara:1454327998835720304>",
        "ruffs": "<:brawler_ruffs:1454327998076555314>",
        "edgar": "<:brawler_edgar:1454327997258535105>",
        "byron": "<:brawler_byron:1454327996323205320>",
        "max": "<:brawler_max:1454327995467829250>",
        "lou": "<:brawler_lou:1454327994288967702>",
        "poco": "<:brawler_poco:1454327993538445478>",
        "sandy": "<:brawler_sandy:1454327992615440446>",
        "grom": "<:brawler_grom:1454327991948673126>",
        "buzz": "<:brawler_buzz:1454327990983856302>",
        "rico": "<:brawler_rico:1454327990237528115>",
        "meg": "<:brawler_meg:1454327989113454635>",
        "sprout": "<:brawler_sprout:1454327988236582995>",
        "otis": "<:brawler_otis:1454327986638815335>",
        "janet": "<:brawler_janet:1454327985665740871>",
        "bonnie": "<:brawler_bonnie:1454327984071774301>",
        "penny": "<:brawler_penny:1454327983019135129>",
        "gus": "<:brawler_gus:1454327981685080178>",
        "sam": "<:brawler_sam:1454327979894247566>"
    }
    
    EMOJI_GADGET_DEFAULT = "<:gadget_default:1454928324945121523>"
    EMOJI_STARPOWER_DEFAULT = "<:starpower_default:1454928324248993952>"
    EMOJI_HYPERCHARGE_DEFAULT = "<:hypercharge_default:1455686652017115196>"

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
    {"type": "coins", "amount": 50, "weight": 45.00},
    {"type": "power_points", "amount": 25, "weight": 45.00},
    {"type": "credits", "amount": 5, "weight": 10.00},
    
    {"type": "gadget", "weight": 0.20},  
    {"type": "star_power", "weight": 0.10},
    {"type": "hypercharge", "weight": 0.02},

    {"type": "credits", "amount": 30, "weight": 0.50},
    {"type": "coins", "amount": 500, "weight": 0.25},
    {"type": "coins", "amount": 1000, "weight": 0.05},
    {"type": "power_points", "amount": 500, "weight": 0.25},
    {"type": "power_points", "amount": 1000, "weight": 0.05},

    {"type": "brawler", "rarity": "rare", "fallback_credits": 100, "weight": 0.50},
    {"type": "brawler", "rarity": "super_rare", "fallback_credits": 200, "weight": 0.25},
    {"type": "brawler", "rarity": "epic", "fallback_credits": 500, "weight": 0.15},
    {"type": "brawler", "rarity": "mythic", "fallback_credits": 1000, "weight": 0.08},
    {"type": "brawler", "rarity": "legendary", "fallback_credits": 2000, "weight": 0.02},
    {"type": "brawler", "rarity": "ultra legendary", "fallback_credits": 3000, "weight": 0.01}, 
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
        {"type": "gadget", "weight": 15.82}, # Added direct Gadget roll
        {"type": "coins", "amount": 500, "weight": 9.49},
        {"type": "power_points", "amount": 200, "weight": 18.99},
        {"type": "credits", "amount": 500, "weight": 6.33},
        {"type": "brawler", "rarity": "mythic", "fallback_credits": 1000, "weight": 2.53},
    ],
    "Legendary": [
        {"type": "hypercharge", "weight": 16.3},
        {"type": "star_power", "weight": 38.04}, 
        {"type": "brawler", "rarity": "legendary", "fallback_credits": 2000, "weight": 2.17}, 
        {"type": "brawler", "rarity": "epic", "fallback_credits": 500, "weight": 8.86}, 
        {"type": "credits", "amount": 1000, "weight": 2.17},
    ]
}

BRAWLER_PRICES = {
    "Rare": 200,
    "Super Rare": 450,
    "Epic": 925,
    "Mythic": 1900,
    "Legendary": 3800,
    "Ultra Legendary": 5500
}

BRAWLER_UPGRADE_COSTS = {
    2:  {"pp": 20,   "coins": 20},
    3:  {"pp": 30,   "coins": 35},
    4:  {"pp": 50,   "coins": 75},
    5:  {"pp": 80,   "coins": 140},
    6:  {"pp": 130,  "coins": 290},
    7:  {"pp": 210,  "coins": 480},
    8:  {"pp": 340,  "coins": 800},
    9:  {"pp": 550,  "coins": 1250},
    10: {"pp": 890,  "coins": 1875},
    11: {"pp": 1440, "coins": 2800}
}