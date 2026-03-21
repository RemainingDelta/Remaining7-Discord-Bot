# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview
A feature-rich Discord bot for the Remaining7 community (~15k members). Built with `discord.py` and MongoDB. Handles economy, leveling, tournaments, moderation, and a Brawl Stars collection minigame.

**Repo:** https://github.com/RemainingDelta/Remaining7-Discord-Bot

---

## Stack
- **Language:** Python 3.10+
- **Framework:** discord.py (slash commands + prefix commands)
- **Database:** MongoDB Atlas via Motor (async) — `motor.motor_asyncio`
- **Config:** Environment variables via `.env` + `features/config.py` for server IDs/role IDs

---

## Run Instructions
```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

Required `.env` vars (see `.env.example`):
- `BOT_MODE` — `TEST` (default) or `REAL`; controls which server IDs and token are used
- `DISCORD_TOKEN` — production bot token (used when `BOT_MODE=REAL`)
- `FAKE_TOKEN` — dev/test bot token (used when `BOT_MODE=TEST`)
- `MONGO_URI` — MongoDB Atlas connection string

There is no test suite. Testing is done by running the bot with `BOT_MODE=TEST` against a test Discord server.

---

## Architecture

### Entry Point (`main.py`)
Initializes the bot and loads all cogs in `on_ready`. Commands are globally synced at startup via `bot.tree.sync()`. The bot uses `BOT_MODE` to determine which token to run with.

### Dual-Environment ID System (`features/config.py`)
`config.py` branches on `BOT_MODE` to set all channel/role/category IDs for either the production or test Discord server. This means every channel ID, role ID, and custom emoji ID has two values — one for REAL, one for TEST. When adding new IDs, add them to **both** branches.

`config.py` also holds: `SHOP_DATA`, `MEGA_BOX_LOOT`, `STARR_DROP_LOOT`, `STARR_DROP_RARITIES`, `BRAWLER_PRICES`, `BRAWLER_UPGRADE_COSTS`, emoji dictionaries (`EMOJIS_CURRENCY`, `EMOJIS_RARITIES`, `EMOJIS_BRAWLERS`, etc.), and `ALLOWED_STAFF_ROLES`.

### Database Layer (`database/mongo.py`)
Single file containing all MongoDB helpers — user data, leveling, economy, brawler collection, quest system, tournament stats, blacklist, payout tracking, and support ticket counters. The database is `r7_bot_db`. Key collections: `users`, `user_quests`, `quests`, `hacked_users`, `blacklist`, `payouts`, `payout_logs`, `tourney_sessions`, `tourney_staff_stats`, `support_ticket_counters`, `settings`.

All new DB operations should be added as async helper functions here, not inline in command handlers.

User documents store R7 Token balance (`balance`), XP/level, `brawlers` (map of brawler_id → stats), `currencies` (coins/power_points/gems/credits for the Brawl gacha), and `inventory`.

### Feature Cogs (`features/`)
Each file is a discord.py Cog loaded in `main.py`. Exception: the tournament system.

- `economy.py` — R7 Tokens, shop, `/buy`, `/leaderboard`, daily rewards, XP/leveling
- `quests.py` — daily/weekly quest assignment and progress tracking
- `security.py` — `/hacked` / `/unhacked` commands
- `event.py` — background task for purging old event channel messages (runs at 12 AM ET)
- `general.py` — miscellaneous commands
- `translation.py` — auto-translation integration
- `support_tickets.py` — general support ticket system (issues, server support, staff apps, partnership, redemption)
- `ticket_command_router.py` — shared routing logic between tourney and support ticket systems

### Tournament System (`features/tourney/`)
**Not loaded as a standard Cog.** Instead, `setup_tourney_commands(bot)` is called directly in `on_ready`. This is legacy architecture — do not refactor without careful consideration.

- `tourney_commands.py` — all tournament slash and prefix commands (`!starttourney`, `!endtourney`, etc.), payout management, blacklist management, queue dashboard (auto-updates every 15s)
- `tourney_utils.py` — ticket lifecycle helpers (open/close/reopen/delete with transcript), in-memory ticket counter and rate-limit tracking, auto-translation via `deep_translator`/`langdetect`
- `tourney_views.py` — `discord.ui.View` classes for ticket open buttons
- `matcherino.py` — Matcherino API integration (ticket context, payout reports, bracket progress)

### Brawl Stars Gacha (`features/brawl/`)
- `commands.py` — Cog with `/megabox`, `/starrdrop`, `/collection`, `/upgrade`, `/shop` (brawl shop) slash commands
- `drops.py` — weighted RNG drop logic using loot tables from `config.py`
- `brawlers.py` — dataclass definitions for brawlers loaded from `brawlers.json`
- `brawlers.json` — brawler data (name, rarity, gadgets, star powers, hypercharges)

---

## Coding Conventions
- Use `discord.py` Cogs for all new feature modules
- Slash commands preferred; prefix commands (`!`) used for tourney admin ops
- Keep MongoDB interactions in `database/mongo.py` helper functions, not inline in commands
- Never hardcode IDs — use `features/config.py`, and always add to **both** `REAL` and `TEST` branches
- Custom emoji strings for display come from `EMOJIS_*` dicts in `config.py`
- Staff permission checks use `is_staff(member)` from `tourney_commands.py` which checks `ALLOWED_STAFF_ROLES`

---

## Key Systems & Notes

### Economy
- R7 Tokens stored in `balance` field; passive earn: 2–5 tokens per message (1-min cooldown)
- Monthly redemption budget cap: $50.00 — auto-resets monthly via `ensure_monthly_budget_state()`
- Shop items have real-world dollar values in `REDEMPTION_BUDGET_COSTS` tracked separately from token prices in `SHOP_DATA`

### Tournament Tickets
- Two phases: pre-tourney and live tourney (toggled via `!starttourney` / `!endtourney`)
- Tickets have a 50-channel Discord limit — old archived tickets auto-delete when limit is hit
- Blacklist stores Discord ID, Matcherino profile, reason, and alts

### Brawl Stars Collection
- New users always get Shelly at level 1; `get_user_data()` in `mongo.py` has self-healing logic to add Shelly if missing
- Duplicate brawlers give 15 Power Points instead
- Brawler IDs are lowercase strings (e.g., `"shelly"`, `"8bit"`, `"larrylawrie"`)

### Security
- `/hacked` instantly timeouts user (7 days), flags in DB, purges recent messages across all channel types
- `/unhacked` reverses this
