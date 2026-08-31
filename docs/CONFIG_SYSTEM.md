# Config System

## Overview
`features/config.py` is the single source of truth for all environment-specific IDs, constants, and data tables. It branches between PROD and DEV environments based on the `ENVIRONMENT` env var. Cogs import from it rather than reading `os.environ` directly — this keeps all ID management in one place and makes the PROD/DEV switch a single variable change.

---

## Environment Branching

```python
import os
IS_PROD = os.getenv("ENVIRONMENT", "DEV") == "PROD"

GENERAL_CHANNEL_ID = 123456789 if IS_PROD else 987654321
TOURNEY_CATEGORY_ID = 111111111 if IS_PROD else 222222222
# ... etc for every ID
```

Every channel ID, category ID, and role ID is defined this way. DEV values point to a test server so local development doesn't affect the production 15k-member server.

---

## Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `ENVIRONMENT` | `"PROD"` or `"DEV"` (defaults to `"DEV"`) |
| `DISCORD_TOKEN` | Bot login token |
| `MONGO_URI` | MongoDB Atlas connection string |
| `GEMINI_TOKEN` | Gemini AI API key (for GitHub ticket generation) |
| `GITHUB_TOKEN` | GitHub personal access token (`repo` scope required) |

---

## Channel and Category IDs (branched)

Key IDs defined in config:

| Constant | Purpose |
|----------|---------|
| `GENERAL_CHANNEL_ID` | Main chat channel (passive tokens, slowmode) |
| `BOOSTER_CHANNEL_ID` | Booster-only `#general-plus` channel (passive tokens, booster supply drops) |
| `TOURNEY_SUPPORT_CHANNEL_ID` | Where the live ticket panel is posted |
| `PRE_TOURNEY_SUPPORT_CHANNEL_ID` | Pre-tourney ticket panel |
| `TOURNEY_CATEGORY_ID` | Active live tourney ticket category |
| `PRE_TOURNEY_CATEGORY_ID` | Active pre-tourney ticket category |
| `TOURNEY_CLOSED_CATEGORY_ID` | Closed live tourney ticket category |
| `PRE_TOURNEY_CLOSED_CATEGORY_ID` | Closed pre-tourney ticket category |
| `TOURNEY_ADMIN_CHANNEL_ID` | Where `!starttourney` / `!endtourney` are run |
| `TOURNEY_UPDATES_CHANNEL_ID` | Where stage announcements are posted |
| `TOURNEY_SCHEDULE_CHANNEL_ID` | Scanned for Matcherino ID auto-detection |
| `TOURNEY_REPORT_CHANNEL_ID` | Where end-of-tourney stat embeds are archived |
| `LOG_CHANNEL_ID` | Transcript log channel |
| `REDEMPTION_TICKET_CATEGORY_ID` | Redemption ticket category |
| `BOOSTER_SHOUTOUT_CATEGORY_ID` | Booster shoutout ticket category |
| `REDEMPTION_TRANSCRIPT_CHANNEL_ID` | Redemption transcript archive |
| `MODERATOR_LOGS_CHANNEL_ID` | Mod action log channel |
| `SPANISH_CHANNEL_ID` | Spanish support channel (locked during SA tourneys) |
| `OTHER_TICKET_CHANNEL_ID` | General support channel (locked during live tourney) |

---

## Role IDs (branched)

| Constant | Purpose |
|----------|---------|
| `ADMIN_ROLE_ID` | Full admin access |
| `MODERATOR_ROLE_ID` | Moderator access |
| `TRIAL_MODERATOR_ROLE_ID` | Trial mod (limited access) |
| `TOURNEY_ADMIN_ROLE_ID` | Tournament staff (granted `moderate_members` during live tourney) |
| `MEMBER_ROLE_ID` | Base member role |
| `SERVER_BOOSTER_ROLE_ID` | Server Booster perks (token/XP bonuses, daily bonus, shop discount); dev reuses the prod ID since the dev server has no booster role |
| `TOURNEY_STAFF_ROLES` | List of role IDs with tourney ticket access |

---

## Loot Tables

Defined as lists of dicts with `type`, `weight`, and type-specific fields:

```python
MEGA_BOX_LOOT = [
    {"type": "coins", "amount": 200, "weight": 30},
    {"type": "power_points", "amount": 50, "weight": 25},
    {"type": "brawler", "rarity": "rare", "fallback_credits": 100, "weight": 10},
    # ...
]

STARR_DROP_RARITIES = {
    "Rare": 40,
    "Super Rare": 25,
    "Epic": 15,
    "Mythic": 10,
    "Legendary": 7,
    "Ultra Legendary": 3,
}

STARR_DROP_LOOT = {
    "Rare": [...],
    "Super Rare": [...],
    # ...
}
```

---

## Emoji Collections

```python
EMOJIS_CURRENCY = {"coins": "<:coins:123>", "power_points": "<:pp:456>", "credits": "<:cred:789>"}
EMOJIS_RARITIES = {"rare": "<:rare:...>", "epic": "<:epic:...>", ...}
EMOJIS_BRAWLERS = {"shelly": "<:shelly:...>", "colt": "<:colt:...>", ...}
```

Used by the drop and collection display code in `features/brawl/`.

---

## Shop Data

```python
SHOP_DATA = {
    "brawl pass": {
        "display": "**Brawl Pass**",
        "price": 5000,
        "description": "A monthly Brawl Stars Brawl Pass."
    },
    # ...
}
```

Used by `/shop`, `/buy`, and `/redeem` in `features/economy.py`.

---

## Runtime Toggle: Test Mode

```python
TOURNEY_TEST_MODE: bool = False
```

Can be toggled at runtime by an admin command. When `True`:
- Max open tickets per user: 100 (normally 3)
- Ticket open cooldown: 0.1s (normally 180s)

The `_check_ticket_limits_for_user()` function in `tourney_utils.py` reads `config.TOURNEY_TEST_MODE` live (via `import features.config as config`) so changes take effect immediately without restarting.

---

## Passive Reward Exclusion

```python
PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS: list[int] = [
    ANNOUNCEMENTS_CHANNEL_ID,
    BOT_COMMANDS_CHANNEL_ID,
    # ...
]
```

The `on_message` listener in `economy.py` skips token and XP earning for messages in these channels.

---

## Source File
`features/config.py`
