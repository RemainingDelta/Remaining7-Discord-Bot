# CHANGELOG.md

## Purpose

This file is a chronological record of PR descriptions and release notes for the Remaining7 Discord Bot, pulled directly from GitHub releases. It is appended on every merge/release so the full release history remains available outside of GitHub itself.

Release body content below is preserved exactly as published — nothing has been edited, summarized, or reformatted.

---

## v1.0.0 — 2026-01-31T22:00:28Z

# 🚀 Release Notes v1.0.0

## 🎯 Features
### R7 Token Economy
- `/balance`, `/give`, `/setbalance` for token management
- Passive income of 2-5 tokens per message (1-minute cooldown)
- `/daily` command with level-based bonus multiplier
- `/drop` admin supply drops averaging every 6 hours

### Quest System
- Daily and weekly message-based challenges
- `/quests` with interactive progress bar
- Automatic token and XP rewards on completion
- Dynamic quest assignment from database

### Shop & Budget System
- `/shop`, `/buy`, `/redeem` for item purchasing and redemption
- $50.00 monthly budget cap with automatic reset
- `/checkbudget` for spending visibility

### Leveling & Leaderboards
- XP and level tracking with `/level` progress bar
- `/leaderboard` for tokens, `/levels_leaderboard` for levels

### Tournament & Ticketing
- `!starttourney` / `!endtourney` phase management
- Live queue dashboard with 15s auto-update
- `/queue` for position checking inside active tickets
- `/tourney-panel`, `/pre-tourney-panel` support panels
- `!close`, `!delete`, `!reopen` ticket control commands
- `/add`, `/remove` ticket access management
- `/blacklist add`, `/blacklist remove`, `/blacklist list`
- `/hall-of-fame` with automatic 50/25/15/10% prize split

### Tourney Admin Compensation
- `/payout-add` with Split and Flat modes
- `/payout-list`, `/payout-history`, `/payout-reset`

### Event Maintenance
- Daily automated scan of event channels at 12:00 AM ET
- Smart alerts at 7-day threshold with Purge button
- `/clear-red`, `/clear-blue`, `/clear-green` manual cleanup
- `/event-rewards` batch token distribution

### Security System
- `/hacked` and `!hacked` to instantly secure compromised accounts
- 7-day timeout with recursive message purge across all channels
- `/unhacked` for recovery, `/hackedlist` for visibility

### Brawl Stars Collection
- `/megabox` and `/starrdrop` gacha summoning with weighted rarity
- `/brawlers` paginated collection view
- Brawler leveling system using Coins and Power Points

### Admin Tools
- `/perm` to grant or revoke staff command access

## 📊 Data Model
- MongoDB schema established for users, economy, leveling, quests, tourney sessions, blacklist, and payouts

## 🎨 Embeds & UI
- Interactive embeds for `/level`, `/quests`, `/leaderboard`, `/brawlers`, and queue dashboard
- Button panels for tourney and pre-tourney support ticket creation

---

## v1.0.1 — 2026-01-31T22:40:19Z

# 🚀 Release Notes v1.0.1

## 🐛 Bug Fixes & Improvements
- **`!endtourney` stats panel not deleting:** `!endtourney` now reliably deletes the live stats panel on tourney end.

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.0.0...v1.0.1

---

## v1.0.2 — 2026-02-01T00:18:06Z

# 🚀 Release Notes v1.0.2

## 🎯 Features
### Searchable Transcript Logs
- Transcript messages now display team name and match number alongside the file attachment
- Staff can search for specific match transcripts in Discord without downloading files

## 🎨 Embeds & UI
- Transcript log messages now show `🛡️ Team: [Name] | 🔢 Match: [ID]` alongside the attachment

## 🐛 Bug Fixes & Improvements
- **Missing channel topic handling:** Added fallback logic to safely display `N/A` for older tickets or channels with missing topics instead of crashing

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.0.1...v1.0.2

---

## v1.1.0 — 2026-02-01T04:47:34Z

# 🚀 Release Notes v1.1.0

## 🎯 Features
### Shop Expansion & Pagination
- Added **Clash of Clans Gold Pass** ($7 / ~11,900 tokens) and **Clash Royale Diamond Pass** ($12 / ~20,400 tokens)
- Shop now paginates across multiple pages with `◀ Previous` and `Next ▶` navigation buttons
- Token costs for new items scaled to the server economy rate ($1 ≈ 1,700 tokens)

## 🎨 Embeds & UI
- `/shop` now displays paginated embeds to keep the menu clean and readable on all devices

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.0.2...v1.1.0

---

## v1.1.1 — 2026-02-08T05:55:42Z

# 🚀 Release Notes v1.1.1

## 🎯 Features
### Economy Cooldown Reduction
- Token earn cooldown reduced from **60 seconds** to **20 seconds**
- Active chatters can now earn tokens up to 3x faster than before

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.0...v1.1.1

---

## v1.1.2 — 2026-02-08T06:40:22Z

# 🚀 Release Notes v1.1.2

## 🎯 Features
### Staff Shop Restrictions
- `/buy` and `/redeem` are now disabled for Trial Moderators, Moderators, and Admins
- Ensures limited shop rewards remain exclusively available to community members

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.1...v1.1.2

---

## v1.1.3 — 2026-02-10T04:04:29Z

# 🚀 Release Notes v1.1.3

## 🎯 Features
### New Brawler: Glowbert
- Added **Glowbert** (Mythic) to the game and brawler shop

### Brawler Shop Pagination
- Shop now paginates across multiple pages, removing the previous 25-item display limit

## 🎨 Embeds & UI
- Brawler shop buttons updated with rarity-specific emojis for better visual clarity

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.2...v1.1.3

---

## v1.1.4 — 2026-02-14T02:51:50Z

# 🚀 Release Notes v1.1.4

## 🔒 Security & Monitoring
- `/payout-add` and `/payout-reset` are now restricted to Server Admins only
- Tourney Admins retain read-only access via `/payout-list` and `/payout-history`

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.3...v1.1.4

---

## v1.1.5 — 2026-02-14T03:37:59Z

# 🚀 Release Notes v1.1.5

## 🐛 Bug Fixes & Improvements
- **Token balance displaying as decimals:** `/balance`, `/buy`, `/daily`, and the token leaderboard now correctly display token amounts as whole numbers instead of long floating-point decimals

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.4...v1.1.5

---

## v1.1.6 — 2026-02-14T04:21:49Z

# 🚀 Release Notes v1.1.6

## 📊 Data Model
- Corrected brawler names, gadgets, star powers, and hypercharges in the brawler JSON to match 2026 game data
- Aligned all internal IDs and stats with the latest Brawl Stars data

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.5...v1.1.6

---

## v1.2.0 — 2026-02-14T05:24:14Z

# 🚀 Release Notes v1.2.0

## 🎯 Features
### Translation System
- Added bidirectional translation supporting 55 languages including Spanish, French, Chinese, and Vietnamese
- `!translate` / `!t` — reply to any message to translate it into English, shows detected language and original text
- `/translate` — translate English text into a target language via searchable autocomplete

### Other Changes
- Smart language detection automatically identifies the source language
- Zero-cost implementation using open-source libraries with no API credit requirements

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.6...v1.2.0

---

## v1.2.1 — 2026-02-14T18:21:43Z

# 🚀 Release Notes v1.2.1

## 🎯 Features
### Manual Source Language Override
- `!t <language>` now accepts an optional language name to bypass auto-detection (e.g. `!t hindi`)
- Eliminates guesswork on short phrases or slang for more reliable translations into English

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.2.0...v1.2.1

---

## v1.2.2 — 2026-02-14T19:01:07Z

# 🚀 Release Notes v1.2.2

## 🎯 Features
### Daily Chat Milestone Requirement
- `/daily` rewards now require at least 5 messages sent within the current day (UTC) to unlock
- If locked, the bot displays a combined status embed showing message progress and cooldown timer together

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.2.1...v1.2.2

---

## v1.3.0 — 2026-02-15T05:41:22Z

# 🚀 Release Notes v1.3.0

## 🎯 Features
### Help System
- Added role-based help command suite — each role only sees menus relevant to them
- `/help` — public directory covering Economy, Brawlers, and Tournaments
- `/economy-help` — deep-dive into earning tokens, the shop, and reward budgets
- `/mod-help` — economy oversight and security protocols for Moderators
- `/tourney-admin-help` — session management and Matcherino guide for Tourney Staff
- `/event-staff-help` — manual purge and cleanup guide for Event Staff
- `/admin-help` — full administrative override menu for Owners and Admins

## 🔒 Security & Monitoring
- All staff-facing help responses are ephemeral and hidden from public view

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.2.2...v1.3.0

---

## v1.4.0 — 2026-02-16T03:35:33Z

# 🚀 Release Notes v1.4.0

## 🎯 Features
### Matcherino Integration
- `/set-matcherino <id>` links the active tournament session to a Matcherino tournament ID
- When a ticket is opened with a match number, the bot automatically generates an embed with live match status, scores, and team names
- Three-column embed layout displays Team A and Team B rosters side-by-side with scoring and status indicators

## ⚡ Integrations
- Connected to the Matcherino API for live match data retrieval
- Matcherino ID is persisted to the database — set once per tournament, survives restarts and crashes
- Updated roster parsing to pull Matcherino display names directly from team member lists

## 📊 Data Model
- Tournament session now stores Matcherino ID in the database for persistence across reboots

## 🤖 GitHub Actions
- Added `requests` and `requests-cache` to requirements
- 60-second caching layer on API responses to prevent rate-limiting during peak tournament hours

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.3.0...v1.4.0

---

## v1.5.0 — 2026-02-16T19:29:08Z

# 🚀 Release Notes v1.5.0

## 🎯 Features
### Tournament Test Mode
- `/tourney-test-mode <enabled>` toggles a testing environment for dry runs and stress tests
- When active, ticket limits increase to 100 and cooldowns reduce to 0.1 seconds
- Test Mode automatically resets to off on bot restart, always failing safe to production limits
- Access restricted to authorized staff roles defined in config

## 🎨 Embeds & UI
- Tournament support panels turn red and display a warning footer when Test Mode is active to prevent accidental use during live events

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.4.0...v1.5.0

---

## v1.6.0 — 2026-02-21T18:13:52Z

# 🚀 Release Notes v1.6.0

## 🎯 Features
### Live Bracket Monitoring
- 1-minute background task automatically refreshes match scores and rosters in all active tickets
- Scoreboards use Discord's native `<t:timestamp:R>` format to show a live relative "last updated" timestamp
- Bot intelligently edits its existing embed if visible, or deletes and reposts if buried by conversation

### Staff Ticket Toolset
- `/match-info` — manually fetch and display live rosters, scores, and match status from Matcherino
- `/match-history` — displays a team's previous rounds to verify path-to-bracket accuracy
- `/set-ticket-match` — correct a ticket's match number or team name, includes 2-second rate limit safety timeout and auto-renames the channel

## ⚡ Integrations
- Matcherino data now refreshes automatically every 60 seconds across all active tickets

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.5.0...v1.6.0

---

## v1.6.1 — 2026-02-21T20:28:23Z

# 🚀 Release Notes v1.6.1

## 🎯 Features
### Fuzzy Team Name Matching
- Match embeds now compare the ticket's team name against both teams in the Matcherino bracket, allowing for minor typos
- When a mismatch is detected, the embed turns red and displays a warning with the team name entered so staff can quickly identify the issue
- When names match closely, the embed shows a `Detected Team` field with the bracket team name for easy use in `/set-ticket-match`

## ⚡ Integrations
- Fuzzy matching uses `difflib.SequenceMatcher` with a 0.60 similarity threshold, consistent with existing bracket logic

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.6.0...v1.6.1

---

## v1.6.2 — 2026-02-21T22:45:10Z

# 🚀 Release Notes v1.6.2

## 🐛 Bug Fixes & Improvements
- **Live refresher overwriting unrelated match embeds:** The 1-minute refresher now only updates the embed for the ticket's own match from the channel topic, no longer overwriting `/match-info` messages for other matches in the same channel

## 📝 Documentation
- `/tourney-admin-help` now documents all four Matcherino tools — `/set-matcherino`, `/match-info`, `/match-history`, and `/set-ticket-match`

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.6.1...v1.6.2

---

## v1.6.3 — 2026-02-24T01:01:38Z

# 🚀 Release Notes v1.6.3

## 🎯 Features
### Automated Results Scraping
- `/hall-of-fame` now scrapes live prize pool totals and tournament names directly from the Matcherino website using `beautifulsoup4`
- Captures metadata not available through standard API endpoints, ensuring Hall of Fame results match the live website exactly

## ⚡ Integrations
- Added `beautifulsoup4` to requirements for Matcherino web scraping

## 🐛 Bug Fixes & Improvements
- **Tourney Admins unable to see slash commands in ticket channels:** Resolved a permission inheritance bug preventing Tourney Admins from seeing or using slash commands in private ticket channels
- **`/set-ticket-match` unintentionally renaming channels:** Fixed a logic error that caused the channel to be renamed when only metadata updates were intended

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.6.2...v1.6.3

---

## v1.6.4 — 2026-02-28T04:38:18Z

# 🚀 Release Notes v1.6.4

## 🎯 Features
### South America Tournament Support
- `!starttourney SA` starts the tournament in SA mode, automatically locking the Spanish channel and posting a redirect message pointing users to the main support channel
- `!endtourney` now restores send permissions to the Spanish channel as a fail-safe regardless of which region was active at startup

### Automated Ticket Translation
- Bot detects non-English input in the "Issue" field during ticket creation
- If a non-English language is detected, an "English Translation" field is dynamically added to the initial ticket embed

## ⚡ Integrations
- Translation detection leverages existing `langdetect` and `deep-translator` libraries

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.6.3...v1.6.4

---

## v1.7.0 — 2026-03-05T04:07:55Z

# 🚀 Release Notes v1.7.0

## 🎯 Features
### Tournament Progress Tracking
- `/tourney-progress` displays a diagnostic report of bracket completion, dominant rounds, and lagging matches
- Smart "active" detection now identifies any match with two real teams as active, preventing matches from being hidden by obscure status names

## ⚡ Integrations
- Bracket-wide scan pulls live data from Matcherino to power the progress report

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.6.4...v1.7.0

---

## v1.7.1 — 2026-03-07T04:54:35Z

# 🚀 Release Notes v1.7.1

## 🎯 Features
### Live Progress Dashboard
- Auto-refreshing tournament panel updates every 5 minutes with a real-time overview of bracket health

### Other Changes
- Bottleneck report now displays visual match numbers aligned with the Matcherino bracket UI instead of internal API IDs
- Added sticky warning messages in key channels to redirect users toward the ticket system for tournament issues

## 🐛 Bug Fixes & Improvements
- **Tournament stuck on "Finals in progress":** Fixed completion status logic so a 100% completion rate correctly triggers a "Tournament Over" signal

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.7.0...v1.7.1

---

## v1.7.2 — 2026-03-08T17:09:54Z

# 🚀 Release Notes v1.7.2

## 🎯 Features
### Automated Milestone Announcements
- Bot now automatically detects and broadcasts Semi-Finalists, Finalists, and Winners without manual staff input

### Sticky Messaging System
- Live support redirection sticky in `#general`, `#brawl-chat`, and `#tourney-chat` — moves to the bottom after every user message to keep help requests funneled correctly
- SA tournaments automatically post Spanish translations of redirection sticky messages
- Active ticket channels feature a match info embed that repositions itself to the bottom every minute for easy access

### Other Changes
- Tournament progress panel in the admin channel auto-refreshes every 5 minutes with a persistent bracket health overview

## 🐛 Bug Fixes & Improvements
- **`!starttourney` not resetting start timestamp:** Fixed so tournament duration reporting accurately reflects the current event
- **Duplicate progress panels on startup:** Resolved a race condition between `/set-matcherino` and `!starttourney` that caused redundant panels to generate

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.7.1...v1.7.2

---

## v1.7.3 — 2026-03-11T02:53:35Z

# 🚀 Release Notes v1.7.3

## 🎯 Features
### General Support Ticket System
- `/support-panel` (Admin/Moderator only) posts a support panel where members select a category to open a private ticket
- 4 ticket categories: Report an Issue, Server Support, Staff Application, Server Partnership
- One open ticket per category per user — closed or deleted tickets don't block new ones
- `!close` / `!c` closes a ticket and posts Delete/Reopen buttons
- `!reopen` reopens a closed ticket
- `!delete` / `!del` deletes the ticket, DMs the opener a transcript, and logs it to the archive channel
- Restricted to Admin and Moderator roles, independent of tourney staff permissions

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.7.2...v1.7.3

---

## v1.7.4 — 2026-03-14T02:32:48Z

# 🚀 Release Notes v1.7.4

## 🎯 Features
### Budget System Fixes
- `/set-budget` (Admin only) allows manual adjustment of the current remaining redemption budget
- Redemption actions now correctly refund token value or reduce budget by the item's dollar value
- Users cannot redeem items if the remaining budget is too low
- Budget resets to $50 automatically at the start of each month

## 🐛 Bug Fixes & Improvements
- **Support transcript logs pinging staff unnecessarily:** Transcript logs now follow the updated format and no longer send unnecessary staff pings

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.7.3...v1.7.4

---

## v1.7.5 — 2026-03-21T15:55:59Z

# 🚀 Release Notes v1.7.5

## 🎯 Features
- `/daily` 5-message requirement now resets in sync with the 24-hour cooldown instead of at 00:00 UTC
- Messages sent in `economy-commands` and `bot-commands` no longer count toward the `/daily` message requirement
- Bot now automatically detects and reposts the active support panel on startup, preventing "Interaction Failed" errors after a restart

## 🐛 Bug Fixes & Improvements
- **Milestone messages deleting instead of updating:** Semi-final, final, and winner announcements now edit in-place when bracket teams update, ensuring there is never a gap in the updates channel

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.7.4...v1.7.5

---

## v1.8.0 — 2026-03-29T03:25:41Z

# 🚀 Release Notes v1.8.0

## 🎯 Features
### Tourney Admin Timeout Permission
- Tourney Admins are automatically granted the Timeout Members permission when `!starttourney` is run and it is revoked when `!endtourney` is run

### Auto Team Detection
- When a ticket's match number is incorrect or missing, the bot now fuzzy matches the team name against all teams in the Matcherino bracket to automatically identify the correct match

### /convert-time Command
- `/convert-time` generates all 9 Discord timestamp formats from a user-provided date, time, and timezone

## 🔒 Security & Monitoring
- `/hacked` and `!hacked` now send a DM to the flagged user informing them they have been timed out on the Remaining 7 server and how to contact staff to recover their account

## 🤖 GitHub Actions
- Added Ruff linting and formatting workflow triggering on push and PRs to `dev` and `main`
- Claude files (`.claude/`, `CLAUDE.md`) removed from repo tracking and added to `.gitignore`

## 🐛 Bug Fixes & Improvements
- **Heartbeat blocked by synchronous Matcherino API calls:** `fetch_ticket_context` and `find_match_by_team_name` now run via `run_in_executor` to prevent blocking the event loop during the 60-second match refresher task
- **Tourney winner incorrectly announced:** Fixed logic error that caused the consolation match winner to be announced as the tournament winner

## 📝 Documentation
- Updated README and all help commands to reflect current feature set
- Updated `.env` variable names to `DEV_TOKEN`, `PROD_TOKEN`, and `BOT_MODE`

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.7.5...v1.8.0

---

## v1.9.0 — 2026-04-26T19:11:32Z

# 🚀 Release Notes v1.9.0

## 🎯 Features

### AI-Powered GitHub Issue Creator
- Mentioning the bot with a description now automatically classifies it as a bug, enhancement, or feature using Gemini 2.5 Flash and creates a GitHub issue with a structured title and body
- Gated behind `TICKET_CREATOR_ID` so only the authorized user can trigger it
- A Yes/No confirmation prompt is shown before issue creation, timing out after 60 seconds
- Added Gemini and GitHub token env vars and repo config to support this flow

### Tourney ML Data Collection
- `/set-matcherino` now accepts a `collect_data` flag to opt into ML training data collection per tourney
- Per-round snapshots (timestamps, durations, match counts) are written to a new `tourney_snapshots` collection on every dashboard poll when enabled
- Collection resets to off on `!endtourney`
- `!starttourney` confirmation now reminds staff to set the Matcherino ID and configure data collection

## 🐛 Bug Fixes & Improvements
- **Post-close ticket permissions:** Non-staff users added via `/add` could still send messages after a ticket was closed — permissions now lock `send_messages` for all non-staff on close
- **Stale Matcherino ID on tourney reuse:** `!starttourney` now clears the stored Matcherino ID and resets in-memory dashboard state when reusing an existing session

## ⚡ Integrations
- `/set-matcherino` confirmation is now public so all staff can see when the tourney ID is updated

## 🎨 Embeds & UI
- SA tournament sticky messages now send a Spanish and Portuguese embed together; non-SA stickies are unchanged

## 🤖 GitHub Actions
- Added CI workflow running the full pytest suite on push
- Added pytest config and unit tests covering brawl, economy, matcherino, tickets, tourney utils, translation, general features, and the new GitHub issue creator cog

## 📝 Documentation
- Moved `BOT_VERSION` source of truth from `config.py` to `pyproject.toml`; version is now read dynamically via `tomllib`
- Added Makefile with `make test`, `make lint`, `make fix`, `make ci`, and `make up` for local dev convenience
- Pinned minimum versions on all dependencies in `requirements.txt`

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.8.0…v1.9.0

---

## v1.9.1 — 2026-05-21T07:39:19Z

# 🚀 Release Notes v1.9.1
                                                                                                                                  
  ## 🎨 Embeds & UI
  - `/hacked-list` is now paginated with navigation buttons for a cleaner layout                                                                                           
                                                                                                                                                                           
  ## 🔒 Security & Monitoring                                                                                                                                              
  - `/hacked` message purge window updated to 12 hours, preserving older message history while still covering the compromise window                                        
                                                                                                                                                                         
  ## 🐛 Bug Fixes & Improvements
  - **`!hacked` triggering on trailing text:** Fixed command matching to require exact `!hacked` with no trailing content
  - **Token Economy:** Messages in BOTS category channels no longer award tokens, preventing earn from bot spam                                                            
  - **Token Economy:** Server booster bonus token chance increased from 2% to 5%
  - **Tourney:** Admin role is automatically renamed on tourney start and restored on end, with confirmation messages                                                      
  - **Tourney:** 60s slow mode applied to general on tourney start/end, with confirmation messages                                                                       
  - **Redeem Tickets:** Embed now shows item price and balance before/after redemption                                                                                     
                                                                                                                                                                         
  **Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.9.0…v1.9.1

---

## v1.9.2 — 2026-05-29T12:04:35Z

# 🚀 Release Notes v1.9.2                                                                                                                                                 
                                                                                                                                                                            
## 🐛 Bug Fixes                                                                                                                                                           
- Fixed passive token and XP rewards being earned in bot command channels — messages in `#bot-commands` and `#economy-commands` no longer grant tokens, XP, or daily message count                                                                                                                                                             
                                                                                                                                                                            
## 🔧 Maintenance                                                                                                                                                         
- Renamed `DAILY_MSG_EXCLUDED_CHANNEL_IDS` to `PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS` to reflect its broader usage                                                        
                                                                                                                                                                            
**Full Changelog:** https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.9.1...v1.9.2   

---

## v1.10.0 — 2026-06-21T02:30:48Z

# 🚀 Release Notes v1.10.0

## 🎯 Features
- **Megabox Quest Type** — Every user now has 4 active quests: daily & weekly message quests plus dedicated daily & weekly Megabox quests. Opening a Mega Box or Starr Drop counts toward progress. (#200)
- **Monthly Tournament Reports** — Auto-generated monthly reports posted to a dedicated archive channel. Matcherino ID is now auto-detected on `!starttourney`. (#312)
- **`/active-matches`** — New command displaying all active match scores grouped by round (#309)
- **`/poll-rewards`** — Distribute tokens to all users who voted on a poll message (#294)
- **Sticky Messages** — `!sticky` / `!unsticky` prefix commands for persistent channel messages with debounced repost (#297)
- **Counting Game** — Sequential counting channel with wrong-number detection and `/set-count` staff override (#220)
- **`/version`** — Slash command to view the bot's current version (#277)
- **Redemption Transcripts** — Transcripts now generated on redemption ticket close (#201)

## ⚙️ Enhancements
- **Quest Rewards Rebalanced** — Token and XP rewards now better incentivize harder quests across all 6 message quest tiers (#184)
- **Slow Mode Auto-Disable** — `!starttourney` enables 60s slow mode in general with a public notice; automatically removed after 1 hour (or immediately on `!endtourney`). (#317)
- **Cleanup Warning Replacement** — Daily event cleanup alerts now replace the previous day's warning instead of stacking (#318)
- **Passive Earning Restricted to General** — Token earning, XP, quest progress, and daily message tracking now only apply in general chat (#301)
- **Booster Bonus** — Server Booster token bonus increased from 2% to 5% (#269)
- **Translation Transcripts** — Auto-translated messages in tourney tickets are now captured in transcripts (#199)
- **Hacked Embed Improvements** — Moderator identity and response time duration added to hacked user flag embed (#251, #265)
- **`/check-budget`** — Now shows the next budget reset date (#285)
- **Tourney Channel Restriction** — `!starttourney` and `!endtourney` restricted to the tourney admin channel (#278)
- **Active Matches Cap Removed** — Removed the 5-match display limit in bracket dashboards (#316)
- **Unit Tests** — Added 15 tests covering `TIMEZONE_ALIASES` and `/convert-time` command (#326)
- **Docs** — README and all help commands updated (#325)

## 🐛 Bug Fixes
- Fixed TBD slot display showing incorrect source match scores and teams (#198)
- Fixed bracket progress showing wrong round numbers (#202)
- Fixed redeem ticket not pinging the redeeming user (#296)
- Fixed floating-point display in redemption ticket balance fields (#299)
- Fixed Gemini API failure crashing GitHub issue creation confirm button (#300)
- Fixed commands failing for users who have left the server (#298)
- Fixed passive token and XP being earned in bot command channels (#280)
- Fixed quest progress counting in restricted channels (#279)

## 📊 Full Changelog
https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.9.2...v1.10.0

---

## v1.11.0 — 2026-07-18T10:23:48Z

# 🚀 Release Notes v1.11.0

## 🎯 Features

### Server Booster Perks
- Boosters now get a ~10% average bonus on both passive tokens and XP per message
- A flat +20 token bonus was added to every `/daily` claim for boosters
- Added an exclusive booster-only channel with its own periodic token supply drops
- Added a monthly 10% shop discount for boosters, gated behind 14 consecutive days of boosting
- Boosters now get quest thresholds cut by 20%
- Boosting for the first time now auto-opens a private ticket where the booster can submit a shoutout message for staff to feature
- Added `/booster-perks` to summarize all of the above in one place

### Other Changes
- Tourney ticket modals now support optional image uploads (up to 3 files)
- Moderators can repost any message by pasting its Discord link — the bot mirrors it via webhook using the original author's name and avatar

## 🔒 Security & Monitoring
- Added a scam image detection system that scans attachments against a blacklist (MD5, pHash, and ORB matching), auto-purges duplicates, and applies a precautionary timeout with mod alert buttons

## 🐛 Bug Fixes & Improvements
- **XP was being earned in every channel:** XP earning is now restricted to the general and booster channels, matching how token earning already worked
- **Redemption budget could be oversold:** pending (not yet fulfilled) tickets are now counted against the monthly budget, and requests that don't fit are queued for the next month instead of failing outright
- **Token shop prices increased ~18%:** all shop items are now priced at a flat 2,000 tokens per dollar
- Removed "Tourney Admin" as a selectable role in staff applications
- Removed the manual `!lock`/`!unlock` commands now that ticket locking is handled automatically

## 📝 Documentation
- Added a `docs/` folder with implementation guides for every major bot feature
- Updated README and shop docs to match the v1.11.0 feature set and fixed several stale figures/examples

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.10.0...v1.11.0

---
