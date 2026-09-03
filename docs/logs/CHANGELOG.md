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


### PR Descriptions

#### PR #1 — Updated README (merged 2025-12-18)

*(no description)*

#### PR #4 — Fixed 3-Bug (merged 2025-12-20)

Resolves #3

#### PR #5 — Added tourney payout commands (merged 2025-12-20)

*(no description)*

#### PR #6 — Updated README (merged 2025-12-20)

*(no description)*

#### PR #8 — Fixed 7-Bug (Discord 50 channels one category rate limit) (merged 2025-12-21)

Resolved #7

#### PR #9 — Updated README (merged 2025-12-21)

*(no description)*

#### PR #10 — Updated leaderboard view and remove ping when closing tourney tickets (merged 2025-12-21)

*(no description)*

#### PR #11 — Added !delete and !reopen commands & changed /hall-of-fame success message to be visible to all (merged 2025-12-22)

Added !delete and !reopen commands in case buttons fail & changed /hall-of-fame success message to be visible to all

#### PR #12 — Added live tournament queue stats and /queue command, also fixed /level_leaderboard (merged 2025-12-22)

*(no description)*

#### PR #13 — Small fix to remove irrelevant footer (merged 2025-12-22)

*(no description)*

#### PR #14 — Added tourney blacklist commands (merged 2025-12-23)

*(no description)*

#### PR #17 — Supply drops can no longer claimed by moderators (merged 2025-12-23)

*(no description)*

#### PR #18 — Revamped Level Leaderboard view (merged 2025-12-25)

*(no description)*

#### PR #19 — Added master switch to the env (merged 2025-12-26)

*(no description)*

#### PR #20 — Added basic brawl collectible system (merged 2025-12-27)

*(no description)*

#### PR #21 — Updated real ids for brawler emojis (merged 2025-12-27)

*(no description)*

#### PR #22 — Updated emoji ids and added brawler leveling (merged 2025-12-28)

*(no description)*

#### PR #23 — Updated README to include all the info on the new Brawl Stars Collection System (merged 2025-12-28)

*(no description)*

#### PR #24 — Removed debug command, added fair content policy disclaimer (merged 2025-12-28)

*(no description)*

#### PR #25 — Added gadgets and starpowers (merged 2025-12-29)

*(no description)*

#### PR #26 — Added hypercharges (merged 2025-12-30)

*(no description)*

#### PR #27 — Some fixes and QOL changes (merged 2026-01-03)

*(no description)*

#### PR #28 — Added buying gadgets, starpowers, hypercharges (merged 2026-01-04)

*(no description)*

#### PR #30 — Updated Brawl Pass prices to reflect in game changes (merged 2026-01-14)

*(no description)*

#### PR #31 — Fixed 29-Bug (Hacked Log in Transcript Channel) (merged 2026-01-18)

Resolved #29

#### PR #32 — Fixed 2-Bug (Chat activity is no longer generating token rewards) (merged 2026-01-18)

Resolved #2

#### PR #33 — Updated README and imports (merged 2026-01-18)

*(no description)*

#### PR #34 — Fixed 15-Bug (Quests got removed) (merged 2026-01-18)

Resolved #15

#### PR #36 — 35-Bug Make supply drops have no timeout (merged 2026-01-24)

Resolves #35

#### PR #38 — 37-Feature Add tourney stats for when tourneys end (merged 2026-01-31)

Closes #37

---

## v1.0.1 — 2026-01-31T22:40:19Z

# 🚀 Release Notes v1.0.1

## 🐛 Bug Fixes & Improvements
- **`!endtourney` stats panel not deleting:** `!endtourney` now reliably deletes the live stats panel on tourney end.

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.0.0...v1.0.1


### PR Descriptions

#### PR #40 — 39-Bug Fix !endtourney not deleting live tourney stats message (merged 2026-01-31)

Close #39

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


### PR Descriptions

#### PR #42 — 41-Feature Mention match number and team name in transcript message (merged 2026-02-01)

Now shows: 
<img width="966" height="499" alt="Screenshot 2026-01-31 at 7 08 56 PM" src="https://github.com/user-attachments/assets/d7aa6cec-93a7-47f5-86b6-16aef9fe38e6" />

Close #41

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


### PR Descriptions

#### PR #44 — 43-Feature Add COC Gold Pass and CR Diamond Pass with pagination view (merged 2026-02-01)

Shop now has pagination view and has new items:
<img width="413" height="427" alt="Screenshot 2026-01-31 at 11 43 14 PM" src="https://github.com/user-attachments/assets/accc9187-eb60-44df-b888-fe66afd52dfe" />
<img width="367" height="361" alt="Screenshot 2026-01-31 at 11 42 55 PM" src="https://github.com/user-attachments/assets/4b5933ef-54df-4017-92cc-dfae08e795bf" />

Close #43

---

## v1.1.1 — 2026-02-08T05:55:42Z

# 🚀 Release Notes v1.1.1

## 🎯 Features
### Economy Cooldown Reduction
- Token earn cooldown reduced from **60 seconds** to **20 seconds**
- Active chatters can now earn tokens up to 3x faster than before

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.0...v1.1.1


### PR Descriptions

#### PR #51 — 46-Enhancement reduce chat token cooldown from 60s to 20s (merged 2026-02-08)

Closes #46

---

## v1.1.2 — 2026-02-08T06:40:22Z

# 🚀 Release Notes v1.1.2

## 🎯 Features
### Staff Shop Restrictions
- `/buy` and `/redeem` are now disabled for Trial Moderators, Moderators, and Admins
- Ensures limited shop rewards remain exclusively available to community members

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.1...v1.1.2


### PR Descriptions

#### PR #52 — 48-Enhancement restrict staff from buying and redeeming shop items (merged 2026-02-08)

Closes #48

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


### PR Descriptions

#### PR #53 — 49-Enhancement add Glowbert and paginate brawler shop (merged 2026-02-10)

Closes #49

---

## v1.1.4 — 2026-02-14T02:51:50Z

# 🚀 Release Notes v1.1.4

## 🔒 Security & Monitoring
- `/payout-add` and `/payout-reset` are now restricted to Server Admins only
- Tourney Admins retain read-only access via `/payout-list` and `/payout-history`

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.3...v1.1.4


### PR Descriptions

#### PR #59 — 58-Bug fix bug where tourney admins can update payouts (merged 2026-02-14)

Closes #58

---

## v1.1.5 — 2026-02-14T03:37:59Z

# 🚀 Release Notes v1.1.5

## 🐛 Bug Fixes & Improvements
- **Token balance displaying as decimals:** `/balance`, `/buy`, `/daily`, and the token leaderboard now correctly display token amounts as whole numbers instead of long floating-point decimals

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.4...v1.1.5


### PR Descriptions

#### PR #60 — 54-Bug fix decimal display bug in token balances (merged 2026-02-14)

Closes #54

---

## v1.1.6 — 2026-02-14T04:21:49Z

# 🚀 Release Notes v1.1.6

## 📊 Data Model
- Corrected brawler names, gadgets, star powers, and hypercharges in the brawler JSON to match 2026 game data
- Aligned all internal IDs and stats with the latest Brawl Stars data

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.1.5...v1.1.6


### PR Descriptions

#### PR #61 — 50-Bug fix brawler in json (merged 2026-02-14)

Closes #50

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


### PR Descriptions

#### PR #62 — Add bidirectional translation to and from English (merged 2026-02-14)

Closes #47

---

## v1.2.1 — 2026-02-14T18:21:43Z

# 🚀 Release Notes v1.2.1

## 🎯 Features
### Manual Source Language Override
- `!t <language>` now accepts an optional language name to bypass auto-detection (e.g. `!t hindi`)
- Eliminates guesswork on short phrases or slang for more reliable translations into English

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.2.0...v1.2.1


### PR Descriptions

#### PR #64 — 63-Enhancement add manual source language override to !translate (merged 2026-02-14)

Closes #63

---

## v1.2.2 — 2026-02-14T19:01:07Z

# 🚀 Release Notes v1.2.2

## 🎯 Features
### Daily Chat Milestone Requirement
- `/daily` rewards now require at least 5 messages sent within the current day (UTC) to unlock
- If locked, the bot displays a combined status embed showing message progress and cooldown timer together

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.2.1...v1.2.2


### PR Descriptions

#### PR #65 — 45-Enhancement add 5 message requirement for /daily command (merged 2026-02-14)

Release v1.2.2

Closes #45

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


### PR Descriptions

#### PR #70 — 55-Feature add economy help command (merged 2026-02-15)

Closes #55

#### PR #71 — 56-Feature add general help command listing all bot commands (merged 2026-02-15)

Closes #56

#### PR #72 — 57-Feature add tourney admin help command (merged 2026-02-15)

Closes #57

#### PR #74 — 73-Feature add even staff help command (merged 2026-02-15)

Closes #73

#### PR #76 — 75-Feature add mod help command (merged 2026-02-15)

Closes #75

#### PR #78 — 77-Feature add admin help command (merged 2026-02-15)

Closes #77

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


### PR Descriptions

#### PR #79 — 68-Bug fix on_message listener registering twice (merged 2026-02-15)

Closes #68

#### PR #80 — 69-Feature integrate Matcherino bracket scraping (merged 2026-02-16)

Part of #66 
Closes #69 

When creating a tourney ticket, you will see something like this:
<img width="387" height="204" alt="Screenshot 2026-02-15 at 10 27 39 PM" src="https://github.com/user-attachments/assets/ecb37f32-ae9f-4823-b6da-aa711e52fa48" />

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


### PR Descriptions

#### PR #85 — 84-Feature add test tourney mode toggle (merged 2026-02-16)

Closes #84

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


### PR Descriptions

#### PR #86 — 82-Feature add match_info command (merged 2026-02-21)

Part of #66 
Closes #82

#### PR #87 — 81-Feature add match-history command (merged 2026-02-21)

Part of #66 
Closes #81

#### PR #88 — 83-Feature add 1m match refresher for match info and set-ticket-match command (merged 2026-02-21)

Part of #66 
Closes #83 

While the sub-issue focused on the core 5-minute refresher, the following improvements were added for better staff control and UI:
- **Increased Frequency**: The refresher loop was updated from 5 minutes to 1 minute to provide near-instant score updates.
- **Live Relative Timestamps**: Switched to Discord’s native relative time formatting. Embeds now dynamically show time elapsed (e.g., "3 minutes ago") instead of a static clock.
- **New Management Command**: Added /set-ticket-match to allow staff to correct match numbers or team names on the fly. This ensures the refresher task picks up corrected data without requiring a new ticket.

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


### PR Descriptions

#### PR #90 — 89-Enhancement add fuzzy team match (merged 2026-02-21)

Part of #66 
Closes #89

---

## v1.6.2 — 2026-02-21T22:45:10Z

# 🚀 Release Notes v1.6.2

## 🐛 Bug Fixes & Improvements
- **Live refresher overwriting unrelated match embeds:** The 1-minute refresher now only updates the embed for the ticket's own match from the channel topic, no longer overwriting `/match-info` messages for other matches in the same channel

## 📝 Documentation
- `/tourney-admin-help` now documents all four Matcherino tools — `/set-matcherino`, `/match-info`, `/match-history`, and `/set-ticket-match`

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.6.1...v1.6.2


### PR Descriptions

#### PR #92 — 91-Bug fix refresher overwriting /match-info match embeds (merged 2026-02-21)

Closes #91 

### Screenshots
<img width="649" height="774" alt="Screenshot 2026-02-21 at 5 21 42 PM" src="https://github.com/user-attachments/assets/b274faed-f4e5-455f-b69a-46e602f2ecd3" />

<img width="610" height="790" alt="Screenshot 2026-02-21 at 5 28 02 PM" src="https://github.com/user-attachments/assets/699f2dbf-b376-4d42-be08-31fdbabdd724" />

#### PR #94 — 93-Enhancement bump up version number and add new commands to /tourney-admin-help (merged 2026-02-21)

Closes #93

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


### PR Descriptions

#### PR #96 — 95-Bug fix tourney admins not being able to use commands in ticket channels (merged 2026-02-22)

Closes #95

#### PR #98 — 97-Bug fix set-ticket-match command from changing channel name (merged 2026-02-23)

Closes #97

#### PR #100 — 99-Enhancement update hall-of-fame command to pull directly from the website (merged 2026-02-23)

Part of #66 
Closes #99

#### PR #102 — 101-Enhancement bumping up version number to v1.6.3 and updating hall-of-fame description (merged 2026-02-24)

Closes #101

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


### PR Descriptions

#### PR #104 — 103-Enhancement add auto translation for tourney ticket issues (merged 2026-02-28)

Closes #103

### Screenshots
<img width="339" height="414" alt="image" src="https://github.com/user-attachments/assets/cb22aa0d-30f7-4e25-900d-67844fe32096" />

<img width="538" height="356" alt="Screenshot 2026-02-27 at 9 46 31 PM" src="https://github.com/user-attachments/assets/54be2e51-bab2-4388-b34f-1f3e5b4dd403" />

#### PR #106 — 105-Enhancement add redirect for espanol channel for SA tourneys (merged 2026-02-28)

Closes #105

#### PR #108 — 107-Enhancement bump up version to v1.6.4 (merged 2026-02-28)

Closes #107

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


### PR Descriptions

#### PR #110 — 109-Feature add tourney progress report command  (merged 2026-03-05)

Part of #66
Closes #109 

New command: `/tourney-progress`

### Screenshots
<img width="474" height="281" alt="Screenshot 2026-03-04 at 10 42 37 PM" src="https://github.com/user-attachments/assets/1cda8b8f-458d-45ad-8cb2-2cbd37db5d5f" />

#### PR #112 — 111-Enhancement bump version to v1.7.0 (merged 2026-03-05)

Closes #111

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


### PR Descriptions

#### PR #118 — 113-Bug fix bottleneck matches to contain the correct match number (merged 2026-03-07)

Actual Bracket:
<img width="285" height="137" alt="image" src="https://github.com/user-attachments/assets/b7078760-55fa-4744-adb0-f53a3c5fd52e" />
Tourney: https://matcherino.com/supercell/tournaments/184533/bracket/bracket

Before:
<img width="470" height="293" alt="Screenshot 2026-03-06 at 10 17 15 PM" src="https://github.com/user-attachments/assets/68b8e02a-2b9e-4d75-a40d-3f2140079c84" />

After:
<img width="485" height="280" alt="Screenshot 2026-03-06 at 10 17 29 PM" src="https://github.com/user-attachments/assets/2116ecd2-23f3-47a1-b740-2d5a22c5aa0c" />



Closes #113

#### PR #119 — 115-Bug fix finished tourneys showing in progress (merged 2026-03-07)

Before:
<img width="471" height="295" alt="Screenshot 2026-03-06 at 10 31 29 PM" src="https://github.com/user-attachments/assets/116241f3-bea7-4400-bb15-9ff0ee8f2290" />

After:
<img width="481" height="286" alt="Screenshot 2026-03-06 at 10 30 30 PM" src="https://github.com/user-attachments/assets/202737d4-4d24-47c4-aebe-f4ca2e5c1a85" />

Closes #115

#### PR #120 — 116-Enhancement add 5 min panel tourney panel refresh (merged 2026-03-07)

Part of #66 
Closes #116

#### PR #121 — 117-Feature add sticky messages for tourney redirection in a few channels (merged 2026-03-07)

Closes #117

#### PR #123 — 122-Enhancement bump up version to v1.7.1 (merged 2026-03-07)

Closes #122

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


### PR Descriptions

#### PR #125 — 124-Enhancement add automated detection of semi-final teams, final teams, and winner and add automated annoucements (merged 2026-03-08)

Closes #124

#### PR #127 — 126-Bug !starttourney resets total tourney time (merged 2026-03-08)

Closes #126

#### PR #129 — 128-Bug fix duplicate tourney progress dashboard (merged 2026-03-08)

Closes #128


<img width="738" height="534" alt="Screenshot 2026-03-07 at 9 57 47 PM" src="https://github.com/user-attachments/assets/1922595c-8b43-4ce2-a71b-75971a0bf5fd" />

#### PR #131 — 130-Enhancement add sticky support redirection for SA tourneys (merged 2026-03-08)

Closes #130

#### PR #133 — 132-Enhancement match info embed now moves to the bottom of ticket channel everytime (merged 2026-03-08)

Part of #66 
Closes #132

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


### PR Descriptions

#### PR #135 — 134-Enhancement revamp support ticket system (merged 2026-03-11)

Closes #134

<img width="647" height="404" alt="image" src="https://github.com/user-attachments/assets/055415df-c90d-4593-8f10-836e7b69d317" />

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


### PR Descriptions

#### PR #137 — 136-Bug update transcript message (merged 2026-03-12)

Now displayes:
<img width="747" height="230" alt="image" src="https://github.com/user-attachments/assets/8bc4601a-c879-40d6-8af0-ed972b6edfdf" />

Closes #136

#### PR #138 — 16-Bug fix budget with revamped ticket system (merged 2026-03-12)

- Added a monthly budget system with automatic month rollover: budget resets to $50.00, spent resets to 0, and budget tracking keys refresh when a new UTC month is detected.
- Updated `/set-budget` to set the current remaining budget (not the monthly cap) by recalculating spent amount behind the scenes.
- Added redemption close actions that now correctly affect budget/refunds: Give back tokens and delete refunds token value, while Reduce from budget and delete deducts the item’s USD cost from budget.
- Added a `/redeem` budget guard so users cannot open redemption tickets if the item cost exceeds remaining monthly budget.

Closes #16

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


### PR Descriptions

#### PR #140 — 139-Feature add CLAUDE.md file (merged 2026-03-14)

Closes #139

#### PR #153 — v1.7.5 (merged 2026-03-21)

### Changes
* Fixed automated tournament milestone messages (semi-final, final, winner) not persisting — messages now edit in-place when bracket teams update instead of being deleted
* Aligned the `/daily` 5-message requirement reset with the 24-hour cooldown timer instead of resetting at 00:00 UTC
* Excluded `economy-commands` and `bot-commands` channels from counting toward the `/daily` message requirement
* Bot now auto-detects and reposts the active support panel on startup to prevent "Interaction Failed" after a restart

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


### PR Descriptions

#### PR #179 — v1.8.0 (merged 2026-03-29)

### Changes
* Fixed bug where previous tourney milestone updates were not sent if they hadn't already posted
* Fixed bug where consolation match winner was incorrectly announced as tournament winner
* Removed Claude files from repo tracking and added `.claude/`, `CLAUDE.md` to `.gitignore`
* Added Ruff linting and formatting workflow, reformatted all files to pass checks
* Updated README and `.env` variable names (`DEV_TOKEN`, `PROD_TOKEN`, `BOT_MODE`)
* Added feature to dynamically grant and revoke Timeout Members permission for Tourney Admins on `!starttourney` / `!endtourney`
* Added `/convert-time` command to generate all Discord timestamp formats from a given date, time, and timezone
* Added DM to user when flagged via `/hacked` or `!hacked`
* Added auto team detection via fuzzy matching when match number is missing or incorrect
* Updated README and all help commands to reflect current feature set

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


### PR Descriptions

#### PR #236 — v1.9.0 (merged 2026-04-26)

### Changes
* Fixed post-close ticket permissions to lock `send_messages` for all non-staff users, not just the opener — covers users added via `/add`
* Added Portuguese translation embed to SA tournament sticky messages; SA tourneys now send Spanish + Portuguese embeds together
* Added test suite with unit tests across brawl, economy, matcherino, tickets, tourney utils, translation, and general features; added CI workflow and pytest config; pinned minimum dependency versions
* Added Makefile with `make test`, `make lint`, `make fix`, `make ci`, and `make up` commands for local dev convenience
* Moved `BOT_VERSION` source of truth from `config.py` to `pyproject.toml`; `config.py` now reads version dynamically via `tomllib`
* Fixed stale Matcherino ID persisting across reused tourney sessions — clears DB ID and resets in-memory dashboard state on `!starttourney`; added `/set-matcherino` reminder to confirmation message
* Added ML training data collection to the tourney system — `/set-matcherino` now accepts a `collect_data` flag; snapshots with per-round timestamps, durations, and match counts are written to `tourney_snapshots` on every dashboard poll when enabled; resets on `!endtourney`
* Made `/set-matcherino` confirmation response public so all staff can see when the tourney ID is updated
* Added AI-powered GitHub issue creator via bot @mention:
  * Added Gemini and GitHub token env vars and repo config
  * Added GitHub tickets cog listening for bot @mentions and extracting raw text
  * Integrated Gemini 2.5 Flash to classify descriptions as bug/enhancement/feature and return structured title + body
  * Added `create_github_issue()` wired to Gemini output, replying with the created issue link
  * Gated issue creation behind `TICKET_CREATOR_ID` and a Yes/No confirmation prompt with 60s timeout
  * Added pytest coverage for `call_gemini`, `create_github_issue`, and the `on_message` listener

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


### PR Descriptions

#### PR #276 — v1.9.1 (merged 2026-05-21)

### Changes                                                                                                                                                              
  * Fixed `!hacked` triggering on messages with trailing text after the command                                                                                            
  * Updated `/hacked` message purge window to 12 hours instead of 7 days                                                                                                   
  * Updated `/hacked-list` to paginate with navigation buttons                                                                                                             
  * Updated token rewards to skip messages sent in BOTS category channels                                                                                                  
  * Updated server booster bonus token chance from 2% to 5%                                                                                                                
  * Added admin role rename on tourney start with automatic restore on end                                                                                                 
  * Added 60s slow mode to general channel on tourney start/end with confirmation messages                                                                                 
  * Updated redeem ticket embed to include item price and balance before/after redemption

---

## v1.9.2 — 2026-05-29T12:04:35Z

# 🚀 Release Notes v1.9.2                                                                                                                                                 
                                                                                                                                                                            
## 🐛 Bug Fixes                                                                                                                                                           
- Fixed passive token and XP rewards being earned in bot command channels — messages in `#bot-commands` and `#economy-commands` no longer grant tokens, XP, or daily message count                                                                                                                                                             
                                                                                                                                                                            
## 🔧 Maintenance                                                                                                                                                         
- Renamed `DAILY_MSG_EXCLUDED_CHANNEL_IDS` to `PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS` to reflect its broader usage                                                        
                                                                                                                                                                            
**Full Changelog:** https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.9.1...v1.9.2   


### PR Descriptions

#### PR #284 — v1.9.2 (merged 2026-05-29)

### Changes                                                                                                                                                             
  * Fixed passive token and XP rewards being earned in bot command channels (`BOT_COMMANDS_CHANNEL_ID`, `ECONOMY_COMMANDS_CHANNEL_ID`) by adding an early return in the `on_message` handler

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


### PR Descriptions

#### PR #329 — v1.10.0 (merged 2026-06-21)

### Changes
  - Added megabox quest type with dedicated daily and weekly slots; opening a Mega Box or Starr Drop counts toward progress
  - Added monthly tournament reports with auto Matcherino ID detection on `!starttourney`
  - Added `/active-matches` command to display active match scores grouped by round
  - Added `/poll-rewards` command to distribute tokens to poll voters
  - Added sticky messages feature (`!sticky` / `!unsticky`) with debounced repost
  - Added counting game with sequential validation and `/set-count` staff command
  - Added `/version` slash command
  - Added transcript generation to redemption ticket close flow
  - Added `/reset-quests` admin command to force-reset a user's quest assignments
  - Updated quest rewards to better incentivize harder quests across all tiers
  - Updated `!starttourney` to enable slow mode with a 1-hour auto-disable and public general chat notice
  - Updated event cleanup alerts to replace the previous day's warning instead of stacking
  - Updated passive token earning, XP, quest progress, and daily tracking to general chat only
  - Updated server booster token bonus from 2% to 5%
  - Updated hacked embed to include moderator identity and response time duration
  - Updated `/check-budget` to show next budget reset date
  - Updated README and all help commands
  - Added 15 unit tests covering `TIMEZONE_ALIASES` and `/convert-time`
  - Fixed TBD slot display with incorrect source match scores and teams
  - Fixed bracket progress showing wrong round numbers
  - Fixed redeem ticket not pinging the redeeming user
  - Fixed floating-point display in redemption ticket balance fields
  - Fixed Gemini API failure in GitHub issue creation confirm button
  - Fixed commands failing for users who have left the server
  - Fixed passive token and XP being earned in bot command channels
  - Fixed quest progress counting in restricted channels

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


### PR Descriptions

#### PR #372 — v1.11.0 (merged 2026-07-18)

### Changes
  * Added ~10% average booster bonus to both passive tokens and XP per message
  * Added a flat +20 token bonus to `/daily` for boosters
  * Added an exclusive booster-only channel with periodic token supply drops
  * Added a monthly 10% shop discount for boosters, gated behind 14 consecutive days of boosting
  * Added a 20% quest threshold reduction for boosters
  * Added auto-opened booster shoutout tickets on first boost
  * Added `/booster-perks` command summarizing all booster perks
  * Added optional image uploads (up to 3 files) to tourney ticket modals
  * Added a moderator message mirror — reposts any message via webhook by pasting its Discord link
  * Added a scam image detection system (MD5/pHash/ORB matching) with auto-purge and mod alert buttons
  * Fixed XP being earned in every channel — now restricted to general and booster channels like tokens
  * Fixed redemption budget to count pending tickets and queue overflow requests to next month
  * Token shop prices increased by ~18% (now 2,000 tokens per dollar)
  * Removed "Tourney Admin" as a selectable staff application role
  * Removed the manual `!lock`/`!unlock` commands now that ticket locking is automatic
  * Added a `docs/` folder with implementation guides for every major feature
  * Updated README and shop docs to match the v1.11.0 feature set and fixed stale figures/examples

---

## v1.11.1 — 2026-07-20

# 🚀 Release Notes v1.11.1

## 🐛 Bug Fixes & Improvements
- `!endtourney` now automatically posts the Hall of Fame for the tournament that just ended, using the session's Matcherino ID
- Fixed booster supply drops occasionally stacking up — old unclaimed drops now expire properly, so only one drop is ever active in the booster channel at a time

## 📝 Documentation
- Added persistent development history under `docs/logs/` — `SPECS.md` (chronological as-implemented spec record) and `CHANGELOG.md` (release notes + PR descriptions), so history survives outside of GitHub

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.11.0...v1.11.1


### PR Descriptions

#### PR #386 — 382-Enhancement update documentation for v1.11.1 release (merged 2026-07-20)

### Changes
* Added the `v1.11.1` section to `docs/logs/SPECS.md`, documenting every issue in the release (#373, #374, #377, #379, #381, #382)
* Added the `v1.11.1` release notes and these PR descriptions to `docs/logs/CHANGELOG.md`
* Updated the booster supply-drop expiry behavior in `docs/TOKEN_SYSTEM.md` for the #377 fix
* Bumped the version string in `README.md` to v1.11.1

Closes #382

#### PR #384 — v1.11.1 (merged 2026-07-20)

### Changes
* Added automatic Hall of Fame posting to `!endtourney` using the ended tournament's Matcherino ID
* Fixed booster supply drops occasionally stacking up — unclaimed drops now expire reliably so only one is ever active in the booster channel
* Added persistent development history under `docs/logs/` (`SPECS.md` and `CHANGELOG.md`)
* Bumped version to v1.11.1

---

## v1.12.0 — 2026-08-14

# 🚀 Release Notes v1.12.0

## 🎯 Features & Enhancements
- Tourney state now auto-resumes after a bot restart — dashboards, slowmode/lock timers, region + admin-role, and the ticket counter are rehydrated on boot, and `!starttourney` guards against clobbering an active session unless `force` is passed
- Event Staff can now use the `!sticky` and `!unsticky` commands
- Migrated hosting from Pella to RamNaym Cloud after repeated Pella outages; added `docs/HOSTING.md` documenting the migration history, plan specs, and reasoning
- Added a `make commit m="..."` shortcut that runs `git add`/`commit`/`push` in one step (dev tooling)
- Pinned the Ruff ruleset and CI Ruff version so `ruff check` is deterministic across Ruff releases (dev tooling)

## 🐛 Bug Fixes & Improvements
This release is anchored by a crash-safety epic hardening every flow that moves tokens, items, or currency against a mid-operation crash or forced restart:
- **`/redeem`** no longer permanently loses an item if the bot crashes between removing the token and creating the ticket — a pending record is reconciled on startup to either complete the ticket or refund the item, never both and never neither
- **`/buy` and Brawl ability/brawler purchases** no longer deduct currency without granting the item — deduct and grant are now a single atomic operation
- **Quest rewards** are no longer lost if the bot crashes right after a quest is flagged complete — completion and payout are tracked separately so an unpaid quest is retried instead of stuck done
- **`/event-rewards`, `/poll-rewards`, and `/payout-add`** no longer double-pay recipients on a crash-and-retry — all three now share a per-recipient ledger that claims each recipient before paying
- **The redemption queue** no longer wrongly refunds active members on a cold member cache (now confirmed via `fetch_member`), no longer double-creates tickets or double-spends budget on retry, and no longer silently loses queued items or refunds in its remove / member-left paths
- **Scam-image purges** now resume from where they left off after a crash instead of leaving copies live in un-visited channels
- **Redemption ticket close and `/daily`** no longer double-refund, double-charge budget, or allow a second claim if a crash lands mid-flow
- **Supply / booster / admin drops** stay claimable after a restart, `!endtourney`'s winner announcement survives a restart during its retry wait, per-message token rewards use an atomic write, and scheduled loop jobs catch up (or log clearly) when a run is missed to downtime
- Fixed a contradictory tournament slow-mode message that stated both "for the tournament" and "removed after 1 hour"

## 📝 Documentation
- Added the `v1.12.0` section to `docs/logs/SPECS.md` (every issue in the release) and `docs/logs/CHANGELOG.md` (release notes + PR descriptions)
- Added `docs/HOSTING.md` capturing the Pella → RamNaym Cloud migration history
- Feature docs (`DATABASE`, `ECONOMY_SHOP`, `QUEST_SYSTEM`, `SCAM_DETECTION`, `TOKEN_SYSTEM`, `BRAWL_*`, `TOURNEY_OVERVIEW`, `STICKY_MESSAGES`, `BOOSTER_SHOUTOUT`) were updated alongside their respective fixes

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.11.1...v1.12.0


### PR Descriptions

#### PR #436 — 436-Enhancement update documentation for v1.12.0 release (pending)

### Changes
* Added the `v1.12.0` section to `docs/logs/SPECS.md`, documenting every issue in the release (#390, #391, #395, #398, #404, #410–#419, #423, #432, #433, #434, #435, #436)
* Added the `v1.12.0` release notes and these PR descriptions to `docs/logs/CHANGELOG.md`

Closes #436

#### PR #440 — 435-Enhancement update version to v1.12.0 (pending)

### Changes
* Updated `pyproject.toml` version from `1.11.1` to `1.12.0` for the upcoming release
* Updated `README.md` version banner to `v1.12.0` to match

Closes #435

---

## v1.13.0 — 2026-08-30

# 🚀 Release Notes v1.13.0

## 🎯 Features & Enhancements
- Added a privacy policy system: the `/privacy-policy` command, a repo-level `PRIVACY_POLICY.md`, and a dedicated privacy channel that is wiped and reposted on every restart — the policy text lives in exactly one place and renders to all three surfaces
- The level leaderboard shipped: `/leaderboard` is now a command group with `token` and `level` subcommands, the level board mirroring the token board's format
- Added a collaborative one-word story game with configurable banned-word and banned-character lists
- The counting channel now accepts math expressions (e.g. `7*10` counts as `70`), evaluated through a safe `ast`-based parser that rejects anything that isn't plain arithmetic
- Renamed the `ALLOWED_STAFF_ROLES` config constant to `TOURNEY_STAFF_ROLES` to reflect its tourney-only scope (no behavior change; same role IDs)
- (dev tooling) Tracked `.claude/` hooks and skills in the repo so they survive a fresh clone, reversing the earlier decision to ignore them, and documented `.claude` in the README
- (dev tooling) Hardened authorship for cloud sessions: commits are authored as `RemainingDelta` with no AI attribution trailers, session URLs, or PR footer, and a new CI check enforces the PR-title format
- (dev tooling) Pinned Ruff to one version across local and CI and fixed `make lint` / `make test` failing on a clean checkout

## 🐛 Bug Fixes & Improvements
- **Hall of Fame** no longer shows `$0` when the prizepool can't be read — a failed read is now distinguished from a genuine `$0`, and instead of rendering a permanent public `$0.00` the bot alerts `#tourney-admin` with a manual override and capped automatic retries
- **Leaderboards** no longer crash for members who have no `balance`, `level`, or `exp` field yet — missing fields are defaulted and sorted last
- **Pre-tourney tickets** now ping the opener in the newly created ticket channel so they can find it

## 📝 Documentation
- Added the `v1.13.0` section to `docs/logs/SPECS.md` (every issue in the release) and `docs/logs/CHANGELOG.md` (release notes + PR descriptions)
- Added `docs/PRIVACY_SYSTEM.md` and `docs/ONE_WORD_STORY.md`; feature docs (`TOKEN_SYSTEM`, `XP_AND_LEVELING`, `TOURNEY_OVERVIEW`, `CONFIG_SYSTEM`, `COUNTING_GAME`, `DATABASE`, `SETUP`, `TOURNEY_TICKETS`) were updated alongside their respective changes

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.12.0...v1.13.0


### PR Descriptions

#### PR #494 — 494-Enhancement update documentation for v1.13.0 release (pending)

### Changes
* Added the `v1.13.0` section to `docs/logs/SPECS.md`, documenting every issue in the release (#355, #356, #388, #408, #443, #448, #450, #455, #457, #477, #484, #486, #490, #493, #494)
* Added the `v1.13.0` release notes and these PR descriptions to `docs/logs/CHANGELOG.md`

Closes #494

---

## v1.13.1 — 2026-09-03

# 🚀 Release Notes v1.13.1

## 🐛 Bug Fixes & Improvements
- **20 of 72 slash commands disappeared from Discord and support tickets stopped working:** one feature (scam detection) failed to load at startup, and because all 17 features were loaded inside a single shared error handler, the 12 listed after it were skipped — support tickets among them. The bot then published its shortened command list to Discord, which treats that list as authoritative and deleted every command belonging to a skipped feature. Each feature now loads on its own, so one failure can no longer take out the others
- **The support panel dropdown answered "didn't respond in time" and created no ticket:** the code handling the panel was one of the features that never loaded, so nothing was listening when a category was picked. Fixed by the change above
- **A partial startup can no longer delete commands:** before publishing, the bot now compares its command list against what Discord already has and skips the update if it would remove anything, naming what it would have deleted. An update that only adds commands still goes through, so commands come back on the next restart even while a feature stays broken
- **Startup failures were effectively invisible:** a failing feature logged only its error message, with no exception type and no traceback, which is why this went undiagnosed. Failures now log the exception type and a full traceback
- **Opening a support ticket could crash on a database error:** the ticket counter returned nothing instead of a number, which broke ticket creation before the channel was made. It now falls back to `1`
- **Support tickets acknowledge the click immediately** rather than risking Discord's 3-second timeout while the channel is being created, and the channel's topic is now set as the channel is created — closing a gap where a ticket could end up without its opener recorded, making it invisible to the duplicate check and unusable for close, reopen, and transcripts

## 📝 Documentation
- Added the `v1.13.1` section to `docs/logs/SPECS.md` and `docs/logs/CHANGELOG.md`

## 🔄 Future Enhancements
- Why `features/scam_detection.py` fails to import is still unknown, so automatic scam-image detection and the `!scam-*` commands remain offline. It is the only feature using `cv2`, and the traceback added in this release should identify it on the next restart

**Full Changelog**: https://github.com/RemainingDelta/Remaining7-Discord-Bot/compare/v1.13.0...v1.13.1


### PR Descriptions

#### PR #504 — 503-Bug isolate cog loading and guard the global command sync

### Changes
* Load each cog in its own `try` in `main.py` (`load_features()`), so one failing cog no longer skips the rest — `features.scam_detection` was aborting the load before `features.support_tickets`
* Treat `ExtensionAlreadyLoaded` as success, and log failures with `repr(e)` plus `traceback.print_exc()` instead of a bare `{e}`
* Guard the global sync (`sync_commands()`) — skip it only when it would delete a command, so a partial load can no longer wipe Discord's command list; the tourney setup and the privacy policy repost feed the same guard
* Fixed `get_next_support_ticket_number` falling through as `None` on a DB error, which raised `TypeError` before a ticket channel was created
* Defer in `SupportTicketSelect.callback` before its first network call, and set the topic in `create_text_channel` instead of a follow-up edit
* Added `tests/test_startup.py` and extended `tests/test_support_tickets.py` (19 cases)

### Notes
* `scam_detection` registers no slash commands, so all 72 sync even while it stays broken — only automatic scam-image detection and the `!scam-*` commands stay offline
* Why it fails is still unknown; it is the only cog importing `cv2`, and the traceback added here will show it on the next boot. Tracked as a follow-up

Closes #503

#### PR #507 — 505-Enhancement update version to v1.13.1

### Changes
* Bumped `pyproject.toml` to `version = "1.13.1"` for the v1.13.1 patch release
* Updated the `**Version:**` line in `README.md` to match

### Notes
* `features/config.py` derives `BOT_VERSION` from `pyproject.toml`, so `/version` and the help embeds follow with no edit there — verified it resolves to `v1.13.1`
* Has to land on `dev` before the release PR opens, since `version-check.yml` fails any PR into `main` whose version equals `main`'s

Closes #505

#### PR #508 — 506-Enhancement update documentation for v1.13.1 release (pending)

### Changes
* Added the `v1.13.1` section to `docs/logs/SPECS.md`, documenting every issue in the release (#503, #505, #506)
* Added the `v1.13.1` release notes and these PR descriptions to `docs/logs/CHANGELOG.md`

Closes #506

---
