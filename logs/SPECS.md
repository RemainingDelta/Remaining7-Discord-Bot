# SPECS.md

## Purpose

This file is a chronological, as-implemented spec record for the Remaining7 Discord Bot. Unlike GitHub issues and PRs, it is designed to survive outside of GitHub — in a zip export, in LLM context windows, or as onboarding material for anyone new to the codebase who doesn't have (or shouldn't need) repo history access.

Entries describe what was actually built, not what was originally requested. **As-implemented is the source of truth.** Where an implementation diverged from a filed issue's original spec, the divergence is noted inline at the point it happened — original tickets are never retroactively edited to match what shipped.

## Structure

The record is split into three eras:

- **Part 1 — Baseline** (inherited, pre-December 14, 2025): The codebase as it existed before the current maintainers took over, reconstructed from analysis of the last inherited commit. Intent behind inherited decisions is frequently unknown and is marked explicitly as "intent unclear" rather than guessed at.
- **Part 2 — Pre-Release R7** (December 14, 2025 – January 30, 2026): Development during the period before formal issue tracking was adopted for this project.
- **Part 3 — Tracked** (January 31, 2026 onwards): Development tracked via filed GitHub issues, recorded here in the order implemented.

---

## Part 1 — Baseline (Inherited, pre-December 14, 2025)

### Overview

This section describes the codebase as inherited from repo `idkwhattonamethis-cyber`, commit `9a66c6f`, released November 7, 2025 (source file referenced throughout as `main.19.py`). The bot was a single monolithic `main.py` (~2500 lines) built on `discord.py`, backed by four separate SQLite databases, with no external HTTP APIs and all IDs hardcoded directly in source. SQLite calls were made synchronously throughout, including inside async event handlers.

Because this code was inherited rather than authored by the current team, original intent behind many decisions is unknown. Such cases are marked **intent unclear** rather than assumed.

### 1. Infrastructure & Database Setup

Four SQLite databases were initialized on startup:

- `currency_data.2.db` — `users(user_id PK, balance, last_message)`, `item_tokens(user_id, item_name, quantity)`, `settings(key, value)` (a general key-value dumping ground used across nearly every feature area).
- `quests_data.2.db` — `quests(quest_id, name, description, reward_tokens, reward_exp, target_count, quest_type CHECK daily/weekly, is_active)`, `user_quests(user_quest_id, user_id, quest_id, progress, is_completed, assigned_date)`.
- `leveling_data.2.db` — `leveling(user_id PK, level, exp)`.
- `events_data.2.db` — `active_events(event_id, event_type, start_time, end_time, participation/top-contributor reward fields, goal_* fields, is_active, announcement_message_id)`, `event_progress(event_id, user_id, message_count)`.

`GENERAL_CHANNEL_ID` (`294192597939912714`) was hardcoded at line 21. The `goal_*` columns on `active_events` were added via a try/except `ALTER TABLE` — an explicit poor-man's migration path for databases that already existed before those columns were introduced.

### 2. Message-Based Token Earning

Users earned 4-10 random tokens per message, subject to a 150-second cooldown, restricted to the general channel only. Members with the Server Booster role (`647685778255642626`) received a 1.02x multiplier — intent unclear whether a 2% bonus was really intended, since it rounds to effectively nothing on typical token amounts.

Cooldown state was stored in `settings` under key `last_message_{user_id}`. Separately, `users.last_message` was written on every earn but never read anywhere — a dead column left over from an earlier or abandoned approach.

All earning, XP, quest progress, and event progress were gated to the single general channel. Whether this restriction was intentional for quest and event progress specifically (as opposed to just token earning) is unclear.

### 3. Leveling System

Users earned 10 XP per message, under the same single-channel restriction as token earning. The level-up requirement was `100 * 1.5^(level-1)` XP, with XP subtracted per level on level-up (not tracked cumulatively). Multiple level-ups could occur from a single message if enough XP was earned at once.

The XP curve shown to users (in `/level` and in a helper function `calculate_level_stats`) was two-phase: exponential growth up to level 20, then linear +5000 XP per level thereafter. However, the actual level-up logic used in `on_message` applied the pure exponential formula forever, with no linear phase — meaning the displayed curve and the real in-game curve diverged past level 20. `calculate_level_stats` itself was defined but never called anywhere — dead code.

Commands: `/level [user]` (progress bar embed) and `/levels_leaderboard` (paginated, with the caller's own rank shown in the footer).

### 4. Daily Reward

`/daily` granted 80-160 random tokens on a 24-hour cooldown, multiplied by `1 + (level-1) * 0.05` — i.e., a 5% bonus per level above 1. This 5%-per-level figure was confirmed as authoritative; an inline comment in the source had at one point been explicitly corrected to match this behavior, ruling out an earlier discrepancy. Cooldown state was stored in `settings` under key `daily_{user_id}`.

### 5. Quest System

The bot maintained one active daily quest and one active weekly quest per user at a time. Assignment was lazy and sequential: quests were assigned in ascending `target_count` order, skipping any quest already assigned to that user for the current period. Daily quests keyed off today's date; weekly quests keyed off the most recent Monday.

The default quest pool was: 3 daily message quests (10/25/50 messages), 3 weekly message quests (100/250/500 messages), and 3 weekly invite quests (1/3/5 invites).

Quest type (message vs. invite vs. other) was detected via keyword matching on the quest's name/description text (looking for substrings like "message", "invite", "recruiter", etc.) rather than being a proper schema field — a fragile approach that could misclassify quests with unexpected wording.

Message-quest progress advanced in `on_message`; invite-quest progress advanced in `on_member_join`. A bug existed in the message-quest reward path: it granted rewards using `if reward_tokens > 0: … elif reward_exp > 0: …`, meaning a quest configured with both a token reward and an XP reward would only ever pay out tokens when completed via `on_message`. The invite-quest completion path did not share this bug and correctly paid both reward types. Intent unclear — most likely an unintentional bug rather than a deliberate asymmetry.

Commands: `/quests` (shows active daily + weekly quests plus the invite-quest catalog) and `/create_quest` (permission-gated, with an option to immediately assign the new quest to a specific user or to all currently-active users). The all-active-users assignment path used a 0.05-second sleep between inserts, presumably to avoid hammering the database in a tight loop.

### 6. Invite Tracking

Invite attribution was cache-based rather than using Discord's own invite-tracking APIs directly at join time. On `on_ready`, the bot cached use-counts for all invites; `on_invite_create` and `on_invite_delete` kept that cache fresh as invites changed. On `on_member_join`, the bot diffed current invite use-counts against the cache to determine which invite had been used, then updated the cache immediately after confirming the match — specifically to prevent double-counting if the handler ran slowly and another join came in before it finished. A whole-cache overwrite that would normally run after this diffing loop was commented out, with reasoning in the source that doing so might clobber the immediate targeted update just made above.

The implementation guarded against invites with a `None` use count. There was no persistence layer for the invite cache — it was in-memory only, meaning a bot restart lost all invite attribution state until the cache was rebuilt from scratch on next `on_ready`. The feature required the Manage Server permission and logged warnings when it was missing. On a successful attributed join, the inviter's weekly invite quest progress advanced, and the inviter was DMed on quest completion.

### 7. Message Sprint Events

Admins could create time-boxed "message sprint" events, with only one event allowed to be active at a time. While an event was active, each message sent in the general channel incremented that user's `event_progress.message_count`.

A background task, running on a 1-minute loop, found events whose end time had passed, paid out participation rewards (to everyone with at least 1 message) and top-N contributor rewards, marked the event inactive, and announced the results. Announcements were always sent to the hardcoded `GENERAL_CHANNEL_ID` — the original author left a comment acknowledging this was a shortcut and that the event's guild/channel should really have been stored per-event in the table. The task preferred to edit the original announcement message (via a stored `announcement_message_id`) and fell back to posting a new message if that failed.

Event duration was parsed from strings like `1h`, `30m`, `2d`.

An abandoned sub-feature was present in the schema: `goal_message_count`, `goal_reward_type`, and `goal_reward_amount` columns existed on `active_events` (and were included in the ALTER TABLE migration described in section 1), but nothing in the codebase ever read or wrote them — a goal-based reward mode that was designed and migrated for, but never actually wired up to any logic.

Commands: `/createevent` (permission-gated) and `/event` (public status view showing the caller's rank and a top-N leaderboard).

### 8. Shop, Buy, Redeem & Ticket System

The purchase flow was two-step: `/buy` deducted tokens from the user's balance and credited a corresponding item token to their inventory; `/redeem` then consumed that item token and created a private ticket channel (named `ticket-{username}`) for manual staff fulfillment. `/buy` matched items by free-text name, lowercased.

Item-specific fulfillment instructions were posted automatically when a ticket was created (e.g., a prompt to "Provide your PayPal email" for PayPal redemptions). Redemption counts were tracked in `settings` under keys like `brawlpass_redeemed_count`, `nitro_redeemed_count`, `pin_redeemed_count`, `paypal_redeemed_count`, and `shoutout_redeemed_count`.

Known price inconsistencies between the `/shop` display and the `/buy` charge: Custom Role Color showed 1500 in `/shop` but actually charged 7000 in `/buy`; Custom Emoji showed 500 in `/shop` but charged 1000. Separately, the Matcherino Pin was redeemable and tracked in the budget system (see section 9) but was absent from both the `/shop` display and the `/buy` price list entirely — most likely a shop item that was removed from the front-facing catalog at some point while its back-end redemption and budget-tracking logic survived untouched.

Confirmed prices at the time: Brawl Pass 17000, Nitro 17000, PayPal $15 = 25500, Giveaway Entries 500, Profile Flair 1000, Fancy Title 1500, Shoutouts 8000.

The Staff role (`1340773919459639506`) was hardcoded as the role granted access to redemption ticket channels.

### 9. Budget Tracking

The bot tracked real-money spend on redemptions against a monthly budget, defaulting to $50.00. The cost model used was: Brawl Pass = $10, Nitro = $10, Matcherino Pin = $5. A `manual_total_spent` setting, when present, took precedence over the computed total.

Commands: `/checkbudget` (ephemeral, callable by anyone) and `/editspent` / `/editbudget` (permission-gated).

The monthly reset behavior was cosmetic only: on check, the code read the stored month and, if it had changed, zeroed the *displayed* counts — but it never actually wrote the new month back to storage or reset the underlying counters. As a result the real accumulated counts kept growing indefinitely even as the display appeared to reset; a genuinely partial implementation rather than a working reset.

PayPal and Shoutout redemptions were counted in `settings` alongside the other redemption types, but were excluded from the dollar-budget math entirely — intent unclear whether this was deliberate (e.g., because their real cost wasn't fixed) or an oversight.

A settings key existed with a typo baked into its name: `"premium_ ed_month"` (a stray space in the key).

### 10. Permission System

`OWNER_ID` (`726097595679899701`) was hardcoded. Beyond the owner, a runtime `allowed_users` set could be granted via `/perm @user` (owner-only). This set was not persisted anywhere, so all grants vanished on every bot restart. There were no Discord role-based permission checks anywhere in the codebase — permissions were entirely tied to this in-memory user ID set plus the hardcoded owner ID.

Gated commands: `/give`, `/take`, `/setbalance`, `/reset`, `/setchannel`, `/create_quest`, `/createevent`, `/editspent`, `/editbudget`.

### 11. Admin Commands

`/give` and `/take` operated on tokens, XP, or levels. `/take` floored at 0 tokens/XP and at level 1 (i.e., could not take a user below level 1). `/setbalance` set a user's token balance to an exact value. `/reset` zeroed a user's balance.

### 12. Dead Code & Cross-Cutting Issues

- A duplicate `on_ready` handler existed at lines 1052-1058, but its decorator had been swallowed into a trailing comment, making the entire handler inert. Fixing that comment (i.e., un-commenting the decorator) would silently disable all bot initialization, since the first `on_ready` would then be overridden by this broken duplicate.
- The bot token was hardcoded directly in source at line 2499, and was committed to git history as a result.
- `GENERAL_CHANNEL_ID` was defined in three separate places: once at module level, once re-declared inside `on_message` at line 804, and once inlined as a raw literal inside `/event` at line 2344 — three independent copies that could drift out of sync with each other.
- `/setchannel` stored an `earnings_channel` setting, but nothing in the codebase ever read it back — a dead setting with no effect.
- `/help` referenced a `/hello` command that did not exist anywhere in the bot, and omitted most of the commands that did exist.
- `users.last_message` was written on every message but never read anywhere (see section 2) — a redundant column.
- A trailing section-marker comment appeared in the source after the `bot.run()` call, with nothing following it.
- Whether confining all economy activity (earning, XP, quests, events) to a single channel was intentional is unclear across the board — this is called out repeatedly above because it affects nearly every feature area.

### What Was Dropped Before R7's First Commit

The following inherited features were not carried forward into the first commit of the current (R7) codebase:

- Invite tracking
- Message sprint events
- `/editspent` and `/editbudget`
- `/take` and `/reset`
- Quest system (stubbed out, with its loading code commented out rather than removed)
- Per-message token earning and XP (no `on_message` listener existed at all in the first R7 commit)

---

## Part 2 — Pre-Release R7 (December 14, 2025 – January 30, 2026)

*(To be filled in.)*

---

## Part 3 — Tracked (January 31, 2026 onwards)

*(To be filled in.)*
