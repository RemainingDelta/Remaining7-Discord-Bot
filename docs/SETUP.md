# Setup & Porting Guide

## Overview
This document covers everything needed to stand up the bot from scratch or port specific features (tournament system, hacked command) to a new Discord bot. It covers dependencies, bot permissions, `.env` configuration, cog loading order, and a per-feature minimum requirements checklist.

---

## Requirements

**Python version**: 3.10+

**Install dependencies**:
```bash
pip install -r requirements.txt
```

### `requirements.txt`
```
discord.py>=2.7
python-dotenv>=1.2
motor>=3.7
dnspython>=2.8
certifi>=2026.2
uuid>=1.30
deep-translator>=1.11
langdetect>=1.0
requests>=2.33
requests-cache>=1.3
beautifulsoup4>=4.14
pytest>=7.0
pytest-asyncio>=0.23
opencv-python-headless>=4.8
numpy>=1.26
aiohttp>=3.9
ruff==0.16.0
```

| Package | Used by |
|---------|---------|
| `discord.py>=2.7` | Everything — 2.7 specifically is required for the `discord.ui.FileUpload` / `discord.ui.Label` modal components used by tourney ticket image upload |
| `motor` | All MongoDB operations (async driver) |
| `dnspython` + `certifi` | Required by motor for MongoDB Atlas SRV connection strings |
| `python-dotenv` | Loading `.env` file |
| `deep-translator` | Translation cog + tourney ticket auto-translation |
| `langdetect` | Language auto-detection for translation |
| `requests` + `requests-cache` | Matcherino API calls |
| `beautifulsoup4` | Matcherino HTML scraping (payout report) |
| `uuid` | Payout batch IDs |

---

## Discord Bot Permissions

### Required Privileged Intents (Discord Developer Portal)
Enable these under **Bot → Privileged Gateway Intents**:

| Intent | Used for |
|--------|---------|
| `Message Content` | Reading message content in `on_message` (passive rewards, counting, sticky, quest tracking) |
| `Server Members` | Reading member roles (staff checks, booster detection) |
| `Invites` | Enabled but currently unused (no active consumer) |

In `main.py`:
```python
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.invites = True
bot = commands.Bot(command_prefix="!", intents=intents)
```

### Bot Permissions (OAuth2 Scopes)
When generating the invite URL, select **bot** + **applications.commands** scopes. Recommended permissions:

| Permission | Used for |
|-----------|---------|
| Manage Channels | Creating/deleting ticket channels |
| Manage Roles | Granting `moderate_members` to Tourney Admin on `!starttourney` |
| Manage Messages | Deleting messages (counting, sticky, hacked purge, channel purge) |
| Send Messages | All bot responses |
| Embed Links | All embed responses |
| Attach Files | Transcript uploads |
| Read Message History | Transcript generation, queue dashboard, event monitoring |
| Moderate Members | Timing out users (`/hacked`) |
| View Channels | Reading channel state |

---

## `.env` File

```env
# Bot tokens (one will be used depending on BOT_MODE)
PROD_TOKEN=your_production_bot_token
DEV_TOKEN=your_development_bot_token

# Controls which token and which config IDs are used
BOT_MODE=DEV         # or PROD
ENVIRONMENT=DEV      # or PROD — controls IDs in config.py

# Database
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority

# Optional integrations
GEMINI_TOKEN=your_gemini_api_key
GITHUB_TOKEN=your_github_pat
GITHUB_REPO=owner/repo-name
```

`BOT_MODE` selects which Discord token to use. `ENVIRONMENT` controls which set of channel/role IDs to load from `config.py`. They're separate so you can run the production token against DEV IDs during testing.

---

## Cog Loading Order (`main.py`)

The order in `on_ready` matters for a few cogs:

```python
await bot.load_extension("features.general")
await bot.load_extension("features.economy")
await bot.load_extension("features.event")
await bot.load_extension("features.security")
await bot.load_extension("features.brawl.commands")
await bot.load_extension("features.quests")
await bot.load_extension("features.translation")
await bot.load_extension("features.support_tickets")
await bot.load_extension("features.github_tickets")
await bot.load_extension("features.sticky")
await bot.load_extension("features.counting")
await bot.load_extension("features.tourney.tourney_reports")

# Tourney system uses a setup function, not load_extension
setup_tourney_commands(bot)
await restore_tourney_panels(bot)   # Re-registers persistent views after restart

# Always last
await bot.tree.sync()
```

`restore_tourney_panels()` must run after `setup_tourney_commands()`. `bot.tree.sync()` must always be last — syncing before all cogs are loaded will miss slash commands.

---

## Minimum Config IDs Required Per Feature

When porting a feature to a new bot, these are the IDs you must set in `config.py`.

### Tournament System (full)
```python
TOURNEY_SUPPORT_CHANNEL_ID       # Where the live ticket panel is posted
PRE_TOURNEY_SUPPORT_CHANNEL_ID   # Where the pre-tourney panel is posted
TOURNEY_CATEGORY_ID              # Active live ticket category
PRE_TOURNEY_CATEGORY_ID          # Active pre-tourney ticket category
TOURNEY_CLOSED_CATEGORY_ID       # Closed live ticket category
PRE_TOURNEY_CLOSED_CATEGORY_ID   # Closed pre-tourney ticket category
TOURNEY_ADMIN_CHANNEL_ID         # Where !starttourney / !endtourney are run
TOURNEY_UPDATES_CHANNEL_ID       # Where stage announcements are posted
TOURNEY_SCHEDULE_CHANNEL_ID      # Scanned for Matcherino ID auto-detection
TOURNEY_REPORT_CHANNEL_ID        # End-of-tourney stat embeds archive
LOG_CHANNEL_ID                   # Ticket transcript log
OTHER_TICKET_CHANNEL_ID          # General support channel (locked during tourney)
SPANISH_CHANNEL_ID               # Spanish channel (only needed for SA region mode)
GENERAL_CHANNEL_ID               # Gets 60s slowmode during live tourney
TOURNEY_STAFF_ROLES              # list[int] — role IDs that can manage tickets
TOURNEY_ADMIN_ROLE_ID            # Gets moderate_members during tourney
ADMIN_ROLE_ID                    # Gets renamed during tourney
MEMBER_ROLE_ID                   # Used for lock/unlock permission target
```

### Matcherino Only (minimal — no full tourney lifecycle)
```python
TOURNEY_ADMIN_CHANNEL_ID    # Where slash commands like /set-matcherino are used
TOURNEY_CATEGORY_ID         # For the 1-minute match refresher to scan
TOURNEY_SUPPORT_CHANNEL_ID  # For the queue dashboard
```
Plus `MONGO_URI` for `get_matcherino_id_from_active()`.

### Hacked System Only
```python
ADMIN_ROLE_ID            # Who can run /hacked
MODERATOR_ROLE_ID        # Who can run /hacked
MODERATOR_LOGS_CHANNEL_ID  # Where mod actions are logged
```
No other infrastructure needed — the hacked system is self-contained.

### Support Tickets Only
```python
SUPPORT_TICKET_CATEGORY_ID    # (and per-type categories)
REDEMPTION_TICKET_CATEGORY_ID
REDEMPTION_TRANSCRIPT_CHANNEL_ID
BOOSTER_SHOUTOUT_CATEGORY_ID
ADMIN_ROLE_ID
MODERATOR_ROLE_ID
```

---

## Porting the Tournament System to a New Bot

### Files to copy
```
features/tourney/
    matcherino.py          # No R7-specific references — copy as-is
    tourney_utils.py       # Replace config imports with new bot's config
    tourney_views.py       # Change button labels; update custom_ids if needed
    tourney_commands.py    # Heavy config dependency — audit all config imports
    tourney_reports.py     # Copy as-is, update channel IDs
database/mongo.py          # Copy the tourney-related helper functions
features/config.py         # Create a new one with new server's IDs
```

### What's server-agnostic (copy as-is)
- `matcherino.py` — pure API logic, no server IDs
- Fuzzy matching, visual match numbering, bracket progress scanning
- Transcript generation logic in `tourney_utils.py`
- Rate limiting logic in `tourney_utils.py`

### What needs updating
- All `config.py` imports in `tourney_commands.py` — replace with new server's IDs
- `TOURNEY_STAGE_HYPE_GIF_URL` in `tourney_commands.py` — hardcoded CDN URL, replace with your own
- `restore_tourney_panels()` — ensure it adds all persistent views for the new bot
- MongoDB collection names — currently shared names like `"tourney_sessions"`; if running on the same Atlas cluster, prefix them (e.g. `"rol_tourney_sessions"`) to avoid collisions

### What to strip if not needed
- Economy/payout commands inside `tourney_commands.py` (can be removed if the new bot doesn't track staff payments)
- SA region mode (`!starttourney sa`) — safe to remove if not needed
- Bracket snapshot/POC data collection (`collect_data`, `insert_tourney_snapshot`) — remove if not doing analytics
- Admin role rename logic in `!starttourney` / `!endtourney`

---

## Porting the Hacked System to a New Bot

The hacked system (`features/security.py`) is the most self-contained feature in the codebase. Dependencies:

1. `database/mongo.py` — needs `add_hacked_user`, `remove_hacked_user`, `get_hacked_users`
2. `features/config.py` — needs `ADMIN_ROLE_ID`, `MODERATOR_ROLE_ID`, `MODERATOR_LOGS_CHANNEL_ID`
3. No external APIs

Steps:
1. Copy `features/security.py`
2. Add the three config constants
3. Add the three mongo helpers
4. `await bot.load_extension("features.security")` in `main.py`
5. Sync slash commands

The 12-hour purge window and 7-day timeout duration are both constants defined inline in `_execute_hacked_action()` — trivial to adjust.

---

## Running Tests

```bash
pytest tests/
```

Tests use `pytest-asyncio`. Individual test files map 1:1 to feature files (e.g. `tests/test_matcherino.py` tests `features/tourney/matcherino.py`).

---

## Common Startup Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Token not found in .env` | Missing `PROD_TOKEN` or `DEV_TOKEN` | Add the correct token to `.env` |
| `MongoDB Connection Failed` | Bad `MONGO_URI` or network issue | Check Atlas IP allowlist and URI format |
| `Command Sync Error` | Slash commands sync failed | Usually a rate limit — wait and restart |
| Buttons dead after restart | `restore_tourney_panels()` not called or views not re-registered | Ensure `restore_tourney_panels(bot)` runs in `on_ready` |
| `Tourney category is not configured correctly` | `TOURNEY_CATEGORY_ID` points to wrong channel type | Must be a Category, not a Text Channel |
