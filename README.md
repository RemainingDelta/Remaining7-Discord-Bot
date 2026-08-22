# Remaining7 Discord Bot

## Overview
**Name:** Remaining7 Discord Bot
**Version:** v1.12.0
**Contributors:** remainingdelta, nightwarrior5
**Objective:** A feature-rich Discord bot for the Remaining7 community server (16k+ members). Handles an R7 Token economy, leveling, quests, a Brawl Stars collection minigame, tournament management with Matcherino integration, support tickets, event operations, a security protocol, and multi-language translation.
**Server Link:** https://discord.gg/6MzrjS2X8k

---

## Tech Stack
- **Language:** Python 3.10+
- **Framework:** `discord.py` (slash commands + prefix commands)
- **Database:** MongoDB Atlas via `motor` (async)
- **Translation:** `deep-translator` + `langdetect`
- **External API:** Matcherino (tournament brackets, payouts)
- **AI Integration:** Gemini API (GitHub issue generation)
- **Linting:** Ruff (`ruff check .` / `ruff format .`)

---

## Project Structure
```
Remaining7-Discord-Bot/
├── main.py                          # Entry point — loads cogs, syncs commands
├── pyproject.toml                   # Project metadata and version
├── requirements.txt
├── Makefile
├── LICENSE
├── .env.example
├── .gitignore
├── README.md
├── docs/                             # Feature implementation guides
│   └── logs/                         # SPECS.md & CHANGELOG.md — development history
├── database/
│   └── mongo.py                     # All MongoDB helper functions
├── features/
│   ├── config.py                    # IDs, shop data, loot tables, emojis (REAL/TEST branches)
│   ├── economy.py                   # R7 Tokens, shop, daily, leveling, leaderboards
│   ├── quests.py                    # Daily & weekly quest system
│   ├── security.py                  # Hacked protocol (timeout, purge, flag)
│   ├── scam_detection.py            # Scam image detection (MD5/pHash/ORB blacklist)
│   ├── event.py                     # Event channel cleanup & reward payouts
│   ├── general.py                   # /help, /mod-help, /admin-help, /version, /convert-time
│   ├── translation.py               # !t prefix & /translate slash command (54 languages)
│   ├── counting.py                  # Sequential counting game with /set-count
│   ├── story.py                     # Collaborative one-word story game (staff-run, moderated)
│   ├── sticky.py                    # !sticky / !unsticky persistent channel messages
│   ├── support_tickets.py           # General support tickets (issues, support, apps, partnership)
│   ├── github_tickets.py           # AI-powered GitHub issue creation from tickets (Gemini)
│   ├── event_tickets.py            # Private event answer-submission tickets
│   ├── ticket_command_router.py     # Shared routing for tourney & support ticket commands
│   ├── booster_shoutout.py          # Auto-opened booster shoutout tickets
│   ├── message_mirror.py            # Moderator message link mirror via webhook
│   ├── brawl/
│   │   ├── brawlers.json            # Brawler data (name, rarity, gadgets, star powers, hypercharges)
│   │   ├── brawlers.py              # Brawler dataclass definitions
│   │   ├── commands.py              # /megabox, /starrdrop, /profile, /upgrade, etc.
│   │   └── drops.py                 # Weighted RNG drop logic
│   └── tourney/
│       ├── tourney_commands.py      # All tournament slash & prefix commands
│       ├── tourney_utils.py         # Ticket lifecycle helpers, auto-translation
│       ├── tourney_views.py         # discord.ui.View classes for ticket buttons
│       ├── tourney_reports.py       # Monthly tournament report generation
│       └── matcherino.py            # Matcherino API integration
├── scripts/
│   └── generate_specs.py            # Generates docs/logs/ SPECS & CHANGELOG from GitHub data
├── tests/                            # Pytest unit tests (pure functions & regex helpers)
├── .claude/                          # Claude Code project config (tracked, see Workflow)
│   ├── settings.json                # Hook registrations
│   ├── hooks/                       # format-file, require-tests, stop-checks, check-config-parity
│   └── skills/                      # Repo slash commands (/ship, /pr-desc, /write-tests, ...)
└── .github/
    ├── ISSUE_TEMPLATE/
    │   ├── bug.md
    │   ├── enhancement.md
    │   └── feature.md
    └── workflows/
        ├── lint.yml                 # Ruff linting CI
        ├── tests.yml                # Pytest CI
        ├── version-check.yml        # Blocks PRs into main without a pyproject.toml version bump
        └── pr-issue-reference-check.yml  # Verifies issue number matches across branch/title/body
```

---

## Core Features

### R7 Token Economy
- **Passive Income:** Users earn 2–5 R7 Tokens per message (20-second cooldown), restricted to the general and booster channels. Server Boosters get a ~10% increase in tokens on average.
- **Daily Rewards:** `/daily` grants 80–160 tokens (scaled by level). Requires 5 messages sent since last claim and a 24-hour cooldown.
- **Supply Drop:** `/drop <amount>` (Admin) to force a token drop in general chat.
- **Balance & Ranking:** `/balance [user]`, `/leaderboard token`.
- **Give & Set:** `/give <user> <token/xp/level> <amount>`, `/set-balance <user> <amount>` (Admin).
- **Permissions:** `/perm <user> <add/remove>` to grant/revoke command access.
- **Guide:** `/economy-help` for a full user-facing guide.

### Shop & Budget System
- **Browse:** `/shop` lists items with prices and descriptions.
- **Purchase:** `/buy <item>` with dropdown selection and balance check.
- **Redeem:** `/redeem <item>` to claim a purchased reward.
- **Monthly Cap:** $50.00 monthly budget, auto-resets each calendar month.
- **Budget Check:** `/check-budget` shows spent vs. remaining.
- **Budget Override:** `/set-budget <amount>` (Admin).
- **Redemption Queue:** `/redemption-queue` lists your queued redemptions (items awaiting next month's budget); staff manage the queue with `/redemption-queue-list` and `/redemption-queue-remove <entry_id>`.

### Leveling & XP
- XP earned passively from messages alongside tokens, restricted to the general and booster channels.
- `/level [user]` — progress bar and next-level XP goal.
- `/leaderboard level` — server-wide level rankings (paginated).

### Quest System
Every user always has **4 active quests** — one daily and one weekly per category:
- **Daily Message Quests:** 80 / 160 / 240 messages → 50 / 115 / 250 tokens + 100 / 200 / 300 XP.
- **Weekly Message Quests:** 500 / 750 / 1000 messages → 225 / 400 / 640 tokens + 1000 / 2000 / 3000 XP.
- **Daily Megabox Quest:** Open 100 Mega Boxes or Starr Drops → 50 tokens + 100 XP.
- **Weekly Megabox Quest:** Open 500 Mega Boxes or Starr Drops → 250 tokens + 500 XP.
- `/quests` — interactive progress bars for all 4 active quests.
- `/reset-quests <user>` (Admin) — force-reset a user's quest assignments.
- Quests auto-assign randomly per slot; completion rewards are granted instantly.
- Server Boosters get quest targets cut by 20% (decided and stored at assignment time).

### Server Booster Perks
- **Token & XP Bonus:** ~10% average increase in both passive token and XP earning (35% chance of +1 per message on each).
- **Daily Bonus:** Flat +20 tokens added to every `/daily` claim.
- **Booster Channel:** Exclusive `#general-plus` channel with its own supply drops (10–25 tokens, roughly every 2 hours) — first booster to claim wins it.
- **Shop Discount:** 10% off one purchase per calendar month, requires 14+ consecutive days boosted.
- **Reduced Quest Thresholds:** Quest targets cut by 20%, applied at assignment time.
- **Booster Shoutout:** Boosting for the first time auto-opens a private ticket (once per calendar month) where the booster can submit a message for staff to feature.
- **Guide:** `/booster-perks` — full perk summary embed.

### Brawl Stars Collection Minigame
- **Gacha Drops:**
  - `/megabox` — open a Mega Box (coins, power points, brawlers, gadgets, star powers).
  - `/starrdrop` — open a Starr Drop with tiered rarity (Rare → Ultra Legendary).
- **Collection:**
  - `/profile [user]` — currencies, collection progress, stats.
  - `/brawlers` — paginated view of owned brawlers with levels.
  - `/buy-brawler` — purchase unowned brawlers by rarity using Credits.
- **Progression:**
  - `/upgrade <brawler>` — interactive upgrade dashboard (Level 1–11).
  - `/buy-ability <brawler>` — Gadgets (Lvl 7+), Star Powers (Lvl 9+), Hypercharges (Lvl 11+).
- **Currencies:** Coins, Power Points, Credits, Gems (separate from R7 Tokens).
- **Rarities:** Starting, Rare, Super Rare, Epic, Mythic, Legendary, Ultra Legendary, Chromatic.
- New users auto-receive Shelly at Level 1. Duplicate brawlers convert to Power Points.

### Tournament System
- **Phase Management:**
  - `!starttourney [region]` — start live tournament, reset counters, init queue dashboard. Use `!starttourney SA` for South America mode. The bot auto-resumes tourney state (dashboards, slow-mode/lock timers, region, ticket counter) after a restart; pass `force` (`!starttourney [region] force`) to restart setup over an already-active session.
  - `!endtourney` — end tournament, clean up dashboards and tickets, auto-post Hall of Fame.
- **Ticket Panels:** `/tourney-panel` (live) and `/pre-tourney-panel` (pre-tourney) post interactive open buttons.
- **Ticket Operations:**
  - `!close` / `!c` — close a ticket.
  - `!delete` / `!del` — delete ticket with transcript.
  - `!reopen` — reopen a closed ticket.
  - `/add <user>` / `/remove <user>` — manage ticket access.
- **Queue:** `/queue` — check your position in line (inside a tourney ticket only).
- **Queue Dashboard:** Auto-updating embed every 15 seconds showing currently serving and queue length.
- **Matcherino Integration:**
  - `/set-matcherino <id>` — link active Matcherino bracket.
  - `/match-info <match_id>` — display roster for a specific match.
  - `/match-history <team>` — view match history.
  - `/set-ticket-match <team1> <team2>` — assign match context to a ticket.
  - `/tourney-progress` — bracket progress dashboard with semi-final/final announcements.
- **Hall of Fame:** `/hall-of-fame` — post winning teams with prize distribution; also auto-triggered by `!endtourney` using the session's Matcherino ID.
- **Blacklist:** `/blacklist add/remove/list` — manage banned users (Discord ID, Matcherino profile, reason, alts).
- **Rate Limits:** Max 3 open tickets per user, 180s cooldown. Auto-reopen after 6-hour lock.
- **Auto-translation:** Ticket messages auto-translated via `deep-translator` + `langdetect`.
- **Test Mode:** `/tourney-test-mode` — toggle 100-ticket limit and 0.1s cooldown for testing.
- **Active Matches:** `/active-matches` — display all active match scores grouped by round.
- **Monthly Reports:** Auto-generated monthly tournament reports posted to a dedicated archive channel. Matcherino ID is auto-detected on `!starttourney`. `/monthly-report [month] [year]` (Staff) generates or re-generates a report on demand.
- **Slow Mode:** `!starttourney` enables 60s slow mode in general chat with a public notice; auto-removed after 1 hour (or immediately on `!endtourney`).
- **Staff Guide:** `/tourney-admin-help`.
- **SA Mode:** South America region variant with separate ticket categories and region-specific workflow.

### Tournament Admin Compensation
- `/payout-add <users...> <amount>` — record staff payouts (Split or Flat mode).
- `/payout-list` — view pending balances.
- `/payout-history [page]` — audit log of group payouts (filters out paid users).
- `/payout-reset` — clear a staff member's balance and archive receipts.

### Support Tickets (Non-Tournament)
- `/support-panel` — post the master support ticket panel.
- **Ticket Types:**
  - Report an Issue — bugs, rule violations, technical problems.
  - Server Support — general server assistance.
  - Staff Application — apply for Event Staff (Tourney Admin / Moderator closed).
  - Server Partnership — propose a partnership.
- One open ticket per type per user.
- Staff can close, reopen, and delete tickets with transcript generation.
- Transcripts DM'd to the opener and archived in a log channel.

### Event Tickets
- `/event-ticket-panel` — post the event ticket panel (Event Staff only).
- Members click **Open Event Ticket** to get a private channel for their event submission.
- Channels are named after the opener (`「❗」event-username`); **one open ticket per member**.
- Event Staff can close, reopen, and delete tickets via `!close` / `!reopen` / `!delete`.
- Closing renames the channel in place (`「❗」` → `「👍」`) and locks the opener to read-only — the channel is not moved.
- Deleting saves a transcript to the event transcript channel and DMs a copy to the opener.

### GitHub Ticket Integration
- AI-powered GitHub issue creation from support tickets using Gemini.
- Automatically generates structured bug reports, feature requests, and enhancement issues from ticket conversations.
- Requires `GEMINI_TOKEN` and `GITHUB_TOKEN` environment variables.

### Event Management
- **Automated Monitoring:** Daily background task at 12:00 AM ET scans event channels.
- **Smart Alerts:** Alert sent when messages are 7+ days old (prevents exceeding Discord's 14-day bulk-delete limit). Previous day's alert is replaced instead of stacking.
- **Manual Cleanup:** `/clear-red`, `/clear-blue`, `/clear-green` for instant channel wipes.
- **Reward Payouts:** `/event-rewards <message_id>` parses `@User 500` format to batch-distribute tokens with confirmation. Payouts run through a per-recipient ledger, so a crash-and-retry never double-pays.
- **Poll Rewards:** `/poll-rewards <message_id> <answer> <amount>` distributes tokens to users who voted a given answer on a poll.
- **Stuck Payouts:** `/check-stuck-payouts [resolve]` lists (or resolves) payouts that were claimed but never confirmed paid after an interruption.
- **Staff Guide:** `/event-staff-help`.

### Security Protocol
- `/hacked <user>` or `!hacked` (reply) — instantly timeout (7 days), flag in DB, purge messages across all channels.
- `/unhacked <user>` — remove flag and timeout.
- `/hacked-list` — view all currently flagged users.
- Logs to moderator logs channel. Prevents targeting equal/higher role members.

### Scam Image Detection
- Automatically scans every image attachment against a MongoDB blacklist using three matchers: MD5 (identical files), pHash (re-compressed/resized copies), and ORB (cropped variants).
- On a match: deletes the message, purges other copies of the image across all channels (30-min lookback), applies a 10-minute precautionary timeout, and sends a mod alert with the image and action buttons.
- **Confirm Hacked** button — upgrades to a 7-day timeout, flags the user in the hacked DB, and DMs them. **False Positive** button — removes the timeout.
- `!scam-add` (reply or attach) — add image(s) to the blacklist.
- `!scam-remove <md5> [md5 ...]` — remove entries by MD5 prefix.
- `!scam-list` — view all blacklisted images.
- `!scam-rename <md5> <name>` — give an entry a readable name.
- `!scam-test` (reply or attach) — dry-run detection with match distances, no action taken.

### Message Mirror
- Moderators can repost any message by pasting its Discord link alone in a message — the bot mirrors it via a temporary webhook using the original author's name and avatar in the current channel.

### Translation
- `!t [language]` / `!translate [language]` — reply to a message to translate it to English.
- `/translate <language> <phrase>` — translate English text into any of 55 supported languages.
- Auto-detects source language. Google Translate backend.

### Counting Game
- Sequential counting game in a designated channel — users must send the next number in sequence.
- `/set-count <number>` (Staff) — manually set the current count.

### One-Word Story
- Collaborative story built one word per message in a designated channel, active only between staff `/story-start` and `/story-end`. Each accepted word gets a ✅; invalid messages (multi-word, emojis, banned words/characters, same user twice in a row) are removed.
- Configurable, MongoDB-backed banned-word and banned-character lists (the default profanity list is fetched from a public source, not committed to the repo).
- `/story-see` — view the current story. `/story-start`, `/story-end`, `/story-reset`, `/story-banword`, `/story-banchar` (Staff) — run and moderate stories.

### Sticky Messages
- `!sticky <message>` — pin a message that reposts automatically when other messages are sent. Usable by Admins and Event Staff.
- `!unsticky` — remove the active sticky message from a channel.

### Utility
- `/convert-time <date> <time> <timezone>` — convert a date and time to all Discord timestamp formats. Supports 20+ timezone aliases (EST, PT, GMT, etc.) and IANA names.
- `/version` — view the bot's current version.

### Help Commands
- `/help` — user command directory.
- `/economy-help` — full guide to earning and spending R7 Tokens.
- `/mod-help` — moderator guide (economy oversight, security protocol).
- `/admin-help` — admin manual (economy, events, security, tournaments, financials).
- `/tourney-admin-help` — tournament staff cheat sheet.
- `/event-staff-help` — event channel management guide.

---

## Setup & Run Instructions

This bot requires **Python 3.10+** and a **MongoDB Atlas** database.

1. **Clone the Repository**
    ```bash
    git clone https://github.com/RemainingDelta/Remaining7-Discord-Bot
    cd Remaining7-Discord-Bot
    ```

2. **Setup Virtual Environment & Dependencies**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Linux/macOS
    # or venv\Scripts\activate on Windows
    pip install -r requirements.txt
    ```

3. **Configure Environment Variables**
    Copy `.env.example` to `.env` and fill in the values:
    ```
    BOT_MODE=DEV            # DEV (default) or PROD
    PROD_TOKEN=             # Production bot token (used when BOT_MODE=PROD)
    DEV_TOKEN=              # Dev/test bot token (used when BOT_MODE=DEV)
    MONGO_URI=              # MongoDB Atlas connection string
    GEMINI_TOKEN=           # Gemini API key for AI-powered GitHub issue creation
    GITHUB_TOKEN=           # GitHub PAT with 'repo' scope for issue creation
    ```

4. **Update Configuration**
    Verify and update IDs in `features/config.py` (channels, roles, categories, emojis) for your server. Both `PROD` and `DEV` branches must be maintained.

5. **Run the Bot**
    ```bash
    python main.py
    ```

    Unit tests cover pure functions and regex helpers (`pytest`); most behavior is still tested by running the bot with `BOT_MODE=DEV` against a test Discord server.

---

## Hosting

The bot runs 24/7 on **RamNaym Cloud** (Nano plan, the lowest paid tier), deployed via GitHub zip download.

| | |
|---|---|
| **Host** | RamNaym Cloud |
| **Plan** | Nano (lowest paid tier) |
| **Plan specs** | 0.10 CPU · 256 MB RAM · 2 GB disk |
| **Cost** | 4 EUR/year (≈ $4.55 USD as of now; paid $4.75) |

**Current usage** (refresh if the plan or load changes materially):

| Resource | Usage |
|---|---|
| vCPU load | 0.5% |
| Memory | 126.6 / 256.0 MB |
| Project storage | 2.1 MB / 2.00 GB |

See [`docs/HOSTING.md`](docs/HOSTING.md) for the full hosting history and the reasoning behind the migration from the previous host.

---

## Database

Uses MongoDB database `r7_bot_db` with the following collections:

| Collection | Purpose |
|---|---|
| `users` | Balance, XP, level, brawler collection, currencies, inventory |
| `user_quests` | Quest progress tracking (daily/weekly) |
| `quests` | Quest definitions |
| `hacked_users` | Flagged compromised accounts |
| `blacklist` | Tournament-banned users |
| `payouts` | Pending staff payouts |
| `payout_logs` | Payout batch audit logs |
| `tourney_sessions` | Active tournament session data |
| `tourney_staff_stats` | Staff performance metrics |
| `support_ticket_counters` | Ticket counters per type |
| `settings` | Global bot settings (budget, etc.) |

---

## Background Tasks

| Task | Schedule | Description |
|---|---|---|
| Message listener | On every message | XP generation; passive token earning restricted to general chat (20s cooldown) |
| Quest tracker | On every message / megabox open | Track message & megabox quest progress, auto-complete and reward |
| Event cleanup | Daily at 12:00 AM ET | Scan event channels for stale messages |
| Queue dashboard | Every 15 seconds | Update tourney queue embed during live tournaments |
| Supply drop | Every 6 hours | Random token drop in general chat |
| Progress dashboard | Every 5 minutes (live) | Semi-final/final bracket announcements |
| Match refresher | Every 1 minute (live) | Refresh Matcherino scores in active tickets |
| Budget reset | On interaction | Auto-reset monthly redemption cap on month change |

---

## Permission Hierarchy

| Role | Access |
|---|---|
| Admin | Full access to all commands |
| Moderator | Economy oversight, security protocol |
| Tourney Admin | Tournament commands, ticket management |
| Event Staff | Event channel cleanup, reward distribution, sticky messages |
| Member | Economy, quests, brawl, translation, help |

---

## Workflow
- Active development on `dev` branch.
- Feature/bug branches merge into `dev` via PR.
- `dev` merges into `main` for release.
- Ruff enforced via CI (`.github/workflows/lint.yml`); pytest suite runs on every push/PR (`tests.yml`).
- Common dev tasks are wrapped in the `Makefile`: `make test`, `make lint`, `make fix`, `make ci`, `make up`, and `make commit m="..."` (stages, commits, and pushes in one step).
- PRs into `main` are blocked unless `pyproject.toml`'s version was bumped (`version-check.yml`).
- PRs into `dev` are checked for a consistent issue number across branch name, title, and body (`pr-issue-reference-check.yml`).
- `.claude/` is tracked in git, so hooks and skills survive a fresh clone. Three hooks run automatically in Claude Code sessions:
  - **On every Python write** — `ruff format` on that one file, and the bot is flagged for restart. Formatting only; `ruff check --fix` deletes unused imports, which breaks a multi-edit sequence that writes an import before the line using it.
  - **Before editing `features/` or `database/`** — the edit is blocked unless the ticket branch has touched something under `tests/`. Bypass a session with `SKIP_TEST_GATE=1 claude`.
  - **At the end of a turn** — `features/config.py` is checked for IDs added to only one of the REAL/TEST branches (a silent break on one server), then `ruff check --fix` runs and the bot is relaunched from `.venv/`. Suppress the restart with `touch /tmp/claude-no-restart`.
- Machine-specific Claude config (`.claude/settings.local.json`) stays ignored.

---

## Future Roadmap
- [ ] Brawl Stars: View for a specific brawler's details
- [ ] Giveaway system with extra entries via R7 Tokens
