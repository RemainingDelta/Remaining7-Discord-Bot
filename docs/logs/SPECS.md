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

> **Framing note:** GitHub issues began December 19, 2025, but were exclusively bug reports — no feature specs were written during this era. All major features were built commit-to-commit. The January 31, 2026 release (v1.0.0) was a catch-up tag with no PR discipline behind it.

### Overview

This era begins with commit `ee66512` ("Bot code refactored", December 14, 2025) — the first commit of the current R7 codebase — and ends at commit `4c032a0` (January 23, 2026), the last commit before the v1.0.0 tag. Roughly 91 commits were made in this window.

The refactor replaced the inherited monolith with a cog-based architecture: a thin `main.py` loading feature extensions (`features/economy.py`, `features/event.py`, `features/security.py`, `features/brawl/`, `features/quests.py`) plus a tourney system wired via `setup_tourney_commands(bot)`. The four SQLite databases were replaced with a single MongoDB database (`r7_bot_db`) accessed asynchronously via `motor` through helper functions in `database/mongo.py`. A `BOT_MODE` environment switch (`TEST`/`REAL`) selects between `FAKE_TOKEN` and `DISCORD_TOKEN` and, from December 26 onward, between two full sets of hardcoded channel/role/emoji IDs in `features/config.py` — dev-server IDs versus production IDs. The bot token moved out of source into `.env`.

Feature classifications below: **MIGRATED** (existed in the baseline SQLite monolith, rewritten for MongoDB), **NEW** (did not exist in baseline), **STUBBED** (present in baseline but missing or placeholder-only for part or all of this era).

### Infrastructure & Database — MIGRATED (total rewrite)

MongoDB collections replacing the four SQLite databases:

- `users` — consolidates the baseline's separate currency/leveling/inventory tables into one document per user: `balance`, `level`, `exp`, `inventory.{item}` counts, plus Brawl Stars fields (`currencies.{coins,power_points,credits,gems}`, `brawlers.{id}.{level,gadgets,star_powers,hypercharge}`).
- `settings` — key-value store, same dumping-ground role as baseline (`last_message_{uid}`, `daily_{uid}`, redemption counters, `monthly_budget`, `manual_total_spent`).
- `hacked_users`, `payouts` + `payout_logs`, `blacklist`, `quests` + `user_quests` — all new collections for new features (below).

Quirk carried into everything: `get_user_data` is the shared fetch path and self-heals users by force-creating a Brawl Stars starter document (Shelly at level 1, 100 coins) — so merely checking a token balance creates a brawl profile. `get_user_rank` contains a legacy int-vs-string `_id` fallback, evidence of an early data-format migration mid-era.

### Economy Core (balance, shop, daily, leveling) — MIGRATED

Commands carried over: `/balance`, `/leaderboard`, `/level`, `/levels_leaderboard`, `/daily`, `/shop`, `/buy`, `/redeem`, `/checkbudget`, `/give`, `/setbalance`, `/perm`. Dropped from baseline: `/take`, `/reset`, `/setchannel`, `/editspent`, `/editbudget`.

Changes from baseline:

- **Shop**: free-text item matching replaced with slash-command choices/autocomplete driven by a `SHOP_DATA` dict in config. Catalog reshuffled: Brawl Pass 15,300 (was 17,000; repriced January 13 "to reflect in game changes"), **Brawl Pass+ 22,100 (new item)**, Nitro 17,000, PayPal $15 = 25,500, Shoutout 12,000 (was 8,000). Custom Role Color, Custom Emoji, Profile Flair, Fancy Title, and Giveaway Entries were all dropped — which also eliminated the baseline's show-one-price-charge-another inconsistencies.
- **Redeem**: same two-step buy-then-redeem flow with a `ticket-{username}` channel; ticket staff role is now `ADMIN_ROLE_ID` from config. Redemption counters kept in `settings`. Vestiges: a duplicated `elif "brawl pass" in item` instruction branch (dead — identical condition twice); `"brawl pass+"` maps to a `brawlpass+_redeemed_count` counter that `/checkbudget` never reads; and because "brawl pass+" contains "brawl pass" as a substring, Brawl Pass+ redemptions also match the Brawl Pass instruction branch.
- **Budget**: only `/checkbudget` survived (now visible to anyone, ephemeral). Same cost model ($10 Brawl Pass, $10 Nitro, $5 Matcherino Pin) and `manual_total_spent` override. The baseline's cosmetic monthly reset is gone entirely — there is *no* reset logic at all now. `pin_redeemed_count` is read but nothing ever increments it (the pin item no longer exists) — the baseline's orphaned-pin situation, inverted. PayPal/Shoutout/Brawl Pass+ redemptions are counted but excluded from dollar math — baseline's "intent unclear" carried forward.
- **Daily**: same 80–160 tokens, 24h cooldown, 5%-per-level bonus.
- **Leveling**: same `100 * 1.5^(level-1)` formula and same baseline defect carried forward — `/level` displays a two-phase curve (exponential to 20, then +5000/level) while actual level-ups remain pure exponential forever.
- **Permissions**: hardcoded `OWNER_ID` is gone. `has_permission` = has `ADMIN_ROLE_ID` role OR is in the in-memory `allowed_users` set. `/perm` is now usable by any permitted user (baseline: owner-only). The set is still not persisted — grants still vanish on restart.

### Message-Based Token Earning & XP — STUBBED, then rebuilt (January 17)

**Absent for the first five weeks of the era** — the December 14 refactor shipped with no `on_message` listener, so per-message tokens and XP silently stopped. Reported as issue #2 on day one of issue tracking; not restored until January 17 (see bug log below). As rebuilt: 2–5 tokens per message (baseline: 4–10), 60-second cooldown (baseline: 150s), **no channel restriction** (baseline: general channel only), booster bonus changed from a 1.02x multiplier to a 7% chance of +1 token (comment: "Avg 2% increase"), and a guard treating timestamps more than an hour in the future as expired cooldowns ("bugged negative timestamps"). XP: 10 per message, multi-level-ups in one message, level-up embeds — same as baseline minus the channel restriction. The `users.last_message` dead column was not carried over; cooldowns live only in `settings`.

### Supply Drops — NEW

An automatic drop task loops every 6 hours with a random 0–12.6h additional sleep, posting a claimable crate of 100–300 tokens to the general channel. First-click-wins claim button; the embed updates to show who claimed. `/drop <amount>` (permission-gated) forces a manual drop. Moderators were barred from claiming on December 23. The claim view's 30-minute timeout was removed on January 23 (issue #35). This feature generated 2 of the era's 7 bugs (#3, #35).

### Quest System — STUBBED, then rebuilt (January 18)

Stubbed for the first five weeks (commented-out load in `main.py`), reported as issue #15, rebuilt January 18 on MongoDB. The rebuild is a redesign, not a port:

- Pool: 3 daily message quests (80/160/240 messages — baseline was 10/25/50) and 3 weekly (500/750/1000 — baseline was 100/250/500), each paying both tokens and XP. Defined in code (`DEFAULT_QUESTS` in `features/quests.py`), seeded into the `quests` collection only if it's empty.
- Assignment is **random** from the matching pool (baseline: sequential by ascending target). One daily + one weekly per user, lazily assigned on first message or `/quests` view. Daily expiry keys off calendar date; weekly keys off ISO week number (baseline: most recent Monday). Completed quests are intentionally returned as still-active until the period rolls over, so a new one isn't assigned same-day.
- Invite quests were dropped entirely. A vestigial invite cache (`on_invite_create`/`on_member_join` handlers) remains in the cog, explicitly commented as "kept for stability, but unused for quests now".
- The baseline's fragile keyword matching survives in new form: message-quest filtering checks for the substring "message" in the quest's *description*.
- The baseline's tokens-XOR-XP reward bug is fixed: both reward types now pay out (two independent `if` blocks). Progress counts messages in **any** channel.
- `assign_random_quest` contains defensive handling for `quest_type`/`type` and `target_count`/`target` field-name mismatches plus debug printing — evidence the collection was hand-edited in production during the rebuild.
- `/quests` shows daily + weekly with progress bars; a January 19 follow-up added reward amounts to the display. `/create_quest` from baseline was not carried over.

### Tourney & Ticket System — NEW

The largest new system of the era, and the ancestor of everything in today's `features/tourney/`. Built across December 19–22, no design doc.

- **Ticket creation**: button panels (`/tourney-panel`, `/pre-tourney-panel`) open modals — main tourney requires Team Name, Match No., Issue; pre-tourney has optional team name. Tickets are created as `「❗」ticket-NNN` channels in category pairs (active/closed × tourney/pre-tourney), with the opener and staff roles granted access. Ticket metadata (opener ID, team, bracket, issue) is stored **in the channel topic** — the DB is not involved. A proof-required embed is posted in each main-tourney ticket.
- **Rate limiting**: max 3 open tickets per user, 3-minute creation cooldown — tracked in-memory only (resets on restart). Ticket counters are also in-memory; `!starttourney` resets the main counter, but the pre-tourney counter is never reset — intent unclear, probably an oversight.
- **Capacity management** (added for issue #7): hard cap 50 tickets per category with admin ping, soft warning at 40, auto-purge of oldest closed tickets (with transcripts) when the closed category hits 40 on `!close`, full-category guards on reopen.
- **Lifecycle commands**: `!close`/`!c` (move to closed category, rename `「👍」`, lock opener's send permission, post Delete/Reopen buttons), `!delete`/`!del` and `!reopen` as button fallbacks, `/add` and `/remove` for ticket access. Deletions produce a plain-text transcript (header from topic metadata, full message history, attachment URLs) that is DMed to the opener and posted to the log channel.
- **Phase management**: `!starttourney` resets the counter, locks the general support channel (`!lock`, 6-hour in-memory auto-reopen timer), opens the main tourney support channel with a fresh panel, closes pre-tourney support, deletes all pre-tourney tickets with transcripts, renames channels via background tasks (rate-limit tolerant), and starts the queue dashboard. `!endtourney` mirrors this in reverse. `!unlock` manually reopens the support channel.
- **Queue dashboard**: 15-second loop editing/re-posting a "Live Tournament Queue" embed in the support channel — currently-serving ticket number (max closed number + 1, falling back to lowest open), queue length, jump-to-bottom repost logic. `/queue` gives a user their position from inside a ticket.
- **Blacklist**: `/blacklist add|remove|list` with reason, Matcherino profile link, and alt IDs, stored in the `blacklist` collection. Opening any ticket triggers a check that pings tourney admins with the blacklist record if the opener is flagged.
- **Payouts**: `/payout-add` (Split or Flat mode) records admin compensation in a batch system (`payouts` per-user amounts + `unpaid_batches` receipt IDs, `payout_logs` global history), `/payout-list` pending balances, `/payout-history` multi-user batches still outstanding, `/payout-reset` per-user or all (with confirm view). All payout commands are gated on `is_staff` (any of tourney admin / founder / admin roles).
- **Hall of Fame**: `/hall-of-fame` posts tournament results with an automatic 50/25/15/10% prize split.

### Security ("Hacked") System — NEW

Added December 18. `/hacked` (slash, with `days_to_clean` parameter defaulting to 7) and `!hacked` (reply to a suspicious message) flag a compromised account: 7-day timeout, record in the `hacked_users` collection, and a purge of the user's messages across all text channels, voice-channel chats, and threads within the cleanup window (0.1s sleep between channels). Cannot target equal-or-higher roles. Result embed is logged to the moderator logs channel (only — after issue #29). `/unhacked` lifts the timeout and clears the flag; `/hacked-list` lists flagged users. Permission: Admin or Moderator role — notably this system uses real role checks, unlike the economy's `allowed_users` set.

### Event Channel Maintenance — NEW (replaces baseline events entirely)

The baseline's message-sprint events were dropped; the `Events` cog that replaced them (December 15–17) is an unrelated feature that reuses the name:

- Three color-coded event channels (red/blue/green) with `/clear-red`, `/clear-blue`, `/clear-green` purge commands, restricted to Admin/Event Staff roles and usable only in the event-staff channel.
- A daily task at 12:00 AM ET checks each event channel's oldest message; if older than 7 days it posts a warning embed to the staff channel with a one-click purge button (styled per channel color). Rationale in-code: Discord can't bulk-delete messages older than 14 days.
- `/event-rewards <message_id>` (Admin only): parses `@User <amount>` pairs out of an announcement-channel message via regex, shows a preview with totals, and on confirmation pays each user tokens and reacts ✅ to the source message to prevent double-processing. This replaces the baseline's automated event reward payout with a staff-driven parse-and-confirm flow.

### Brawl Stars Collection — NEW

Built December 26 – January 4 in a rapid burst on the `brawl` branch. A gacha/collection minigame entirely absent from baseline:

- **Data**: `brawlers.json` roster (98 brawlers with rarity, gadgets, star powers, hypercharge) loaded into a `Brawler` dataclass at startup. Per-user state in `users.brawlers` and `users.currencies` (coins, power points, credits, gems). Every user self-heals to own Shelly.
- **Drops**: `/megabox` (10 weighted rolls) and `/starrdrop` (rarity roll, then reward roll within rarity) from weighted loot tables in config. Brawler drops pick a random eligible brawler of the rolled rarity; duplicates convert to fallback credits. Gadget/star power/hypercharge drops select from brawlers the user owns at the required level (7/9/11), falling back to 1,000 coins if none are eligible.
- **Progression**: `/upgrade` — interactive per-brawler leveling to 11 using power points + coins on an escalating cost curve; levels 7/9/11 gate gadgets/star powers/hypercharges. `/buy_ability` — purchase missing abilities with coins (1,000/2,000/5,000). `/buy_brawler` — rarity-tiered credit shop showing only unowned brawlers (200–5,500 credits). `/brawlers` — paginated collection view with per-brawler level and ability counts. `/profile` — currency wallet and collection-completion stats.
- Every embed carries the Supercell fan-content-policy disclaimer (added December 28 alongside removal of a debug command).

### Bug Log — the 7 issues of this era

GitHub issues from this window were exclusively bug reports. For each: the report, the actual fix, and any divergence between them.

**#2 — "Chat activity is no longer generating token rewards"** (filed Dec 19, first issue ever; fixed Jan 17, commit `320cbfa`). Report: passive tokens-per-message stopped working after the rewrite. Actual fix: the refactor had shipped no `on_message` at all, so the fix re-implements the entire listener — tokens *and* XP/leveling (the report only mentioned tokens; XP earning was equally dead for those five weeks). As-implemented differs from #2 in the following ways: the issue framed this as restoring the old behavior, but the rebuilt earning changed every parameter — 2–5 tokens instead of 4–10, 60s cooldown instead of 150s, the general-channel-only restriction silently dropped (earning now worked everywhere; this became a recurring problem fixed much later, v1.9.2/v1.10.0 era), and the booster bonus redesigned from a 1.02x multiplier to a 7% chance of +1 token. A follow-up commit (`7777c07`) cleaned up imports and the README.

**#3 — "Interaction 10062 (Unknown Interaction) and Webhook Rate Limiting in Economy Module"** (filed Dec 20, fixed same day, commit `e65fafe`). Report: console logs showing `Unknown interaction` failures in the supply-drop claim button and `/balance` during webhook rate-limiting. Fix: defer-early pattern — `claim_callback` now defers immediately and uses `followup`/`edit_original_response`; `/balance` defers before the DB read. As-implemented differs from #3 in the following ways: the issue implied a broad rate-limiting problem across the economy module; the fix touched exactly the two call sites in the attached logs and left every other command's interaction pattern unchanged (several were deferred piecemeal in later commits).

**#7 — "`!close` command crashes when category channel limit (50) reached"** (filed Dec 21, fixed same day, commit `e5df69a`). Report: `HTTPException: 400` moving a ticket into a full archive category; asked for graceful handling. Fix went substantially beyond the report: capacity checks on *ticket creation* (hard 50-cap refusal + admin ping, soft warning at 40), auto-cleanup on `!close` that transcripts-and-deletes the oldest closed tickets when the archive hits 40, a full-category guard on reopen, and a new `TOURNEY_ADMIN_CHANNEL_ID` config entry. As-implemented differs from #7 in the following ways: scope — the issue asked to not crash on close; the fix built a whole capacity-management layer. It also quietly promoted the ticket-creation cooldown from 0.1 minutes (a leftover testing value) to 3 minutes — an unrelated behavior change buried in the bug-fix commit.

**#15 — "Quests got removed"** (filed Dec 23, fixed Jan 18, commit `2df28d8`). Report: quests existed in the old bot and were lost in the DB migration/refactor. Fix: quest system rebuilt from scratch on MongoDB (`features/quests.py` + quest helpers in `mongo.py`). As-implemented differs from #15 in the following ways: the issue asked for the removed feature back; what shipped is a redesign — different quest pool (80/160/240 daily and 500/750/1000 weekly vs. baseline's 10/25/50 and 100/250/500), random instead of sequential assignment, invite quests dropped entirely, and the baseline's pay-tokens-XOR-XP bug fixed in passing. A follow-up (`ca95869`, Jan 19) added reward amounts to the `/quests` display.

**#16 — "Budget doesn't seem to work as intended"** (filed Dec 23, **not fixed in this era** — closed March 12, 2026, in the v1.7.4 timeframe). Report: budget doesn't update on redemption and the update commands (`/editspent`, `/editbudget`) are gone. Throughout this entire era the budget system remained read-only display math over redemption counters, with no reset and no way to adjust spend. This is the only pre-release bug that survived past v1.0.0.

**#29 — "Hacked Log in Transcript Channel"** (filed Jan 11, fixed Jan 17, commit `0f5e82f`). Report: hacked-user logs were being posted to the transcript/log channel instead of only the moderator logs channel. Fix: exactly as reported — `_send_security_logs` reduced from dual-channel (LOG_CHANNEL_ID + moderator logs) to moderator logs only. No divergence.

**#35 — "Token Drops Unclaimable After 30 Minutes"** (filed Jan 24, fixed within 10 minutes, commit `2aa9163`). Report: supply-drop claim buttons died after 30 minutes ("Interaction Failed") with acceptance criterion "drops remain claimable until claimed". Fix: one line — `DropView` timeout changed from 1800 seconds to `None`. Matches the acceptance criterion exactly. (Note the view is still non-persistent: an unclaimed drop still dies if the bot restarts — the criterion holds only within a bot session; whether that gap was in scope is unclear.)

### Known Debt at the End of This Era

State of the code as tagged v1.0.0 on January 31, 2026:

- In-memory state everywhere: `allowed_users` permission grants, ticket counters, per-user ticket limits/cooldowns, the support-channel lock timer, and supply-drop claim views all reset or die on restart.
- The pre-tourney ticket counter is never reset by `!starttourney` (only the main counter is).
- Budget (#16) still broken; no reset logic at all; `pin_redeemed_count` read but never written; Brawl Pass+ counted but never included in dollar math.
- The `/level` display curve still diverges from actual level-up math past level 20 (inherited from baseline).
- Vestigial invite cache in the quests cog; dead duplicate `elif` in redeem instructions.
- Token/XP earning has no channel restriction — the seed of the "earning everywhere" bugs addressed repeatedly in later eras.

---

## Part 3 — Tracked (January 31, 2026 onwards)

<!-- generated:part3 by scripts/generate_specs.py -->

Entries below were assembled in two passes. A script (`scripts/generate_specs.py`) built the structure: for each release, the commit range since the previous tag was scanned for issue-branch references, and each issue's filed spec is quoted with its fixing commits. A full manual review then compared every issue body against its actual diff. Each entry carries a reviewed verdict: either the implementation matches the filed spec, or an explicit "as-implemented differs" note describing exactly how — plus review notes for anything worth knowing that falls short of a divergence.

### v1.0.0 — 2026-01-31

Catch-up tag over the full pre-release history. Issues fixed before this release are covered narratively in Part 2 and are not re-listed here.

### v1.0.1 — 2026-01-31

#### #39 — Bug: `Live Tournament Queue` doesn't delete sometimes after ending tourney (Bug)

> ### Overview
> The `Live Tournament Queue` embedded is not deleted when running !endtourney after long sessions (5+ hours). It works in short tests but fails when the channel has activity.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] The Dashboard message is successfully and permanently deleted upon `!endtourney`, regardless of how long the tournament has been running (e.g., 1 hour vs 6 hours).
> - [ ] The background task updating the dashboard is confirmed stopped before the deletion logic runs.
>
> ### Steps to Reproduce Bug
> - [ ] Run `!starttourney`.
> - [ ] Allow the tournament to run for an extended duration (5+ hours).
> - [ ] Run `!endtourney`.
> - [ ] Result: The Dashboard embed delet …(truncated)

Implemented in `ab1f7e2`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.0.2 — 2026-02-01

#### #41 — Feature: Add Team & Match Info to Transcript Logs (Feature)

> ### Overview
>
> Currently, ticket details are hidden inside attached text files, making them impossible to search via Discord search. This feature adds the **Team Name** and **Match Number** directly to the deletion log message to enable instant searching.
>
> ### Technical Requirements 
> - [ ] Update `tourney_utils.py`: Modify `delete_ticket_with_transcript` to parse the channel topic.
> - [ ] Log Content: Extract `Team Name` and `Match Number` and append them to the message sent to `LOG_CHANNEL_ID`.
> - [ ] Fallback: Display "N/A" if the topic data is missing or malformed to prevent errors.
>
> ### Acceptance Criteria 
> - [ ] Deletion logs explicitly display "Team: [Name]" and "Match: [ID]".
> - [ ] Searc …(truncated)

Implemented in `9b14159`. Files: `README.md`, `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.1.0 — 2026-02-01

#### #43 — Feature: Shop Pagination & New Passes (Feature)

> ### Overview
> Add "Clash of Clans Gold Pass" and "Clash Royale Diamond Pass" to the shop inventory and implement a pagination system (Next/Previous buttons) to support the growing item list.
>
> ### Technical Requirements 
> - [ ] Add `Clash of Clans Gold Pass` to the shop config with a value of **$7**.
> - [ ] Add `Clash Royale Diamond Pass` to the shop config with a value of **$12**.
> - [ ] Scale the R7 Token cost for each new item using a base of 1700 tokens as 1 dollar. 
> - [ ] Implement a pagination View class with `Next` and `Previous` buttons.
> - [ ] Update the shop command to chunk items (e.g., 5 items per page) and display the correct slice based on the current page index.
>
> ### Acceptance Crit …(truncated)

Implemented in `dec77ca`. Files: `features/config.py`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Shipped with 4 items per page (the issue's example suggested 5).

### v1.1.1 — 2026-02-08

#### #46 — Enhancement: Reduce Chat Token Cooldown to 20s (Enhancement)

> ### Overview
> Update the on_message economy logic to lower the time required between token rewards.
>
> ### Current Behavior
> Users must wait 60 seconds between messages to earn tokens.
>
> ### Proposed Behavior
> Users will only need to wait 20 seconds between messages to earn tokens.
>
> ### Technical Requirements
> - [ ] In cogs/economy.py, change the time difference check from >= 60 to >= 20.
>
> ### Acceptance Criteria
> - [ ] A user sending a message 21 seconds after their last one receives tokens.
>
> ### Benefit/Impact
> Encourages faster-paced conversation and makes the economy feel more rewarding for active users.

Implemented in `9732ae6`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.1.2 — 2026-02-08

#### #48 — Enhancement: Restrict Staff from Redeeming R7 Rewards (Enhancement)

> ### Overview
> Update the `/redeem` command to prevent staff members (Trial Moderator and above) from redeeming shop items. 
>
> ### Current Behavior
> Currently, any user with enough tokens—including staff members—can redeem items from the shop. 
>
> ### Proposed Behavior
> Users holding Trial Moderator, Moderator, or Admin roles should be blocked from using the /redeem command. If they attempt to use it, the bot should return an ephemeral error message (e.g., "❌ Staff members cannot redeem rewards.").
>
> ### Technical Requirements
> - [ ] In cogs/economy.py, add a role check at the beginning of the redeem command.
> - [ ] Check if the user has the `TRIAL_MOD_ROLE_ID`, `MODERATOR_ROLE_ID`, or `ADMIN_ROLE_ID` …(truncated)

Implemented in `3d04e72`. Files: `features/config.py`, `features/economy.py`

⚠️ as-implemented differs from #48: the fix also blocks /buy for staff, not just /redeem as filed (commit title acknowledges the wider scope).

### v1.1.3 — 2026-02-10

#### #49 — Enhancement: Add new Brawler "Glowbert" to the minigame configuration (Enhancement)

> ### Overview
> Update the game configuration to include the new **Mythic** brawler, "Glowbert." This involves adding his stats to the JSON database and his emoji to the configuration file.
>
> ### Current Behavior
> "Glowbert" is missing from `brawlers.json` and `EMOJIS_BRAWLERS`, so he cannot be rolled or viewed.
>
> ### Proposed Behavior
> Glowbert should be purchasable/rollable as a Mythic brawler with a custom emoji.
>
> ### Technical Requirements
> - [ ] Update `brawlers.json` with Glowbert info
> - [ ] Update `config.py`: Add the emoji ID to `EMOJIS_BRAWLERS` dictionary (`REAL` and `TEST`)
>
> ### Acceptance Criteria
> - [ ] Glowbert appears in the `/brawlers` list under Mythic.
> - [ ] The emoji `<:brawler_glo …(truncated)

Implemented in `b5b8e69`. Files: `features/brawl/brawlers.json`, `features/brawl/commands.py`, `features/config.py`

⚠️ as-implemented differs from #49: the commit bundles brawler-shop pagination (removing the 25-item dropdown cap) and rarity-button color changes — none of which the issue mentions.

### v1.1.4 — 2026-02-14

#### #58 — Bug: Restrict payout modification commands to Admins (Bug)

> ### Overview
> Currently, all `/payout` commands use the generic `is_staff()` check. This allows Tourney Admins to execute financial modification commands like `/payout-add` and `/payout-reset`. While Tourney Admins should be able to *view* the lists (`list`, `history`), they must not be able to *add funds* or *wipe the database*.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] `/payout-add` and `/payout-reset` return "Permission Denied" for users who only have the Tourney Admin role.
> - [ ] `/payout-list` and `/payout-history` remain accessible to Tournament Admins for transparency.
> - [ ] Only users with the high-level `ADMIN_ROLE_ID` can execute the modification commands.
>
> ### Steps …(truncated)

Implemented in `4aa78ee`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.1.5 — 2026-02-14

#### #54 — Bug: Inconsistent decimal precision in /balance (Bug)

> ### Overview
>
> The `/balance` command sometimes displays long decimal numbers (e.g., `12182.699999999997`) instead of clean values. This appears to happen inconsistently, affecting some users but not others.
>
> ### Acceptance Criteria
>
> How do we know it's done?
>
> * [ ] Balance always displays rounded to 2 decimal places (or as a whole number) for all users.
>
> ### Steps to Reproduce Bug
>
> * [ ] Run `/balance` for various users.
> * [ ] Observe that some users receive a clean number (e.g., `100`), while others see long decimals.
>
> ### Impact
>
> Users may believe the bot is broken or glitchy due to the unpolished display. While it does not affect the actual value stored in the database, it degrades the us …(truncated)

Implemented in `e19bac8`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Displays are truncated via int() rather than rounded; underlying float balances remain in the DB (display-only fix, as the issue anticipated).

### v1.1.6 — 2026-02-14

#### #50 — Bug: Fix Brawler Data (Bug)

> ### Overview
> The `brawlers.json` file contains widespread inaccuracies where Gadgets, Star Powers, and Hypercharges use placeholder or "hallucinated" names (e.g., Kenji's Star Power is listed as "Wasabi Wipeout" instead of "Studied the Blade"). The entire file needs to be cross-referenced with official game data.
>
> ### Acceptance Criteria
> - [ ] **All** 98+ Brawlers in `brawlers.json` have their abilities matched 1:1 with the official Brawl Stars Wiki.
> - [ ] No placeholder names (e.g., "Default Gadget") remain in the file.
> - [ ] Typos in existing correct names are resolved.
>
> ### Steps to Reproduce Bug
> 1. Pick a recent Brawler in `brawlers.json` (e.g., Kenji, Berry, Clancy).
> 2. Compare their `g …(truncated)

Implemented in `3f91399`. Files: `features/brawl/brawlers.json`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The diff changes ~22 lines of brawlers.json; whether the full 98-brawler roster was audited 1:1 as the acceptance criteria demand is not verifiable from the diff.

### v1.2.0 — 2026-02-14

#### #47 — Feature: Message Translation Command (Feature)

> ### Overview
> Implement a `!translate` command that allows users to translate foreign language messages into English by replying to them. This helps bridge language barriers and assists staff in moderating non-English content.
>
> ### Technical Requirements 
>
> - [ ] Install deep-translator (`pip install deep-translator`).
> - [ ] Create a `!translate` command handler that retrieves the content of the referenced (replied-to) message.
> - [ ] Implement logic using `GoogleTranslator(source='auto', target='en'`) to translate the text.
> - [ ] Add error handling for empty messages or commands sent without a reply reference.
>
> ### Acceptance Criteria 
>
> [ ] Replying with `!translate` to a message like "Bonjour …(truncated)

Implemented in `d64e1e7`. Files: (none)

⚠️ as-implemented differs from #47: the issue specced only a reply-based !translate into English; what shipped also includes /translate (English → 55 target languages) with autocomplete and a full language map — a much larger feature than filed.

### v1.2.1 — 2026-02-14

#### #63 — Enhancement: Manual Source Language Override for !translate (Enhancement)

> ### Overview
> Updates the `!t` command to allow users to manually specify the **source** language (e.g., `!t hindi`) instead of relying on the auto-detector.
>
> ### Current Behavior
> `!t` always uses `langdetect` to guess the source language. If the text is short or ambiguous, the detection sometimes fails or picks the wrong language.
>
> ### Proposed Behavior
> Users can force the source language by typing `!t <language>` (e.g., `!t spanish`). The bot will skip auto-detection and translate specifically from that language into English.
>
> ### Technical Requirements
> - [ ] Add an optional `source_input` argument to the `!translate` command.
> - [ ] Implement a lookup to match `source_input` to the correct …(truncated)

Implemented in `d137eb0`. Files: `features/translation.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: AC asked for a "Manual Detection" footer; shipped as an embed author line "Manual Language Override" instead.

### v1.2.2 — 2026-02-14

#### #45 — Enhancement: Daily Reward Activity Requirement (Enhancement)

> ### Overview
> To encourage active participation, users must now send at least 5 messages in the server each day before they can use the `/daily` command to claim their rewards.
>
> ### Current Behavior
> Users can claim their `/daily` rewards immediately upon logging in, regardless of whether they have contributed to server conversations that day.
>
> ### Proposed Behavior
> The `/daily` command will be locked behind a 5-message daily threshold. If a user attempts to claim the reward without meeting this requirement, the bot will return an ephemeral message showing their current progress.
>
> ### Technical Requirements
> - [ ] Update `on_message` to track message counts using a `YYYY-MM-DD:COUNT` string for …(truncated)

Implemented in `5e46b79`. Files: `features/economy.py`

⚠️ as-implemented differs from #45: the issue asked for an ephemeral lock message; the shipped status embed is public (ephemeral=False). The fix also accidentally duplicated the @commands.Cog.listener() decorator — the cause of the double level-up bug later fixed in #68.

### v1.3.0 — 2026-02-15

#### #55 — Feature: Economy Guide Command (Feature)

> ### Overview
>
> Implement a new slash command `/economy_help` that provides users with a comprehensive guide on the R7 Token economy. This will help new and existing members understand how to earn tokens (chatting, dailies, events) and what they can spend them on (shop, brawlers, items).
>
> ### Technical Requirements 
>
> - [ ] Implement a new slash command `/economy_help`.
> - [ ] Design a rich Embed response that includes:
>     - **Earning Methods:** Chat activity (cooldowns/rates), Daily rewards (`/daily`), Supply Drops, and Event participation.
>     - **Spending Options:** The Token Shop (`/shop`)
>     - **Commands List:** A quick reference to economy commands like `/balance`, `/shop`, `/daily`, and …(truncated)

Implemented in `30fc555`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The guide text asserts "the reward budget resets every month", which was not actually implemented at the time (#16 was still open).

#### #56 — Feature: General Help Command (Feature)

> ### Overview
>
> Implement a central `/help` command that lists all **publicly available** bot commands, categorized by function (Economy, Brawlers, etc). This will serve as the main directory for general users to discover features they can actually use, while filtering out administrative commands.
>
> ### Technical Requirements
>
> - [ ] Create a new slash command `/help`.
> - [ ] Design an Embed with distinct categories for general users:
>     - **Economy:** `/balance`, `/daily`, `/shop`, `/redeem`.
>     - **Brawlers & Items:** `/brawlers`, `/profile`, `/buy_brawler`, `/upgrade`, `/megabox`, `/starrdrop`.
>     - **Social & Rankings:** `/leaderboard`, `/levels_leaderboard`.
> - [ ] Explicitly **exclude** s …(truncated)

Implemented in `8b33433`. Files: `features/config.py`, `features/general.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #57 — Feature: Tournament Admin Help Command (Feature)

> ### Overview
>
> Implement a restricted `/tourney_admin_help` command exclusively for Tournament Admins. This command will serve as a centralized reference for all tournament-related management commands and provide a clear workflow for handling support tickets.
>
> ### Technical Requirements
>
> - [ ] Create a new slash command `/tourney_admin_help`.
> - [ ] **Restrict access** to users with the `TOURNEY_ADMIN_ROLE_ID`.
> - [ ] Design an Embed that includes:
>     - **Management Commands:** - `!starttourney`: Initialize tournament channels and panels.
>         - `!endtourney`: Close the tournament session and generate stats.
>         - `/lock` / `/unlock`: Manage access to the general support channel. …(truncated)

Implemented in `410a073`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Gated via is_staff() (tourney admin, founder, or admin) — broader than the issue's tourney-admin-only requirement.

#### #73 — Feature: Event Staff Help Command (Feature)

> ### Overview
> Implement a restricted `/event-staff-help` command to provide a centralized reference for Event Staff. This ensures staff members can efficiently manage event channels and understand the automated cleanup workflows.
>
> ### Technical Requirements 
>
> - [ ] Implement a new slash command `/event-staff-help` within the `Events` Cog.
> - [ ] Add a permission check using the existing `has_event_permission` helper (restricted to `ADMIN_ROLE_ID` or `EVENT_STAFF_ROLE_ID`).
> - [ ] Ensure the response is sent as an **ephemeral** message to keep staff-only instructions private.
> - [ ] Document the channel purge commands: `/clear-red`, `/clear-blue`, and `/clear-green`.
> - [ ] Include an explanation …(truncated)

Implemented in `4643fc8`. Files: `features/brawl/commands.py`, `features/economy.py`, `features/event.py`, `features/tourney/tourney_commands.py`

⚠️ as-implemented differs from #73: the commit also renames five unrelated commands to kebab-case (buy_brawler→buy-brawler, buy_ability→buy-ability, levels_leaderboard→levels-leaderboard, checkbudget→check-budget, economy_help→economy-help, tourney_admin_help→tourney-admin-help) — a bot-wide naming sweep the issue never mentions.


#### #75 — Feature: Moderator Help Command (Feature)

> ### Overview
> Implement a restricted `/mod-help` slash command for general server Moderators. This command serves as a central reference for managing the R7 economy and responding to server security threats (e.g., compromised accounts).
>
> ### Technical Requirements 
> - [ ] Create a new slash command `/mod-help` (recommended to be placed in the `Security` or `Economy` Cog).
> - [ ] Implement a permission check to ensure the command is only accessible to users with `MODERATOR_ROLE_ID` or `ADMIN_ROLE_ID`.
> - [ ] Set the response to be **ephemeral** (hidden from public view).
> - [ ] Categorize the embed into two primary sections:
>     - **Economy Oversight:** `/drop` (Supply Drops), `/give` (Tokens/XP), …(truncated)

Implemented in `c7be5ce`. Files: `features/event.py`, `features/general.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The spec's Economy Oversight list included /drop, which was omitted from /mod-help (it appears in /admin-help instead).


#### #77 — Feature: Admin Help Command (Feature)

> ### Overview
> Implement a restricted `/admin-help` slash command to serve as the master reference for the highest-level bot functions. This command centralizes administrative tools for Economy management, Event payouts, Security protocols, and Tournament financials.
>
> ### Technical Requirements 
> - [ ] Create a new slash command `/admin-help` (Centralized in the `General` cog).
> - [ ] Implement a strict permission check to ensure the command is ONLY executable by users with the `ADMIN_ROLE_ID`.
> - [ ] Set the response to be **ephemeral** to protect sensitive administrative workflows.
> - [ ] Organize the embed into the following functional categories:
>     - **Economy:** `/drop` (Supply Drops), `/gi …(truncated)

Implemented in `8da8ddc`. Files: `features/general.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Adds /perm and the payout read commands beyond the specced list, plus a Treasury section to /tourney-admin-help.

### v1.4.0 — 2026-02-16

#### #68 — Bug: Duplicate Level Up Messages (Bug)

> ### Overview
> The bot is sending the "Level Up!" announcement embed twice for a single level-up event. This is likely caused by a duplicate event listener registration in the `Economy` cog.
>
> ### Acceptance Criteria
> - [ ] The "Level Up!" message is sent exactly once per level.
> - [ ] Duplicate `@commands.Cog.listener()` decorators are removed.
>
> ### Steps to Reproduce Bug
> 1. Send messages to earn XP.
> 2. Cross a level threshold (e.g., from Level 1 to Level 2).
> 3. Observe two identical "Level Up!" embeds appearing in the channel.
>
> ### Impact
> Causes chat clutter and provides a buggy experience for active users.
>
> ### Screenshots/Logs 
> [image]
>
> ### Branch
> [code block omitted]

Implemented in `02ac5cc`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The duplicate decorator being removed here was introduced by the #45 fix.

#### #69 — Feature: Matcherino Data Extraction Utility (Feature)

> Sub issue of Epic #66 
>
> ### Overview
> This issue creates the core Python scraper (`matcherino.py`) that fetches, caches, and parses tournament bracket data from Matcherino. It provides the foundational data layer needed to instantly feed match context and team histories into admin support tickets.
>
> - [ ] Add `beautifulsoup4` and `requests-cache` to the `requirements.txt` file.
> - [ ] Create a new utility file (e.g., `features/tourney/matcherino.py`).
> - [ ] Initialize a `requests_cache.CachedSession` configured with a 60-second expiration to prevent API rate-limiting during high ticket volume.
> - [ ] Write a function (e.g., `fetch_ticket_context(url, match_number)`) that fetches the URL, locates …(truncated)

Implemented in `bf3c1c6`. Files: `.gitignore`, `database/mongo.py`, `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_utils.py`, `features/tourney/tourney_views.py`, `requirements.txt`

⚠️ as-implemented differs from #69: the spec called for HTML scraping of the __NEXT_DATA__ tag with beautifulsoup4; the implementation instead hits Matcherino's hidden JSON API directly (no BS4 at all). It also exceeds the "decoupled from Discord UI" scope by wiring the auto-embed into ticket creation and adding /set-matcherino with DB persistence — and quietly loosens ticket rate limits to 10 open tickets / 0.6-second cooldown (test values that shipped to production and were only corrected in #84).


### v1.5.0 — 2026-02-16

#### #84 — Feature: Tournament Test Mode Toggle (Feature)

> ### Overview
> This sub-issue implements a "Test Mode" command for the tournament system. This allows staff to bypass standard ticket limits and cooldowns during dry runs or stress tests, enabling 100 tickets per person with a 0.1-second cooldown.
> ### Technical Requirements
> - [ ] Create a global boolean variable `TOURNEY_TEST_MODE` in `features/config.py` or within the tournament Cog, defaulting to `False` on startup.
> - [ ] Implement a slash command `/tourney-test-mode <state: True/False>` restricted to high-level staff/admins.
> - [ ] Modify the ticket creation logic in `tourney_utils.py` or `tourney_views.py` to check the `TOURNEY_TEST_MODE` state:
> - **If True:** Set user ticket limit to `100` …(truncated)

Implemented in `91b2a6e`. Files: `features/config.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Also restores production limits to 3 tickets / 3 minutes, fixing #69's leftover debug values. The toggle is available to all tourney staff, not only "high-level staff/admins" as specced.

### v1.6.0 — 2026-02-21

#### #81 — Feature: Matchup History Command (Feature)

> Sub-issue of #66
>
> ### Overview
> This sub-issue implements a dedicated command to retrieve and display the tournament history of teams involved in a specific matchup. It provides staff with instant context on how teams have performed in previous rounds of the current bracket.
>
> ### Technical Requirements 
> - [ ] Update `matcherino.py` to ensure `team_a_history` and `team_b_history` lists are accessible outside the main ticket creation logic.
> - [ ] Implement a new slash command `/match-history <match_num>` in `tourney_commands.py`.
> - [ ] Format the history data into a clean Discord embed, listing previous opponents and the scores of those past matches.
> - [ ] Add error handling for cases where tea …(truncated)

Implemented in `c87a7c3`. Files: `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #82 — Feature: Matchup Status & Latency Diagnostic (Feature)

> Sub-issue of Epic #66 
>
> ### Overview
> This issue creates a manual command to display the current status of a matchup, including player rosters and average game latency. This assists staff in diagnosing lag complaints and verifying active participants.
>
> ### Technical Requirements 
> - [ ] Create a new slash command `/match-info <match_num>` that pulls the same data structure used in the ticket auto-embed.
> - [ ] Update the `fetch_ticket_context` logic to traverse the `reports` -> `statistics` array in the Matcherino API.
> - [ ] Extract the `averageLatency` (ping) value for each player from the most recent game report.
> - [ ] Display the latency stats next to the Matcherino names in the team columns …(truncated)

Implemented in `6fd2589`. Files: `features/tourney/tourney_commands.py`

⚠️ as-implemented differs from #82: the issue's headline latency diagnostic (averageLatency from the reports→statistics array) was never implemented — the command shows only status, scores, and rosters.

#### #83 — Feature: Automated Match Info Refresh (Feature)

> Sub-issue of Epic #66
>
> ### Overview
> This issue implements an automated background task that refreshes match information in active ticket channels every 5 minutes. To ensure maximum visibility for staff, the bot will intelligently manage its presence: editing the existing message if it is still at the bottom, or resending and deleting the old one if new conversation has buried it.
>
> ### Technical Requirements 
> - [ ] Implement a `tasks.loop(minutes=5)` in the `QueueDashboard` or a new dedicated Cog.
> - [ ] Logic to identify active ticket channels in `TOURNEY_CATEGORY_ID` and parse the match number from the channel name (e.g., `ticket-024`).
> - [ ] Query the database for the current Matcherino ID …(truncated)

Implemented in `0f5fc59`. Files: `features/tourney/tourney_commands.py`

⚠️ as-implemented differs from #83: the loop runs every 1 minute, not the specced 5; the match number is parsed from the channel topic, not the channel name; and the commit bundles an unspecced /set-ticket-match command with a rate-limit kill switch. The dashboard refactor also briefly introduced a broken .flatten() call (repaired in #89's commit).

### v1.6.1 — 2026-02-21

#### #89 — Enhancement: Team-Similarity-Validation (Enhancement)

> Enhancement of #66 
>
> ### Overview
> Implements fuzzy string matching to validate user-provided team names against live bracket data during ticket creation and the automated 1-minute refresh.
>
> ### Current Behavior
> The bot pulls match info based only on the match number. If a user provides a correct match number but the wrong team name, the bot displays the matchup without any warning, often confusing staff.
>
> ### Proposed Behavior
> The bot will compare the team name in the channel topic against the two teams in the Matcherino matchup. If the similarity is low, the embed color will shift to red and a "Team Mismatch Warning" field will be added to alert staff.
>
> ### Technical Requirements
> - [ ] Impl …(truncated)

Implemented in `f8d7949`. Files: `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_views.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The commit also fixes the dashboard .flatten() bug from #83 and changes the refresher to always edit in place, dropping #83's delete-and-repost behavior (reintroduced on-tick-only in #132).

### v1.6.2 — 2026-02-21

#### #91 — Bug: Refresher overwrites `/match-info` result (Bug)

> ### Overview
> When staff run `/match-info` for a different match than the ticket’s match (from the topic), the 1-minute refresher later overwrites that `/match-info` embed with the ticket’s own match data.
>
> ### Acceptance Criteria
> - [ ] Refresher only updates the embed for the ticket’s match number (from topic).
> - [ ] `/match-info` embeds for other match numbers are never changed by the refresher.
>
> ### Steps to Reproduce Bug
> - [ ] Open a ticket whose topic has `bracket:123`.
> - [ ] Run `/match-info 199` in that ticket and see Match #199.
> - [ ] Wait for the refresher to run and see that the Match #199 embed is replaced with Match #123.
>
> ### Impact
> Staff can be shown the wrong match after using …(truncated)

Implemented in `dede6c1`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #93 — Enhancement: Version bump and tourney-admin-help updates (Enhancement)

> ### Overview
> Bump the bot version to v1.6.2 and document the Live Match Tracking commands in `/tourney-admin-help` so staff can discover and use `/match-info`, `/match-history`, and `/set-ticket-match` without hunting for them.
>
> ### Current behavior
> - `BOT_VERSION` in `features/config.py` is still `v1.5.0`.
> - `/tourney-admin-help` lists Session Management, Ticket Control, Treasury, Moderation, and Support Workflow but does not mention the Matcherino/live-bracket commands (`/match-info`, `/match-history`, `/set-ticket-match`, `/set-matcherino`).
>
> ### Proposed behavior
> - Set `BOT_VERSION` to `v1.6.2`.
> - Add a section in the tourney-admin-help embed for **Live Bracket / Matcherino** that briefl …(truncated)

Implemented in `6d88875`. Files: `features/config.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.6.3 — 2026-02-24

#### #95 — Bug: Tourney admins can’t use application commands in ticket channels (Bug)

> ### Overview
> Staff with tourney admin roles can’t run Discord application commands (e.g. `/match-info`, `/set-ticket-match`) inside ticket channels. Commands don’t show when in ticket channels. 
>
> ### Acceptance criteria
> - [ ] Tourney admins see and can run app commands (e.g. `/match-info`, `/set-ticket-match`) in ticket channels.
>
> ### Steps to reproduce
> - [ ] Start a tourney and open a ticket (or use an existing open ticket).
> - [ ] As a user with a tourney admin role, open the command picker or type `/` in that ticket channel.
> - [ ] Confirm tourney app commands are missing or don’t run in the ticket, but do work in the tourney support channel.
>
> ### Impact
> Staff can’t fix match/team info or p …(truncated)

Implemented in `0311c49`. Files: `features/tourney/tourney_commands.py`, `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #97 — Bug: `/set-ticket-match` renames ticket channels (Bug)

> ### Overview
> Using `/set-ticket-match` changes the ticket’s channel name (e.g. to `ticket-095`) instead of only updating the stored match number/team in the topic.
>
> ### Acceptance Criteria
> - [ ] `/set-ticket-match` updates topic metadata only (match/team).
> - [ ] Channel name stays unchanged after running the command.
>
> ### Steps to Reproduce
> - [ ] Open a tourney ticket (e.g. `「❗」ticket-063`).
> - [ ] Run `/set-ticket-match` with a new match number.
> - [ ] See that the channel name changes to match the new number.
>
> ### Impact
> Unexpected channel renames confuse staff and break consistency; `/set-ticket-match` is meant to fix metadata, not rename channels.
>
> ### Branch
> [code block omitted]

Implemented in `285ad3f`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #99 — Enhancement: Automate `/hall-of-fame` Command (Enhancement)

> Sub issue of Epic #66 
>
> ### Overview
> This update automates the `/hall-of-fame` command by replacing manual data entry with a single `tournament_id` input. It integrates the newly implemented Matcherino scraper and bracket logic to fetch results directly from the source.
>
> ### Current Behavior
> The `/hall-of-fame` command requires staff to manually type in seven different fields: `tourney_name`, `link`, `total_prize`, `first`, `second`, `third`, and `fourth`. This is time-consuming and prone to human error, such as typos in team names or incorrect prize math.
>
> ### Proposed Behavior
> The updated command will only require a `tournament_id`. Upon execution, the bot will:
> 1. Scrape the tournament na …(truncated)

Implemented in `7480f8c`. Files: `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`, `requirements.txt`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #101 — Enhancement: Version bump to v1.6.3 and /hall-of-fame documentation refinement (Enhancement)

> ### Overview
> Bump the bot version to **v1.6.3** and update the `/hall-of-fame` command description in the admin help guide to reflect the requirement for the tournament ID.
>
> ### Current Behavior
> - `BOT_VERSION` in `features/config.py` is `v1.6.2`.
> - `/tourney-admin-help` mentions `/hall-of-fame` but does not specify that the **tournament ID** is a required input for generating the winner list and prize splits.
>
> ### Proposed Behavior
> - Set `BOT_VERSION` to `v1.6.3`.
> - Update the **Moderation & Results** section in the `/tourney-admin-help` embed to clarify that `/hall-of-fame` requires the tournament ID to fetch and post the results.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` in ` …(truncated)

Implemented in `acd92d3`. Files: `features/config.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.6.4 — 2026-02-28

#### #105 — Enhancement: Regional Support Redirect (South America) (Enhancement)

> ### Overview
> Updates `!starttourney` to accept an optional "SA" argument for regional channel management and modifies `!endtourney` to automatically restore access globally.
>
> ### Current Behavior
> The `!starttourney` command only locks the general support channel (`OTHER_TICKET_CHANNEL_ID`). The `!endtourney` command unlocks only that same channel. Neither command currently interacts with region-specific channels like the Spanish channel.
>
> ### Proposed Behavior
> - **Start:** Running `!starttourney SA` performs all standard tasks and additionally locks the Spanish channel (defined in config). It will post a Heading 1 message in that channel directing users to `#tourney-support`.
> - **End:** `!en …(truncated)

Implemented in `a05a0bb`. Files: `features/config.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #107 — Enhancement: Version bump to v1.6.4 (Enhancement)

> ### Overview
> Bump the bot version to **v1.6.4**. 
>
> ### Current Behavior
> - `BOT_VERSION` in `features/config.py` is `v1.6.3`.
>
> ### Proposed Behavior
> - Set `BOT_VERSION` to `v1.6.4`.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` in `features/config.py` to `"v1.6.4"`.
>
> ### Acceptance Criteria
> - [ ] `/Help` embed title displays `🤖 R7 Bot Command Directory | v1.6.4`. 
>
> ### Benefit/Impact
> - Ensures the versioning remains consistent with the latest deployment.
>
> ### Branch
> [code block omitted]

Implemented in `a4af0e4`. Files: `features/config.py`

✅ Reviewed against the diff: implementation matches the filed spec.

- **#108** — referenced by commits in this range but no matching GitHub issue found (possibly a PR number or deleted issue); skipped.

### v1.7.0 — 2026-03-05

#### #109 — Feature: Tourney Progress Report (Feature)

> Part of #66 
> Sub issue of Epic #66 
>
> ### Overview
> This feature adds a command to provide a real-time health check of the tournament, focusing on bracket completion, round-by-round bottlenecks, and match durations. It allows staff to identify exactly which matches are holding up the progression of the bracket.
>
> ### Technical Requirements 
>
> - [ ] Add a full-bracket scanner to `matcherino.py` that processes the entire `matches` array instead of a single match ID.
> - [ ] Implement logic to calculate the **Completion Percentage** by comparing closed matches against the total bracket size.
> - [ ] Create a "Round Analyzer" to determine the **Dominant Round** and identify "Laggard Matches" (active mat …(truncated)

Implemented in `ef2375c`. Files: `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`

⚠️ as-implemented differs from #109: the specced "Longest Match" tracker was never implemented, and the command shipped as slash /tourney-progress rather than the specced !progress prefix command. A small unrelated timezone fix for duration math is bundled in.

#### #111 — Enhancement: Version bump to v1.7.0 (Enhancement)

> ### Overview
> Bump the bot version to **v1.7.0**. 
>
> ### Current Behavior
> - `BOT_VERSION` in `features/config.py` is `v1.6.4`.
>
> ### Proposed Behavior
> - Set `BOT_VERSION` to `v1.7.0`.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` in `features/config.py` to `"v1.7.0"`.
>
> ### Acceptance Criteria
> - [ ] `/Help` embed title displays `🤖 R7 Bot Command Directory | v1.7.0`. 
>
> ### Benefit/Impact
> - Ensures the versioning remains consistent with the latest deployment.
>
> ### Branch
> [code block omitted]

Implemented in `32c9b79`. Files: `features/config.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.7.1 — 2026-03-07

- **#112** — referenced by commits in this range but no matching GitHub issue found (possibly a PR number or deleted issue); skipped.

#### #113 — Bug: Visual Match Number Discrepancy in `/tourney-progress` (Bug)

> ### Overview
> The `/tourney-progress` command displays raw API match IDs instead of the visual match numbers staff see on the bracket. While the round and teams are correct, the match numbers are wrong (e.g., #225 vs #156).
>
> ### Acceptance Criteria
> - [ ] Bottleneck matches display visual numbers matching the bracket.
> - [ ] AKATSUKI vs Guris shows **#156**.
> - [ ] Lospapus vs mafia brawl shows **#168**.
> - [ ] Tier S de Saudade vs Chill broo shows **#170**.
>
> ### Steps to Reproduce Bug
> - [ ] Run `/tourney-progress` during an active tourney.
> - [ ] Check the **⚠️ Bottleneck Matches** list.
> - [ ] Compare IDs to the visual bracket.
>
> ### Impact
> Staff cannot quickly find the correct matches on the brac …(truncated)

Implemented in `8fdcab5`. Files: `features/tourney/matcherino.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #114 — Enhancement: Tourney Ticket `/add` Read Message History Permission (Bug)

> ### Overview
> Updates the `/add` command to ensure added users can view the full message history of the ticket.
>
> ### Current Behavior
> Users added to a ticket channel may not be able to see messages sent before they were added.
>
> ### Proposed Behavior
> Explicitly grant the `read_message_history` permission to any user added through the `/add` command.
>
> ### Technical Requirements
> - [ ] Ensure `read_message_history=True` is included in the `set_permissions` call within the `/add` command logic.
>
> ### Acceptance Criteria
> - [ ] Users added to a ticket can scroll up and read all previous messages.
>
> ### Benefit/Impact
> Improved UX by allowing newly added staff or players to catch up on the context of th …(truncated)

Implemented in `7134f17`. Files: (none)

⚠️ as-implemented differs from #114: the branch merged for this issue contains the "tournament stuck on Finals in progress" completion-status fix — no /add permission change at all (read_message_history was already granted in /add before this issue was filed). The filed enhancement was effectively a no-op.

#### #116 — Enhancement: Auto-Updating Tourney Progress Dashboard (Enhancement)

> Sub issue of Epic #66 
>
> ### Overview
> Adds a persistent tournament progress panel to the admin channel that automatically refreshes every 5 minutes by updating the existing message.
>
> ### Current Behavior
> Staff must manually invoke the `/tourney-progress` command to see current bracket status and bottlenecks.
>
> ### Proposed Behavior
> The bot will maintain a "Live Dashboard" in the admin channel, automatically fetching new Matcherino data and editing the same message every 5 minutes to prevent spam.
>
> ### Technical Requirements
> - [ ] Implement a `tasks.loop(minutes=5)` background task to trigger the scan.
> - [ ] Store and reference the `dashboard_message_id` to perform edits instead of sending new …(truncated)

Implemented in `0db54c9`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Goes beyond spec — reposts to the bottom when buried (spec said edit-only), recovers the panel after restarts, and adds the "Tournament Over" completion state.

#### #117 — Feature: Sticky Support Redirection (Feature)

> This feature ensures a support redirection notice stays at the bottom of high-traffic channels by deleting its previous instance and re-sending whenever a new message is detected.
>
> ### Technical Requirements 
>
> - [ ] Implement an `on_message` listener for `general`, `brawl-chat`, and `tourney-chat`.
>
> - [ ] Logic to delete the bot's previous embed and send a new one to maintain "sticky" behavior.
>
> ### Acceptance Criteria 
>
> - [ ] The redirection embed always appears at the bottom of the chat after any user interaction.
>
> - [ ] Only one instance of the redirection message exists per channel.
>
> ### Notes
>
> Embed content: `description=f"# ⚠️ Attention!\n# Please use {support_mention} to open a suppor …(truncated)

Implemented in `448774c`. Files: `features/config.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Stickies are gated to active tournaments (enabled by !starttourney, cleaned up by !endtourney) — a scope condition the issue didn't state.

#### #122 — Enhancement: Version bump to v1.7.1 (Enhancement)

> ### Overview
> Bump the bot version to **v1.7.1**. 
>
> ### Current Behavior
> - `BOT_VERSION` in `features/config.py` is `v1.7.0`.
>
> ### Proposed Behavior
> - Set `BOT_VERSION` to `v1.7.1`.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` in `features/config.py` to `"v1.7.1"`.
>
> ### Acceptance Criteria
> - [ ] `/Help` embed title displays `🤖 R7 Bot Command Directory | v1.7.1`. 
>
> ### Benefit/Impact
> - Ensures the versioning remains consistent with the latest deployment.
>
> ### Branch
> [code block omitted]

Implemented in `f6b8825`. Files: (none)

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.7.2 — 2026-03-08

#### #124 — Enhancement: Automated Semi-Finals and Finals Announcements (Enhancement)

> ### Overview
> Automate the announcement of high-stakes matches (Semi-Finals and Finals) to a public channel. This builds hypes and keeps players informed without requiring manual staff announcements.
>
> ### Current Behavior
> The bot scans the bracket every 5 minutes to update the admin dashboard, but it does not proactively announce specific matchups to the public.
>
> ### Proposed Behavior
> During the existing 5-minute background scan, the bot will identify active matches belonging to the Semi-Final and Final rounds. When these matches are detected for the first time, the bot will post an embedded announcement in a designated public updates channel.
>
> ### Technical Requirements
> - [ ] Add a new confi …(truncated)

Implemented in `961415c`, `7c67987`. Files: `features/config.py`, `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`

⚠️ as-implemented differs from #124: goes well beyond the filed spec — adds an unspecced winner "GGs!" announcement, hype GIF messages, custom vs/win emojis, delete-and-replace when rosters change (spec said announce once), duplicate-post guards, and a forced final announcement sync in !endtourney.

#### #126 — Bug: `!starttourney` not reseting tourney timer (Bug)

> ### Overview
> The `!starttourney` command does not reset the start timestamp if the previous session wasn't cleared by `!endtourney`. This causes the bot to calculate duration from the time of a previous test run rather than the actual start.
>
> ### Acceptance Criteria
> - [ ] Running `!starttourney` forcefully overwrites any existing `start_time` with the current timestamp.
> - [ ] `/tourney-progress` displays `0h 0m` immediately after the command is run.
>
> ### Steps to Reproduce Bug
> - [ ] Run `!starttourney` (as a test).
> - [ ] Wait 5 minutes.
> - [ ] Run `!starttourney` again without running `!endtourney` first.
> - [ ] Check `/tourney-progress`.
> - [ ] **Result**: Duration shows `0h 5m` instead of `0h …(truncated)

Implemented in `f6a6c6e`. Files: `database/mongo.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #128 — Bug: Duplicate Tourney Progress Dashboard (Bug)

> ### Overview
> When `/set-matcherino` is executed before `!starttourney`, the bot generates two separate "Live Tournament Progress" embeds. Only one of these panels correctly receives background updates, leaving the other static.
>
> ### Acceptance Criteria
> - [ ] Only one "Live Tournament Progress" panel is sent per tournament session.
> - [ ] If a dashboard message already exists in the channel, the bot should reference or update it rather than sending a second instance.
>
> ### Steps to Reproduce Bug
> - [ ] Run `/set-matcherino <ID>`.
> - [ ] Run `!starttourney`.
> - [ ] Observe that two identical progress embeds are posted to the admin channel.
> - [ ] Wait for the 5-minute refresh and observe that only o …(truncated)

Implemented in `fd877ff`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #130 — Enhancement: Spanish Sticky Support Redirection for SA Tourneys (Enhancement)

> ### Overview
> Adds localized Spanish support redirection to the sticky message loop specifically for South American (SA) tournaments.
>
> ### Current Behavior
> The sticky redirection message only displays in English, regardless of the tournament region.
>
> ### Proposed Behavior
> When the tournament is started in `SA` mode, the sticky redirection embed should automatically switch to Spanish text.
>
> ### Technical Requirements
> - [ ] Implement a check in the `on_message` logic to detect the active tournament region.
> - [ ] Define the Spanish embed content: `description=f"# ⚠️ ¡Atención!\n# Por favor, usa {support_mention} para abrir un ticket de soporte para el torneo."`.
>
> ### Acceptance Criteria
> - [ ] Ru …(truncated)

Implemented in `7ae80e9`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #132 — Enhancement: Periodic Sticky Match Info Refresh (Enhancement)

> Sub issue of Epic #66 
>
> ### Overview
> Updates the existing 1-minute refresh loop to move the Match Info embed to the bottom of the channel only when the timer triggers, ensuring it is always the most recent message.
>
> ### Current Behavior
> The Match Info embed updates in place every minute, but remains buried if players or staff chat between refresh intervals, requiring users to scroll up to find match data.
>
> ### Proposed Behavior
> During the scheduled 1-minute refresh, the bot checks if the Match Info embed is the latest message in the channel. If it is not the latest, it deletes the old message and sends a new one to the bottom. If it is already at the bottom, it performs a standard edit.
>
> ### …(truncated)

Implemented in `aeead07`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.7.3 — 2026-03-11

#### #134 — Enhancement: General Server Support Ticket System Revamp (Enhancement)

> ### Overview
> Develop an in-house, fully customizable ticket system to replace the "Ticket Tool" integration, which currently restricts support workflow due to character limits in embeds. This system is strictly for general server support and applications, operating entirely independently of the specialized tournament ticket system.
>
> ### Current Behavior
> The bot uses a third-party tool with limited visual customization and a singular, inflexible ticket creation process.
>
> ### Proposed Behavior
> Users will interact with a "Master Support" embed in the #tickets channel to select a specific category (e.g., Issues, Server Support, Staff Apps). Upon selection, the bot creates a private channel withi …(truncated)

Implemented in `d1142b2`, `15e7228`. Files: `features/support_tickets.py`, `database/mongo.py`, `features/config.py`, `features/ticket_command_router.py`, `features/tourney/tourney_commands.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The two new files (support_tickets.py, ticket_command_router.py) are the implementation itself; the router preserves the spec's isolation rule by dispatching !close/!delete/!reopen per category.


### v1.7.4 — 2026-03-14

#### #16 — Bug: Budget doesn't seem to work as intended (Bug)

> Budget is not updating when redeeming, and the commands to update the budget are also gone.

Implemented in `d6a3d22`. Files: `features/config.py`, `features/economy.py`, `features/ticket_command_router.py`

⚠️ as-implemented differs from #16: the two-line issue asked for budget updates on redeem and restored edit commands; what shipped is a full budget redesign — real monthly reset via a stored month key, budget deducted at staff fulfillment (button) rather than at redemption time, a pre-redemption budget guard, a three-option ticket close flow (reopen / refund tokens / deduct budget), /set-budget with remaining-budget semantics replacing /editspent + /editbudget, a dedicated redemption ticket category with topic metadata, and an expanded cost model that newly counts PayPal at $15 and prices Brawl Pass+/CoC/CR passes.


#### #136 — Bug: Fix ping on ticket closure message (Bug)

> ### Overview
> When a ticket is closed, the transcript message currently pings the person who closed it, which is annoying and creates unnecessary notifications. This needs to be changed to match the tourney ticket transcript format so it simply lists the username without pinging them. 
>
> ### Acceptance Criteria
> - [ ] The transcript message no longer pings the user who closed/deleted the ticket.
> - [ ] The transcript message follows the new format: `Transcript for ticket #「」[ticket-name] deleted by [username] (opener: @[user])`.
>
> ### Steps to Reproduce Bug
> - [ ] Open a new ticket.
> - [ ] Close and delete the ticket.
> - [ ] Observe the transcript log message where the user who closed it is pinged. …(truncated)

Implemented in `8bcf066`. Files: `features/support_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.


### v1.7.5 — 2026-03-21

#### #139 — Feature: Add CLAUDE.md for Claude Code project context (Feature)

> ### Overview
> Set up a `CLAUDE.md` file at the project root to give Claude Code persistent context about the Remaining7 bot's architecture, stack, and conventions every session.
>
> ### Technical Requirements
> - [ ] Create `CLAUDE.md` at the repo root
> - [ ] Include stack, folder structure, run instructions, and key system notes
> - [ ] Document coding conventions (Cogs, config.py for IDs, DB helper pattern)
>
> ### Acceptance Criteria
> - [ ] `CLAUDE.md` exists at repo root and is committed
> - [ ] Running `/init` in Claude Code confirms context is loaded
> - [ ] Claude Code gives accurate project-aware responses without extra prompting
>
> ### Notes
> Use the CLAUDE.md already drafted — just verify the folder s …(truncated)

Implemented in `0c91a26`. Files: `CLAUDE.md`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #141 — Bug: High Traffic Alert spams Tourney Admin channel (Bug)

> ### Overview
> When the ticket count hits 40+, the bot sends repeated High Traffic Alert pings to `@Tourney Admin` instead of a single notification.
>
> ### Acceptance Criteria
> - [ ] Remove the High Traffic Alert system entirely since the 50-ticket hard cap already prevents new tickets from being created
>
> ### Steps to Reproduce Bug
> - [ ] Open tickets until count reaches 40+
> - [ ] Observe repeated identical pings in Tourney Admin channel
>
> ### Impact
> Spam pings flood the admin channel, causing notification fatigue and making it hard to spot real alerts.
>
> ### Screenshots/Logs [if applicable]
> [image]
>
> ### Branch
> [code block omitted]

Implemented in `c6988e1`. Files: `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Removes the capacity-warning system that the #7 fix introduced in December 2025.

#### #143 — Bug: Matcherino tournament milestone messages deleted/missing and progress not updating (Bug)

> ### Overview
> During a live Matcherino tournament, the bot scrapes/polls the Matcherino API to post milestone updates (semi-final, final, winner) to the tournament updates channel. Multiple issues were observed: the semi-final message was posted but then deleted and never reposted, the final message was deleted before the winner message could fire, the winner was never announced, the progress tracker did not update to reflect the tournament as completed, and `!endtourney` failed to resolve the state either.
>
> ### Acceptance Criteria
> - [ ] Semi-final message is posted to the tournament updates channel and persists — it is not deleted or overwritten mid-flow
> - [ ] Final message is posted and per …(truncated)

Implemented in `3c3c580`. Files: `.claude/settings.local.json`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The commit accidentally includes a stray .claude/settings.local.json (removed again in #158).


#### #145 — Enhancement: Align daily message reset with `/daily` cooldown (Enhancement)

> ### Overview
> The 5-message requirement for `/daily` currently resets at 00:00 UTC, independent of the 24-hour cooldown timer. This enhancement aligns the two so they reset together.
>
> ### Current Behavior
> Message requirement resets at 00:00 UTC daily, while the `/daily` cooldown is a rolling 24-hour timer from last use. The two are out of sync.
>
> ### Proposed Behavior
> The message requirement counter resets in sync with the user's `/daily` cooldown — both tied to 24 hours from the user's last `/daily` use.
>
> ### Technical Requirements
> - [ ] Tie the message requirement reset to the user's `/daily` cooldown timestamp instead of 00:00 UTC
> - [ ] Ensure the message counter resets 24 hours after the u …(truncated)

Implemented in `d9b3e4d`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #147 — Enhancement: Exclude economy-commands and bot-commands from `/daily` message requirement: (Enhancement)

> ### Overview
> Messages sent in economy-commands and bot-commands should not count toward the 5-message requirement for `/daily`. Both channels will be added to the config as excluded channels.
>
> ### Current Behavior
> All messages regardless of channel count toward the `/daily` message requirement.
>
> ### Proposed Behavior
> Messages in economy-commands and bot-commands are ignored when tracking the `/daily` message requirement.
>
> ### Technical Requirements
> - [ ] Add excluded channels to config for both servers:
> [code block omitted]
> - [ ] Skip message count increment when message is sent in an excluded channel
>
> ### Acceptance Criteria
> - [ ] Messages in economy-commands and bot-commands do not count t …(truncated)

Implemented in `a52d9e4`. Files: `features/config.py`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #149 — Bug: Pre-tourney/tourney support button fails after bot restart (Bug)

> ### Overview
> When the bot restarts, the pre-tourney and tourney support buttons stop working and return "Interaction Failed". The bot needs to automatically detect which support message is active on startup and repost it so interactions remain functional.
>
> ### Acceptance Criteria
> - [ ] On startup, the bot checks the pre-tourney and tourney support channels for an existing message
> - [ ] If a message is found, the bot deletes it and reposts a fresh one so the button interaction is registered
> - [ ] The correct message is posted based on whichever channel is active
> - [ ] Users are never blocked by "Interaction Failed" after a restart
>
> ### Steps to Reproduce Bug
> - [ ] Have an active pre-tourney o …(truncated)

Implemented in `e19e355`. Files: `features/tourney/tourney_commands.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #151 — Enhancement: Bump the bot version to v1.7.5 (Enhancement)

> ### Overview
> Bump the bot version to **v1.7.5**.
>
> ### Current Behavior
> - `BOT_VERSION` in `features/config.py` is `v1.7.1`.
>
> ### Proposed Behavior
> - Set `BOT_VERSION` to `v1.7.5`.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` in `features/config.py` to `"v1.7.5"`.
>
> ### Acceptance Criteria
> - [ ] `/Help` embed title displays `🤖 R7 Bot Command Directory | v1.7.5`.
>
> ### Benefit/Impact
> Ensures the versioning remains consistent with the latest deployment.
>
> ### Branch
> [code block omitted]

Implemented in `d2dcee5`. Files: `features/config.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.8.0 — 2026-03-29

#### #154 — Bug: Tournament stage announcements skip earlier stages (Bug)

> ### Overview
> Tournament milestone messages (semi-finals, finals, winner) can post out of order or skip earlier stages entirely. For example, the finals message may post without a semi-finals message ever being sent. The bot should enforce stage ordering — before posting a later stage, it must verify the previous stage message exists and post it first if missing.
>
> ### Acceptance Criteria
> - [ ] Before posting the finals message, the bot checks if the semi-finals message has been posted — if not, it posts the semi-finals message first, then finals
> - [ ] Before posting the winner message, the bot checks if both the semi-finals and finals messages have been posted — posting any missing ones in or …(truncated)

Implemented in `e3b4922`. Files: `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #156 — Bug: Winner announcement posts consolation match winner instead of grand final winner (Bug)

> ### Overview
> The winner announcement incorrectly identifies the consolation match (3rd place) winner as the tournament winner. In the example, OverThrow won match 100 (3rd place) and was announced as the overall winner, when the actual grand final winner was power power from match 99.
>
> ### Acceptance Criteria
> - [ ] Winner announcement correctly identifies the winner of the grand final, not the consolation match
> - [ ] Consolation/3rd place match is excluded from winner detection logic
> - [ ] Correct team is posted in the updates channel as the tournament winner
>
> ### Steps to Reproduce Bug
> - [ ] Run a tournament through to completion with a consolation/3rd place match
> - [ ] Wait for the winner …(truncated)

Implemented in `1d9e533`. Files: `features/tourney/matcherino.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #158 — Enhancement: Add Claude files to .gitignore and remove from repo (Enhancement)

> ### Overview
> Adds `.claude/` and `CLAUDE.md` to `.gitignore` and removes them from git tracking so Claude Code context files are never committed to the repository.
>
> ### Current Behavior
> `.claude/` and `CLAUDE.md` are tracked and committed to the repo.
>
> ### Proposed Behavior
> Both files are untracked by git but remain on the local filesystem for Claude Code to use.
>
> ### Technical Requirements
> - [ ] Run `git rm -r --cached .claude/` to untrack the folder
> - [ ] Run `git rm --cached CLAUDE.md` to untrack the file
> - [ ] Add `.claude/` and `CLAUDE.md` to `.gitignore`
>
> ### Acceptance Criteria
> - [ ] Neither file appears in future commits or the GitHub zip download
> - [ ] Both files still exist locally …(truncated)

Implemented in `26a250f`, `b09f875`. Files: `.gitignore`, `.claude/settings.local.json`, `CLAUDE.md`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #160 — Feature: Add Ruff linting and formatting workflow (Feature)

> ### Overview
> Adds a GitHub Actions workflow that runs Ruff on every push and pull request to enforce consistent code style and catch lint errors automatically.
>
> ### Technical Requirements
> - [ ] Create `.github/workflows/lint.yml`
> - [ ] Configure Ruff to run `ruff check .` and `ruff format --check .`
> - [ ] Trigger on push to `dev`/`main` and PRs into `main`
> - [ ] Add `ruff` to `requirements.txt`
>
> ### Acceptance Criteria
> - [ ] Workflow runs automatically on push and PRs
> - [ ] Workflow fails if lint errors or formatting issues are detected
>
> ### Notes
> Ruff replaces both flake8 and black in a single tool. Run `ruff format .` locally to auto-fix formatting before pushing.
>
> ### Branch
> [code block o …(truncated)

Implemented in `3ae3678`, `1c20b3d`, `07a0a28`, `1676c30`. Files: `features/brawl/commands.py`, `features/config.py`, `features/economy.py`, `features/event.py`, `features/quests.py`, `features/security.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_utils.py`, `features/tourney/tourney_views.py`, `features/translation.py`, `main.py`, `.github/workflows/lint.yml`, `database/mongo.py`, `features/brawl/brawlers.py`, `features/brawl/drops.py`, `features/general.py`, `features/support_tickets.py`, `features/ticket_command_router.py`, `features/tourney/matcherino.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The repo-wide reformat is the issue's intent; the lint-fix commit left a few no-op statements behind (discarded values in check_budget and on_message) instead of deleting them.


#### #163 — Enhancement: Update README to reflect current project state (Enhancement)

> ### Overview
> Updates the README to accurately reflect the current feature set, structure, and setup instructions. Also standardizes environment variable naming conventions.
>
> ### Current Behavior
> README contains outdated or incomplete information that does not match the current state of the project. Environment variables use inconsistent naming (`FAKE_TOKEN`, `DISCORD_TOKEN`).
>
> ### Proposed Behavior
> README is fully up to date and serves as an accurate reference for contributors and Claude Code context. Environment variables follow a clear DEV/PROD naming convention.
>
> ### Technical Requirements
> - [ ] Update feature list to reflect all current commands and systems
> - [ ] Update project structure …(truncated)

Implemented in `b9a64ae`, `a1d448d`. Files: `.env.example`, `README.md`, `features/config.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #165 — Feature: Dynamically grant and revoke Tourney Admin timeout permission (Feature)

> ### Overview
> Automatically grants the Tourney Admin role the Timeout Members permission when `!starttourney` is run, and revokes it when `!endtourney` is run.
>
> ### Technical Requirements
> - [ ] On `!starttourney`: update Tourney Admin role to enable `timeout_members` permission
> - [ ] On `!endtourney`: update Tourney Admin role to revoke `timeout_members` permission
> - [ ] Handle edge cases where role permission update fails gracefully (log error, don't block tourney phase change)
>
> ### Acceptance Criteria
> - [ ] Tourney Admins can timeout members only while a tourney is active
> - [ ] Permission is automatically removed when `!endtourney` is run
> - [ ] Tourney phase change still completes even if p …(truncated)

Implemented in `efba931`, `e0ee61d`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #167 — Feature: Add /convert-time command to generate Discord timestamp formats (Feature)

> ### Overview
> Adds a `/convert-time` slash command that takes a user-provided date and time and returns all Discord timestamp format strings alongside their rendered previews.
>
> ### Technical Requirements
> - [ ] Create `/convert-time` slash command with three required parameters: `date` (e.g. "2026-03-27"), `time` (e.g. "8:13 PM"), and `timezone` (e.g. "America/New_York")
> - [ ] Convert input to a Unix timestamp using the provided timezone
> - [ ] Return an embed displaying all 9 Discord timestamp formats, each showing the raw string in a code block and its rendered Discord output
> - [ ] Formats to include: `F`, `f`, `D`, `d`, `t`, `T`, `R`, `s`, `S`
>
> ### Acceptance Criteria
> - [ ] Command returns a …(truncated)

Implemented in `59608bb`. Files: `features/general.py`

⚠️ as-implemented differs from #167: the spec (and later release notes) demand "all 9" formats including s/S, which don't exist in Discord — the implementation correctly ships the 7 real styles, plus an unspecced 22-alias timezone table.

#### #169 — Enhancement: Send DM to user when flagged as hacked (Enhancement)

> ### Overview
> Modifies the `/hacked` slash command and `!hacked` reply command to send a direct message to the compromised user notifying them that their account has been flagged.
>
> ### Current Behavior
> When `/hacked` or `!hacked` is run, the user is timed out and flagged in the database but receives no notification.
>
> ### Proposed Behavior
> The bot attempts to DM the flagged user informing them their account has been marked as compromised and to contact staff once they recover access.
>
> ### Technical Requirements
> - [ ] After applying timeout and DB flag, send a DM embed to the user containing:
>   - Their account has been flagged as hacked on the Remaining 7 server
>   - They have been timed out for …(truncated)

Implemented in `e5b8163`. Files: `features/security.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #171 — Feature: Identify team by name fuzzy match without match number (Feature)

> ### Overview
> Adds a fallback team lookup that searches all teams in the Matcherino bracket by name when a valid match number is not provided, using fuzzy matching to identify the correct team.
>
> ### Technical Requirements
> - [ ] On ticket creation or team lookup, if no valid match number is found, fetch and cache all teams from the Matcherino bracket
> - [ ] Cache the team list per tourney session so no redundant API calls are made (teams do not change mid-tourney)
> - [ ] Run fuzzy match using `difflib.SequenceMatcher` against all cached team names with a 0.60 similarity threshold
> - [ ] If a match is found above the threshold, auto-populate the team name on the ticket
> - [ ] If no match is found a …(truncated)

Implemented in `33d3756`. Files: `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_views.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Extends beyond spec — also auto-corrects wrong (not just missing) match numbers, rewriting the ticket topic in place at creation time and during the refresher.

#### #173 — Enhancement: Update README and help commands to reflect current state (Enhancement)

> ### Overview
> Updates the README and all in-bot help commands to accurately reflect the current feature set.
>
> ### Current Behavior
> README and help command embeds contain outdated or incomplete information that does not match the current state of the bot.
>
> ### Proposed Behavior
> README and all help commands are fully up to date and serve as accurate references for users and staff.
>
> ### Technical Requirements
> - [ ] Update README feature list and command references to match current functionality
> - [ ] Update `/help` public directory to reflect all current economy, brawler, and tourney commands
> - [ ] Update `/economy-help` to reflect budget system, daily milestone requirement, and channel exclusio …(truncated)

Implemented in `0c704e6`. Files: `README.md`, `features/economy.py`, `features/event.py`, `features/general.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #174 — Bug: Synchronous Matcherino API calls blocking the event loop in match_refresher_task (Bug)

> ### Overview
> The `match_refresher_task` makes synchronous HTTP requests via `requests_cache` inside an async task, blocking the entire event loop and preventing Discord's heartbeat from sending. This causes gateway warnings and risks bot disconnection during live tournaments.
>
> ### Acceptance Criteria
> - [ ] `fetch_ticket_context` and `find_match_by_team_name` are called via `run_in_executor` so they run off the event loop
> - [ ] No heartbeat blocked warnings appear during a live tourney with multiple active tickets
>
> ### Steps to Reproduce Bug
> - [ ] Start a tourney session with a Matcherino ID set
> - [ ] Have multiple active ticket channels open
> - [ ] Wait for the 60-second refresher to fire and …(truncated)

Implemented in `ccf0f5a`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #177 — Enhancement: Bump bot version to v1.8.0 (Enhancement)

> ### Overview
> Bump the bot version to **v1.8.0**.
>
> ### Current Behavior
> `BOT_VERSION` in `features/config.py` is `v1.7.5`.
>
> ### Proposed Behavior
> `BOT_VERSION` is set to `v1.8.0`.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` in `features/config.py` to `"v1.8.0"`
>
> ### Acceptance Criteria
> - [ ] `/help` embed displays `v1.8.0`
>
> ### Branch
> [code block omitted]

Implemented in `8857fe0`. Files: `features/config.py`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.9.0 — 2026-04-26

#### #180 — Bug: Added users retain send message permissions after ticket close (Bug)

> ### Overview
> When a tourney ticket is closed via `!close` / `!c`, users who were manually added to the ticket through `/add` still have send message access in the archived channel. Only the original ticket opener's permissions are revoked.
>
> ### Acceptance Criteria
> - [ ] All manually added users lose send message permissions when a ticket is closed
> - [ ] Original ticket opener permissions continue to be revoked as expected
>
> ### Steps to Reproduce Bug
> - [ ] Open a tourney ticket
> - [ ] Use `/add` to add a user to the ticket
> - [ ] Close the ticket with `!close`
> - [ ] Observe that the added user can still send messages in the closed ticket
>
> ### Impact
> Added users can continue chatting in closed/a …(truncated)

Implemented in `641a763`. Files: `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #182 — Enhancement: Add Portuguese translation to SA tourney sticky message (Enhancement)

> ### Overview
> The SA tourney sticky message currently only displays in Spanish. This enhancement adds a Portuguese translation to support Brazilian players participating in South American tournaments.
>
> ### Current Behavior
> The sticky message posted in `#tourney-support` during SA tournaments only shows Spanish text directing users to open a support ticket.
>
> ### Proposed Behavior
> The sticky message includes both the existing Spanish text and a Portuguese translation below it, so both language groups can understand the instructions.
>
> ### Technical Requirements
> - [ ] Add Portuguese translation of the sticky message text
> - [ ] Update the embed builder to display both languages cleanly (e.g., Span …(truncated)

Implemented in `00dcaf8`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Shipped as two stacked embeds (Spanish + Portuguese) in one message rather than one combined embed.

#### #186 — Feature: Add pytest testing framework and CI workflow (Feature)

> ### Overview                                                                                                                                                             
>                                                                                                                                                                            
>   Introduce `pytest` with `pytest-asyncio` as the project's testing foundation, along with a GitHub Actions workflow that runs tests on PRs. This gives contributors a     
>   structured way to verify behavior without a live bot and catches regressions before they merge. …(truncated)

Implemented in `1d282df`. Files: `.github/workflows/tests.yml`, `Makefile`, `pyproject.toml`, `requirements.txt`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_brawlers.py`, `tests/test_drops.py`, `tests/test_economy.py`, `tests/test_general.py`, `tests/test_matcherino.py`, `tests/test_support_tickets.py`, `tests/test_tourney_utils.py`, `tests/test_translation.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Far exceeds the "at least one sample test" spec — ~700 lines of tests across 8 modules, plus the Makefile and pinned dependency versions.

#### #188 — Enhancement: Move BOT_VERSION to pyproject.toml (Enhancement)

> ### Overview
> Centralize the bot version in `pyproject.toml` instead of `features/config.py`, since the project now has a `pyproject.toml` for test configuration.
>
> ### Current Behavior
> `BOT_VERSION` is defined as a string in `features/config.py` and referenced from there at runtime.
>
> ### Proposed Behavior
> The version is defined in `pyproject.toml` under `[project]` and read into the bot at runtime (e.g., via `importlib.metadata` or by parsing the file). `features/config.py` no longer owns the version string.
>
> ### Technical Requirements
> - [ ] Add `version` field to `pyproject.toml` under `[project]`
> - [ ] Update `features/config.py` to read version from `pyproject.toml` instead of hardcoding i …(truncated)

Implemented in `006c029`, `ee4fea8`. Files: `features/config.py`, `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The release notes say "read dynamically via tomllib", but tomllib requires Python 3.11 — a follow-up commit replaced it with regex parsing for 3.10 compatibility.

#### #196 — Bug: Previous tourney winners posted at start due to stale tourney ID (Bug)

> ### Overview
> When `!starttourney` is run, previously saved tourney winners are incorrectly posted because the tourney ID from the last tournament is still stored in the database.
>
> ### Acceptance Criteria
> - [ ] Saved tourney ID is cleared when `!starttourney` is run
> - [ ] Previous winners are not posted at the start of a new tournament
> - [ ] `!starttourney` confirmation message includes a reminder to set the new tourney ID
>
> ### Steps to Reproduce Bug
> - [ ] Complete a tournament and save winners
> - [ ] Run `!starttourney` for a new tournament without setting a new tourney ID
> - [ ] Observe previous winners being posted
>
> ### Impact
> Previous tourney winners are incorrectly displayed at the start o …(truncated)

Implemented in `8c72efd`. Files: `database/mongo.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #197 — Enhancement: Post set tourney ID confirmation publicly in channel (Enhancement)

> ### Overview
> Updates the set tourney ID command to post its confirmation response publicly in the channel instead of only to the user who ran it.
>
> ### Current Behavior
> The confirmation response after setting the tourney ID is only visible to the staff member who ran the command.
>
> ### Proposed Behavior
> The confirmation response is posted publicly in the channel so all staff can see the new tourney ID has been set.
>
> ### Technical Requirements
> - [ ] Remove ephemeral flag from the set tourney ID command response
>
> ### Acceptance Criteria
> - [ ] Confirmation message is visible to all users in the channel after the command is run
>
> ### Benefit/Impact
> Keeps all staff informed when the tourney ID has b …(truncated)

Implemented in `55d7c35`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #205 — Feature: Collect tourney round snapshots for ML training data (Feature)

> Sub issue of Epic #203 
>
> ### Overview
> Silently captures per-round snapshot data during opted-in tourneys by piggybacking on the existing 5-minute `progress_dashboard_task` poll. Data is stored in a new `tourney_snapshots` MongoDB collection and will be used to train the ML duration prediction model in Phase 2.
>
> ### Technical Requirements
> - [ ] Add `collect_data` boolean parameter to the set-matcherino-id command (defaults to False)
> - [ ] Add a reminder in `!starttourney` output prompting staff to set `collect_data` if they want data collected
> - [ ] Add `collect_data` flag reset to False in `!endtourney` logic
> - [ ] On each 5-minute `progress_dashboard_task` poll, check if `collect_data` is T …(truncated)

Implemented in `cb638f9`, `9203700`, `66513c7`. Files: `database/mongo.py`, `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`, `.gitignore`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Snapshots are written on every 5-minute poll (with null round fields between transitions) rather than only on round transitions as the AC implies; a temporary 1-minute POC loop was reverted before release.

#### #206 — Enhancement: Add `make up` command to run the bot (Enhancement)

> ### Overview
> Adds a `make up` command to the Makefile as a shorthand for running the bot locally.
>
> ### Current Behavior
> Running the bot requires manually typing `python main.py` in the terminal.
>
> ### Proposed Behavior
> `make up` starts the bot by running `python main.py`.
>
> ### Technical Requirements
> - [ ] Add `up` target to the Makefile that runs `python main.py`
>
> ### Acceptance Criteria
> - [ ] Running `make up` starts the bot successfully
>
> ### Benefit/Impact
> Saves time and keeps the local dev workflow consistent.
>
> ### Branch
> [code block omitted]

Implemented in `756a56e`. Files: `Makefile`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #211 — Feature: Config & environment setup for GitHub issue creator (Feature)

> Sub-issue of #210 
>
> ### Overview
> Adds the required environment variables and config constants to support the GitHub issue creator cog. This is the foundational setup sub-issue that all other sub-issues depend on.
>
> ### Technical Requirements
> - [ ] Add `GEMINI_TOKEN` to `.env.example` with a placeholder value and inline comment pointing to aistudio.google.com
> - [ ] Add `GITHUB_TOKEN` to `.env.example` with a placeholder value and inline comment noting it requires `repo` scope
> - [ ] Add `TICKET_CREATOR_ID` constant to `features/config.py` set to your Discord user ID
> - [ ] Add `GITHUB_REPO` constant to `features/config.py` (e.g. `"RemainingDelta/Remaining7-Discord-Bot"`) for the target repo
>
> ### …(truncated)

Implemented in `3c448b0`, `86832a3`. Files: `features/config.py`, `.env.example`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #213 — Feature: Cog scaffold and mention listener for GitHub issue creator (Feature)

> Sub-issue of #210 
>
> ### Overview
> Creates the `github_tickets.py` cog and implements the `on_message` listener that detects @mentions of the bot and extracts the raw message text to pass downstream to Gemini.
>
> ### Technical Requirements
> - [ ] Create `features/github_tickets.py` as a new cog and register it in `main.py`
> - [ ] Implement `on_message` listener that fires only when the bot is @mentioned
> - [ ] Strip the mention from the message and extract the remaining raw text
> - [ ] If the message is just a mention with no content, reply with a usage hint and exit early
> - [ ] Pass the raw text to the Gemini integration (stubbed for now) once extracted
>
> ### Acceptance Criteria
> - [ ] Cog loads with …(truncated)

Implemented in `285bd2a`, `c44683c`. Files: `features/github_tickets.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The second commit on the branch also lands the full Gemini prompt/template integration.

#### #217 — Feature: GitHub Issues API integration (Feature)

> Sub-issue #210 
>
> ### Overview
> Takes the structured JSON output from Gemini and creates a real GitHub Issue via the GitHub REST API. Returns the created issue's URL and number to the caller for use in the Discord reply.
>
> ### Technical Requirements
> - [ ] Build an async function `create_github_issue(title: str, body: str) -> dict` that POSTs to `https://api.github.com/repos/{GITHUB_REPO}/issues`
> - [ ] Authenticate using `GITHUB_TOKEN` from `.env` via the `Authorization: Bearer` header
> - [ ] Pass `title` and `body` from the Gemini output as the request payload
> - [ ] Parse the response and return the issue `number` and `html_url`
> - [ ] Raise a descriptive exception on non-201 status for the error …(truncated)

Implemented in `e1cd9de`. Files: `features/github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Adds an unspecced PATCH step that renumbers the issue's Branch field after creation, plus title/body normalization fixes.


#### #222 — Feature: Access control for GitHub issue creator (Feature)

> Sub-issue of #210
>
> ### Overview
> Gates the entire GitHub issue creation flow behind a single authorized Discord user ID, silently ignoring any @mention from anyone else.
>
> ### Technical Requirements
> - [ ] Import `TICKET_CREATOR_ID` from `features/config.py`
> - [ ] At the top of `on_message`, after the mention check, compare `message.author.id` against `TICKET_CREATOR_ID`
> - [ ] If the author is not authorized, return silently — no reply, no action
>
> ### Acceptance Criteria
> - [ ] Only the authorized user can trigger issue creation
> - [ ] Unauthorized @mentions produce no response from the bot whatsoever
> - [ ] Authorized user flow is completely unaffected
>
> ### Notes
> Fail silently for unauthorized us …(truncated)

Implemented in `438d3d2`. Files: `features/github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #225 — Feature: Confirmation UI before GitHub issue creation (Feature)

> Sub-issue of #225
>
> ### Overview
> Adds a yes/no confirmation step before any API calls are made. When the bot is @mentioned, it prompts the user for confirmation before triggering Gemini or GitHub.
>
> ### Technical Requirements
> - [ ] After the access control check in `on_message`, reply with "Create a GitHub issue?" and two buttons: "Yes" and "No"
> - [ ] Store the raw message text to pass to Gemini on confirmation
> - [ ] On "Yes": edit the message to "Creating GitHub issue..." then proceed to call `call_gemini` and `create_github_issue` (implemented in prior sub-issues)
> - [ ] On "No": edit the message to "Cancelled."
> - [ ] Use `discord.ui.View` with two `discord.ui.Button` components for the yes/n …(truncated)

Implemented in `250d5a9`. Files: `features/github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #231 — Bug: Bot fails to ping user when replying to ticket creation message (Bug)

> Sub-issue of #210
>
> ### Overview
> The bot replies to a user's message after a ticket is created, but it does not include a user ping in its reply, which is an unintended omission.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] The bot's reply to a ticket creation message successfully pings the original user.
> - [ ] The user receives a notification for the bot's reply.
>
> ### Steps to Reproduce Bug
> - [ ] Send a message to the bot to initiate ticket creation.
> - [ ] Observe the bot's reply confirming the ticket creation.
> - [ ] Verify that the bot's reply does not contain a ping/mention of the user who sent the original message.
>
> ### Impact
> Users may not immediately notice the bot's confirm …(truncated)

Implemented in `3a89790`. Files: `features/github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #233 — Feature: Add pytest tests for GitHub issue creator cog (Feature)

> Sub-issue of #210 
>
> Feature: Add pytest tests for GitHub issue creator cog
>
> ### Overview
> Adds a pytest test suite covering the core logic of the GitHub issue creator cog — Gemini integration, GitHub API integration, and the mention listener — to ensure reliability and catch regressions.
>
> ### Technical Requirements
> - [ ] Add `pytest` and `pytest-asyncio` to `requirements.txt` if not already present
> - [ ] Create `tests/test_github_tickets.py`
> - [ ] Mock `aiohttp.ClientSession` to test `call_gemini` without hitting the real Gemini API:
>   - Returns valid JSON with `type`, `title`, `body`
>   - Raises `RuntimeError` on non-200 status
>   - Raises `RuntimeError` on malformed/missing JSON keys
> - [ ] Mo …(truncated)

Implemented in `e2b091f`. Files: `tests/test_github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #237 — Enhancement: Bump bot version to v1.9.0 (Enhancement)

> ### Overview
> This enhancement updates the bot's version number in the project configuration to reflect a new development cycle or release. It modifies the existing version tracking mechanism.
>
> ### Current Behavior
> The `pyproject.toml` file currently specifies the bot version as `v1.8.0`.
>
> ### Proposed Behavior
> The bot version in `pyproject.toml` should be updated to `v1.9.0`.
>
> ### Technical Requirements
> - [ ] Update `version` field in `pyproject.toml` to `1.9.0`
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file reflects `version = "1.9.0"`
> - [ ] CI/CD pipelines (if any) correctly pick up the new version
>
> ### Benefit/Impact
> This improvement ensures the project's version number accurate …(truncated)

Implemented in `9652145`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #241 — Bug: Confirmation prompt re-disables buttons after a choice is made (Bug)

> ### Overview
> After pressing Yes or No on a confirmation prompt, the message incorrectly updates again 60 seconds later — overlaying disabled buttons on top of the already-completed result.
>
> ### Acceptance Criteria
> - [ ] Pressing Yes or No prevents any further edits to the confirmation message
> - [ ] Completed result is not overwritten after a button is pressed
>
> ### Steps to Reproduce Bug
> - [ ] Trigger any command that shows a Yes/No confirmation prompt
> - [ ] Press either button before the timeout
> - [ ] Wait 60 seconds and observe the message being edited again
>
> ### Impact
> Confirmation message appears broken after every successful interaction — the completed result gets overwritten with a disa …(truncated)

Implemented in `4050201`. Files: `features/github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.


### v1.9.1 — 2026-05-21

#### #190 — Enhancement: Improve `/hackedlist` display with pagination and better formatting (Enhancement)

> ### Overview
> Improves the `/hackedlist` command by adding pagination and cleaning up the visual layout of each entry.
>
> ### Current Behavior
> The hacked list renders all entries in a single embed with bullet points and no clear separation between users, making it hard to read when the list grows.
>
> ### Proposed Behavior
> - Entries are paginated (e.g. 5–10 per page) with navigation buttons
> - Bullet points are removed from each entry
> - Clear visual separation between each user (e.g. dividers or spacing)
>
> ### Technical Requirements
> - [ ] Implement paginated embed view with Previous/Next buttons
> - [ ] Remove bullet point formatting from entry display
> - [ ] Add consistent spacing or divider between e …(truncated)

Implemented in `f1c7eb4`. Files: `database/mongo.py`, `features/security.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Also lifts the DB fetch cap from 100 hacked users to unlimited.


#### #191 — Enhancement: Limit hacked message purge to last 12 hours instead of 7 days (Enhancement)

> ### Overview
> Updates the `/hacked` message purge to only delete messages from the last hour rather than the last 7 days.
>
> ### Current Behavior
> When `/hacked` is triggered, the automated purge deletes messages going back 7 days across all channels.
>
> ### Proposed Behavior
> The purge only deletes messages sent within the last 12 hours, leaving older message history intact.
>
> ### Technical Requirements
> - [ ] Update the message purge logic to filter messages to the last 12 hours only
>
> ### Acceptance Criteria
> - [ ] Message purge only deletes messages sent within the last 12 hours
> - [ ] 7 day timeout on the user remains unchanged
>
> ### Benefit/Impact
> Preserves legitimate message history while still cl …(truncated)

Implemented in `6268fe9`, `c029716`. Files: `features/security.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The issue text is self-contradictory (overview says 1 hour, proposal says 12) and the commits mirror that — first 1h, then 12h final. The fix also silently removes the days_to_clean parameter from /hacked, making the window fixed.

#### #192 — Enhancement: Apply slow mode to general channel during tournaments (Enhancement)

> ### Overview
> Automatically applies a 60 second slow mode to the general channel when a tournament starts and removes it when the tournament ends.
>
> ### Current Behavior
> `!starttourney` and `!endtourney` do not modify slow mode on the general channel.
>
> ### Proposed Behavior
> - `!starttourney` applies a 60 second slow mode to the general channel
> - `!endtourney` removes slow mode from the general channel
>
> ### Technical Requirements
> - [ ] Add slow mode (60s) to general channel in `!starttourney` logic
> - [ ] Remove slow mode from general channel in `!endtourney` logic
>
> ### Acceptance Criteria
> - [ ] General channel has 60 second slow mode active after `!starttourney` is run
> - [ ] Slow mode is remove …(truncated)

Implemented in `325aed0`, `f370ee1`, `fca0206`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #194 — Enhancement: Rename admin role automatically during tournaments (Enhancement)

> ### Overview
> Automatically renames the designated admin role when a tournament starts and restores the original name when it ends.
>
> ### Current Behavior
> `!starttourney` and `!endtourney` do not modify the admin role name.
>
> ### Proposed Behavior
> - `!starttourney` renames the admin role to `[NOT TOURNEY ADMIN] Admin`
> - `!endtourney` restores the admin role to its original name
>
> ### Technical Requirements
> - [ ] Rename admin role to `[NOT TOURNEY ADMIN] Admin` in `!starttourney` logic
> - [ ] Restore original admin role name in `!endtourney` logic
>
> ### Acceptance Criteria
> - [ ] Admin role is renamed to `[NOT TOURNEY ADMIN] Admin` when `!starttourney` is run
> - [ ] Admin role name is restored when ` …(truncated)

Implemented in `ace024d`, `5c65884`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The original role name is held in memory only — a restart between start and end falls back to restoring the literal name "Admin".

#### #195 — Enhancement: Show item price and before/after balance in redemption ticket (Enhancement)

> ### Overview
> Updates the `/redeem` command to include the item's price and the user's token balance before and after the redemption in the created ticket.
>
> ### Current Behavior
> The ticket created by `/redeem` does not display the item cost or the user's token balance.
>
> ### Proposed Behavior
> The generated ticket includes:
> - The price of the item being redeemed
> - The user's token balance before the redemption
> - The user's token balance after the redemption
>
> ### Technical Requirements
> - [ ] Fetch item price and include it in the ticket embed
> - [ ] Fetch user's current balance and calculate post-redemption balance
> - [ ] Display before/after balance in the ticket embed
>
> ### Acceptance Criteria
> - …(truncated)

Implemented in `f6df726`, `62018c0`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #238 — Feature: Add CI check for version bump on PRs to main (Feature)

> ### Overview
> This sub-issue adds a GitHub Actions workflow that runs on every PR targeting `main` and fails if the `version` in `pyproject.toml` has not been bumped relative to `main`. This ensures version consistency.
>
> ### Technical Requirements
>
> - [ ] Create `.github/workflows/version-check.yml` triggered on `pull_request` to `main`
> - [ ] Extract `version` from `pyproject.toml` on both the PR branch and `main` using `grep`
> - [ ] Fail the workflow with a clear message if both versions match
> - [ ] Add the workflow as a required status check in branch protection rules
>
> ### Acceptance Criteria
>
> - [ ] PRs to `main` with no version bump are blocked from merging
> - [ ] PRs to `main` with a bumped …(truncated)

Implemented in `8e0f2bd`. Files: `.github/workflows/version-check.yml`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #250 — Feature: Add MIT License file to project root (Feature)

> ### Overview
>
> This feature adds an MIT License file to the root directory of the project, clearly defining the terms under which the software can be used and distributed. This is a foundational step for open-sourcing the project.
>
> ### Technical Requirements
>
> - [ ] Create a `LICENSE` file in the root directory.
> - [ ] Populate the `LICENSE` file with the standard MIT License text, including current year and copyright holder.
>
> ### Acceptance Criteria
>
> - [ ] A file named `LICENSE` exists in the project's root directory.
> - [ ] The `LICENSE` file contains the full MIT License text.
> - [ ] The copyright year and holder in the `LICENSE` file are accurate.
>
> ### Notes
>
> N/A
>
> ### Branch
> [code block omitt …(truncated)

Implemented in `c82a529`. Files: `LICENSE`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #254 — Enhancement: Bump bot version to v1.10.0 (Enhancement)

> ### Overview
> This enhancement updates the bot's version number in the project configuration to reflect a new development cycle or release. It modifies the existing version tracking mechanism.
>
> ### Current Behavior
> The `pyproject.toml` file currently specifies the bot version as `v1.9.0`.
>
> ### Proposed Behavior
> The bot version in `pyproject.toml` should be updated to `v1.10.0`.
>
> ### Technical Requirements
> - [ ] Update `version` field in `pyproject.toml` to `1.10.0`
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file reflects `version = "1.10.0"`
> - [ ] CI/CD pipelines (if any) correctly pick up the new version
>
> ### Benefit/Impact
> This improvement ensures the project's version number accur …(truncated)

Implemented in `17ac244`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: This bump to v1.10.0 was reversed days later by #274 when the release was rescoped as patch v1.9.1.

#### #257 — Enhancement: Exclude 'BOTS' category channels from token rewards (Enhancement)

> ### Overview
> This enhancement aims to refine the token reward system by preventing token accrual from messages posted in channels designated for other bots, specifically those within the 'BOTS' category.
>
> ### Current Behavior
> Currently, the bot awards tokens for all messages, including automated responses or spam from other Discord bots (e.g., owo bot) in channels within categories like 'BOTS'.
>
> ### Proposed Behavior
> The bot should identify messages sent in channels that belong to a category named 'BOTS' and actively exclude them from the token reward calculation, thus not awarding any tokens for such messages.
>
> ### Technical Requirements
> - [ ] Implement logic to check the category of a mess …(truncated)

Implemented in `d19bc95`. Files: `features/config.py`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Implemented via a BOTS_CATEGORY_ID config constant rather than the specced case-insensitive category-name match; the specced "logging reflects ignored messages" was not implemented.

#### #258 — Bug: `!hacked` command triggers with additional text (Bug)

> ### Overview
> The `!hacked` command currently triggers even when additional text follows it, leading to unintentional command execution.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] The `!hacked` command only initiates when it is the sole content after the prefix, or followed only by whitespace.
> - [ ] The `!hacked` command does not initiate when any non-whitespace text follows it.
>
> ### Steps to Reproduce Bug
> - [ ] Type `!hacked is a command we have` in a Discord channel.
> - [ ] Observe that the bot initiates the `!hacked` protocol.
>
> ### Impact
> Users can accidentally trigger the `!hacked` command by including `!hacked` within a longer message, leading to unintended actions or confus …(truncated)

Implemented in `5ad7f37`. Files: `features/security.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #260 — Feature: PR consistency validation workflow on dev (Feature)

> ### Overview
>
> Add a GitHub Actions workflow that fires on PRs into `dev` and verifies the branch name, PR title, and PR body all reference the same issue number.
>
> ### Technical Requirements
>
> - [ ] Trigger on `pull_request` targeting `dev` for types: `opened`, `edited`, `synchronize`, `reopened`
> - [ ] Extract leading issue number from branch name (e.g. `258-Bug` → `258`), fail if none found
> - [ ] Assert PR body contains `Closes #<issue_num>` (case-insensitive)
> - [ ] Assert PR title references `<issue_num>` as a whole word
>
> ### Acceptance Criteria
>
> - [ ] Workflow fails with a clear message if branch has no leading issue number
> - [ ] Workflow fails if PR body is missing the matching `Closes #<n …(truncated)

Implemented in `3888d60`. Files: `.github/workflows/pr-issue-reference-check.yml`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #269 — Enhancement: Increase token gain for Nitro Boosters (Enhancement)

> ### Overview
> This enhancement aims to increase the average token gain for users who boost the Discord server, making server boosting more rewarding.
>
> ### Current Behavior
> Users who boost the server currently receive an average of a 2% increase in token gain.
>
> ### Proposed Behavior
> Increase the average token gain for server boosters from the current 2% to 5%.
>
> ### Technical Requirements
> - [ ] Adjust the token calculation logic to reflect the new percentage for server boosters.
>
> ### Acceptance Criteria
> - [ ] Nitro users boosting the server receive an average 5% increase in token gain.
> - [ ] Non-boosting users' token gain remains unchanged.
>
> ### Benefit/Impact
> This improvement will make server …(truncated)

Implemented in `b002695`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #274 — Enhancement: Bump version to v1.9.1 (Enhancement)

> ### Overview                                                                                                                                                                 
>                                                                                                                                                                            
> - Updates the bot version from the incorrectly bumped v1.10.0 back down to v1.9.1, reflecting that the current release is a patch rather than a minor version bump.      
>                                                                                                                                                                          
> ### Current Be …(truncated)

Implemented in `8cf5625`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.9.2 — 2026-05-29

#### #280 — Bug: Bot/economy command channel messages incorrectly earn tokens (Bug)

> ### Overview
> Messages sent in `BOT_COMMANDS_CHANNEL_ID` and `ECONOMY_COMMANDS_CHANNEL_ID` are excluded from the daily message count tracker but still trigger passive token rewards. These channels should not grant tokens for chatting.
>
> ### Acceptance Criteria
> - [ ] Messages in `BOT_COMMANDS_CHANNEL_ID` do not earn passive tokens or XP
> - [ ] Messages in `ECONOMY_COMMANDS_CHANNEL_ID` do not earn passive tokens or XP
> - [ ] Messages in all other eligible channels are unaffected
>
> ### Steps to Reproduce Bug
> - [ ] Send a message in the bot commands or economy commands channel
> - [ ] Check balance — tokens have been awarded
>
> ### Impact
> Users can farm passive tokens by chatting in bot command channels, …(truncated)

Implemented in `e993aec`. Files: `features/config.py`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #282 — Enhancement: Bump version to v1.9.2 (Enhancement)

> ### Overview
> Update `BOT_VERSION` in `pyproject.toml` from `1.9.1` to `1.9.2`.
>
> ### Current Behavior
> `BOT_VERSION` is set to `1.9.1` in `pyproject.toml`.
>
> ### Proposed Behavior
> `BOT_VERSION` is set to `1.9.2` in `pyproject.toml`.
>
> ### Technical Requirements
> - [ ] Update `BOT_VERSION` to `1.9.2` in `pyproject.toml`
>
> ### Acceptance Criteria
> - [ ] `BOT_VERSION` reads `1.9.2`
>
> ### Benefit/Impact
> Keeps the version in sync with the upcoming release tag.
>
> ### Branch
> [code block omitted]

Implemented in `9a707a5`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.10.0 — 2026-06-21

#### #184 — Bug: Quest token rewards do not scale correctly across all quests (Bug)

> ### Overview
> Quest token rewards are not properly scaled relative to each other. The 80 message quest awards 50 tokens, but the higher target quests do not award proportionally more, leaving users under-rewarded for completing harder quests.
>
> ### Acceptance Criteria
> - [ ] All quest token rewards are reviewed and updated to scale proportionally with their target count
> - [ ] 80 message quest reward remains the baseline at 50 tokens
>
> ### Steps to Reproduce Bug
> - [ ] Complete each of the 3 quests and note the tokens rewarded
> - [ ] Observe that higher target quests do not award proportionally more tokens than the 80 message quest
>
> ### Impact
> Users are under-rewarded for completing harder quests, …(truncated)

Implemented in `78da21b`. Files: `database/mongo.py`, `features/quests.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: XP rewards were also rebalanced though the issue only covered tokens, and init_default_quests changed from seed-once to upsert-on-every-startup so reward edits actually deploy.


#### #198 — Bug: Matches with TBD/BYE opponents silently skipped in match history (Bug)

> ### Overview
> Match history skips any match where one or both teams are TBD or BYE. Instead, these matches should display which prerequisite match the slot is waiting on using the `entrantSources` field already returned by the Matcherino API.
>
> ### Current Behavior
> The match history loop in `matcherino.py` (lines 349, 356, 364, 371) explicitly filters out TBD and BYE entries, causing incomplete matchups to disappear from history entirely.
>
> ### Proposed Behavior
> When a team slot is TBD or BYE, the match still appears in history with the opponent slot displaying "Waiting on Match #X" using the `matchNum` from `entrantSources`.
>
> ### Technical Requirements
> - [ ] Parse `entrantSources` from the raw …(truncated)

Implemented in `e1aa714`, `962dd5b`, `e1eddbe`. Files: `features/tourney/matcherino.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #199 — Enhancement: Include translation output in ticket transcripts (Enhancement)

> ### Overview
> Updates the transcript system to capture translations from `!t` and `/translate` so both the original message and its English translation appear in the transcript.
>
> ### Current Behavior
> The transcript system only captures `msg.content` (plain text). Since `!t` and `/translate` post their output as embeds with no text content, translations are completely invisible in transcripts. When staff translate a player's message during a ticket, there is no record of what was said.
>
> ### Proposed Behavior
> When `!t` is used as a reply, the transcript includes both the original message and the translated output inline, e.g.:
> [code block omitted]
>
> ### Technical Requirements
> - [ ] Update transc …(truncated)

Implemented in `71c012b`. Files: `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #200 — Feature: Add megabox opening quest (Feature)

> ### Overview
> Adds a new quest type that tracks how many Mega Boxes a user opens, hooking into the existing quest system alongside the current message-counting quests.
>
> ### Technical Requirements
> - [ ] Add new quest definition(s) to `DEFAULT_QUESTS` in `features/quests.py` (e.g. "Open 3 Mega Boxes today.") with appropriate token and XP rewards
> - [ ] Clear or manually insert into the quests collection on deploy since `init_default_quests()` only seeds when the collection is empty
> - [ ] Call `process_quest_update(user_id, channel, "megabox")` from the megabox command in `features/brawl/commands.py` after a box is opened
> - [ ] Add `"megabox"` action type handling to the filter logic in `quests.p …(truncated)

Implemented in `41af5c3`. Files: `database/mongo.py`, `features/brawl/commands.py`, `features/quests.py`

⚠️ as-implemented differs from #200: the issue's Notes explicitly said to keep the description-substring matching pattern "for consistency"; the implementation instead introduced a proper quest_category schema field and a four-slot quest model (daily/weekly × message/megabox), eliminating the fragile matching entirely — plus an unspecced /reset-quests admin command.

#### #201 — Feature: Save transcript for R7 token reward redemptions (Feature)

> ### Overview
> Adds transcript generation to the redemption ticket close flow, creating a persistent record of each redemption including token details and full message history.
>
> ### Technical Requirements
> - [ ] Hook transcript generation into the redemption ticket close flow
> - [ ] Include item name, token cost, and before/after balance in the transcript header
> - [ ] Save transcript to the designated redemption transcript channel
> - [ ] Add `REDEMPTION_TRANSCRIPT_CHANNEL_ID` to `features/config.py`
>
> ### Acceptance Criteria
> - [ ] A transcript is saved every time a redemption ticket is closed
> - [ ] Transcript includes item name, cost, and before/after token balance
> - [ ] Full message history of th …(truncated)

Implemented in `450409a`. Files: `features/config.py`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #202 — Bug: Bracket progress rounds off by one due   to BYE-inflated round numbers (Bug)

> ### Overview
> The bracket progress embed displays round numbers that are consistently off — e.g. "Round 2" where the Matcherino site shows  "Round 1" — but only in some tournaments.
>
> ### Steps to Reproduce Bug
> - [ ] Run a tournament where the participant count is ≤ half the bracket size (e.g. 79 teams in a 256-slot bracket)
> - [ ] Check the bracket progress embed and observe all round labels are shifted up by one (or more)
>
> ### Impact
> Staff see incorrect round numbers in the bracket progress embed — dominant round, bottleneck labels, and rounds remaining are all off. This makes it harder to accurately track tournament progress.
>
> ### Notes
> When Matcherino assigns a first-round BYE to every team …(truncated)

Implemented in `943ca01`. Files: `features/tourney/matcherino.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The issue's own AC ("source max_round from totalRounds") was deliberately not implemented — the issue's Notes section corrects it as wrong, and the round-normalization approach from the Notes is what shipped.

#### #220 — Feature: Implement a new counting game feature with specific rules and admin controls (Feature)

> ### Overview
> This sub-issue aims to introduce a new 'counting game' feature to the bot, allowing users to count sequentially in a designated channel. It will replace the functionality of an existing external counting bot, providing an engaging community activity and contributing to a more self-contained bot solution.
>
> ### Technical Requirements
> - [ ] Implement message listener to track counting in a designated channel.
> - [ ] Logic to detect and delete consecutive messages from the same user.
> - [ ] Logic to validate if the message content is the correct next number in the sequence.
> - [ ] Implement a `/set-count` command accessible only by moderators and admins.
> - [ ] Add configuration option …(truncated)

Implemented in `3a3de48`. Files: `database/mongo.py`, `features/config.py`, `features/counting.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Rule-violation feedback is a 5-second self-deleting channel message rather than the suggested ephemeral reply; the count does not reset on wrong numbers (the wrong message is deleted instead).


#### #251 — Enhancement: Include initiator in 'User Flagged as Hacked' message (Enhancement)

> ### Overview
> This enhancement aims to improve the 'User Flagged as Hacked' message by adding information about the moderator who initiated the hacked protocol, modifying an existing notification feature.
>
> ### Current Behavior
> The 'User Flagged as Hacked' message, displayed in both the activation channel and the moderator log channel, currently indicates that a user was flagged but does not specify which moderator initiated the protocol.
>
> ### Proposed Behavior
> Modify the 'User Flagged as Hacked' message to include the name or ID of the user who initiated the hacked protocol command. This information should be appended to the existing message in both the original channel and the moderator log …(truncated)

Implemented in `38292ff`. Files: `features/security.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #265 — Enhancement: Enhance 'User Flagged as Hacked' message with response time (Enhancement)

> ### Overview
> This enhancement updates the existing "User Flagged as Hacked" message to include a calculated duration, providing insight into staff response times for flagged users.
>
> ### Current Behavior
> The "User Flagged as Hacked" message is displayed without any information regarding the time elapsed between the user's first message and the `!hacked` command.
>
> ### Proposed Behavior
> The "User Flagged as Hacked" message should be updated to include the time difference between the first message sent by the user who was flagged as hacked and the execution of the `!hacked` command. This duration should be clearly displayed within the message.
>
> ### Technical Requirements
> - [ ] Implement logic to …(truncated)

Implemented in `a4d1036`. Files: `features/security.py`

⚠️ as-implemented differs from #265: "response time" is measured from the earliest message among those purged (12-hour window) — not from the user's actual first message as specced — and formatted HH:MM rather than "X minutes Y seconds"; it shows N/A when nothing was purged.

#### #277 — Feature: Add /version command (Feature)

> ### Overview
>
> This issue implements a new `/version` command that allows users to query the bot's current version, contributing to user information accessibility.
>
> ### Technical Requirements
>
> - [ ] Implement new `/version` slash command.
> - [ ] Command logic to retrieve and display the bot's current version.
>
> ### Acceptance Criteria
>
> - [ ] The `/version` command is registered and accessible to users.
> - [ ] Executing `/version` displays the bot's current version number in a clear message.
>
> ### Notes
>
> This command should be straightforward and provide a simple text response.
>
> ### Branch
> [code block omitted]

Implemented in `1d687a8`. Files: `features/general.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #278 — Enhancement: Restrict tourney commands to admin channel (Enhancement)

> ### Overview
> This enhancement aims to improve the security and control of tournament management by restricting the `!starttourney` and `!endtourney` commands to a designated administration channel.
>
> ### Current Behavior
> Currently, the `!starttourney` and `!endtourney` commands can be executed in any channel where the bot has permissions, potentially leading to misuse or accidental activation/deactivation of tournaments.
>
> ### Proposed Behavior
> The proposed behavior is to modify the bot's command handler such that `!starttourney` and `!endtourney` can only be successfully executed within a pre-configured "tourney admin channel". If an attempt is made to run these commands outside of this speci …(truncated)

Implemented in `62b8ace`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #279 — Bug: Quests bypass channel restrictions (Bug)

> ### Overview
> Channel restrictions for not counting R7 tokens are currently only applied to R7 tokens. Quests do not respect these channel restrictions, leading to inconsistent behavior where quests can progress in channels that should be excluded.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] Quests do not count or progress in channels that are restricted for R7 token accumulation.
> - [ ] All existing channel restrictions and associated rules for R7 tokens are consistently applied to quests.
>
> ### Steps to Reproduce Bug
> - [ ] Configure channel restrictions to prevent R7 token accumulation in a specific channel.
> - [ ] Initiate or progress a quest within the aforementioned restricted …(truncated)

Implemented in `063b68f`. Files: `features/quests.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #285 — Enhancement: Include budget reset date in /check-budget embed (Enhancement)

> ### Overview
> This enhancement modifies the existing `/check-budget` command to display the budget reset date within its embed, providing users with crucial information.
>
> ### Current Behavior
> The `/check-budget` command currently displays budget information but does not indicate when the budget period will reset.
>
> ### Proposed Behavior
> The `/check-budget` command embed should include a field or description line that clearly states the date the user's budget will reset.
>
> ### Technical Requirements
> - [ ] Modify the `/check-budget` command's embed generation logic.
> - [ ] Retrieve and format the next budget reset date.
> - [ ] Add a new field or update an existing description in the embed to displa …(truncated)

Implemented in `0e1a15a`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #292 — Enhancement: Update README and Help Commands (Enhancement)

> ### Overview
> This improvement updates the bot's documentation in the README file and ensures all help commands reflect the current features and usage, modifying the existing documentation and help system.
>
> ### Current Behavior
> The `README.md` file and potentially some help commands may contain outdated information or not fully reflect the current state of the bot's features and commands.
>
> ### Proposed Behavior
> The `README.md` file should be updated to accurately describe the bot's functionality, installation, and usage. All in-bot help commands (e.g., `!help`, `!command help`) should also be reviewed and updated to provide correct and current information to users.
>
> ### Technical Requirements …(truncated)

Implemented in `9106e15`. Files: `README.md`, `features/general.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The README blurb it adds misdescribes the GitHub issue creator as working "from ticket conversations" when it is actually mention-triggered.


#### #294 — Feature: /poll-rewards command for distributing tokens to correct poll predictors (Feature)

> ### Overview
> Add a `/poll-rewards` command that fetches voters for a specified answer on a Discord native poll and distributes a set token amount to each correct voter.
>
> ### Technical Requirements
> - [ ] Register slash command `/poll-rewards` with parameters in order: `message_id` (str), `amount` (int), `answer` (str)
> - [ ] Restrict command to Admin role only
> - [ ] Fetch the target message by ID and validate it contains an active or finalized poll
> - [ ] Match the `answer` parameter (case-insensitive) against poll answer text to resolve the correct answer ID; return an error if no match is found
> - [ ] Paginate through all voters for the resolved answer ID using `get_answer_voters`
> - [ ] Use `$ …(truncated)

Implemented in `538b1fa`. Files: `database/mongo.py`, `features/config.py`, `features/event.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Parameter order shipped as (message_id, answer, amount) vs the specced (message_id, amount, answer); adds unspecced guards — polls-channel and event-staff-channel restrictions, a finalized-poll requirement, and a confirm-before-payout view.

#### #296 — Bug: User mention in /redeem embed does not ping (Bug)

> ### Overview
> The `/redeem` command currently includes a user mention within the embed message when an item is redeemed from the R7 shop. However, this mention does not actually ping the user, leading to confusion as to where they need to go after running the command.
>
> ### Acceptance Criteria
> - [ ] The user who redeems an item is successfully pinged in the created channel.
> - [ ] The ping is a direct mention that notifies the user.
>
> ### Steps to Reproduce Bug
> - [ ] A user runs the `/redeem` command for an item from the R7 shop.
> - [ ] A new channel is created for the redemption.
> - [ ] An embed message is sent in the new channel, containing a mention of the redeeming user.
> - [ ] Observe that the …(truncated)

Implemented in `9b03eab`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #297 — Feature: Implement a new command to make messages sticky in a channel (Feature)

> ### Overview
> This sub-issue focuses on implementing the core functionality for sticky messages, allowing channel administrators to designate a message that the bot will repost at the bottom of the channel after every new message. This enhances channel organization by ensuring important information remains visible.
>
> ### Technical Requirements
> - [ ] Implement `!sticky` command, callable by replying to a message.
> - [ ] Store the content (text and attachment data) of the designated sticky message per channel.
> - [ ] Implement a listener to detect new messages posted in a channel.
> - [ ] Upon a new message, delete the previously posted sticky message and repost the current sticky message at the bot …(truncated)

Implemented in `12a16d3`. Files: `database/mongo.py`, `features/sticky.py`, `main.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Adds a 1.5-second debounce to keep repost churn down in active channels.


#### #298 — Bug: !hacked command fails to delete messages if the user has left the server (Bug)

> ### Overview
> The !hacked command is intended to delete a user's messages from the last 12 hours. Currently, if the target user has left the Discord server, the command fails entirely, reporting that the user is no longer in the server, and no messages are deleted.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] The !hacked command successfully deletes messages from the last 12 hours for a user who has left the server.
> - [ ] The bot provides appropriate feedback to the user after executing the command for a departed user.
>
> ### Steps to Reproduce Bug
> - [ ] A user sends messages in the server.
> - [ ] The user then leaves the server.
> - [ ] An administrator attempts to use the !hacked <de …(truncated)

Implemented in `0920f05`. Files: `features/security.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #299 — Bug: Redemption Ticket Embed: Balances display excessive decimal points (Bug)

> ### Overview
> The new redemption ticket channel embed currently displays `Balance Before` and `Balance After` with additional, unrounded decimal points, which negatively impacts its visual presentation.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] Balances shown under `Balance Before` in the redemption ticket embed are rounded appropriately (e.g., to 2 decimal places).
> - [ ] Balances shown under `Balance After` in the redemption ticket embed are rounded appropriately (e.g., to 2 decimal places).
> - [ ] The redemption ticket embed presents a clean and professional display of balance information.
>
> ### Steps to Reproduce Bug
> - [ ] Trigger a redemption event that generates a new redemp …(truncated)

Implemented in `043c4d0`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #300 — Bug: Bot fails to inform user about AI API errors during GitHub issue creation (Bug)

> ### Overview
> When attempting to create a GitHub issue via the AI + GitHub integration, the bot can get stuck on a 'Creating GitHub issue...' message without notifying the user if the underlying AI API call fails. This leaves the user unaware of the problem and the current state.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] User is notified with an appropriate error message if the AI API call fails.
> - [ ] The bot's status message updates to reflect the failure instead of remaining 'Creating GitHub issue...'.
> - [ ] The error message includes information about the nature of the failure (e.g., API unavailable, try again later).
>
> ### Steps to Reproduce Bug
> - [ ] Initiate the GitHub is …(truncated)

Implemented in `1d01484`. Files: `features/github_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #301 — Enhancement: Token earning restricted to designated channels (Enhancement)

> ### Overview
> Modifies the passive token earning system so that message-based token accrual, quest progress, and daily message tracking are restricted to the general chat channel only.
>
> ### Current Behavior
> Users receive tokens, quest progress, and daily message credit for chatting in any channel, enabling abuse in channels like counting, self-promo, and one-word-story.
>
> ### Proposed Behavior
> Only messages sent in the general chat channel will grant passive tokens, count toward quest progress, and count toward the daily message requirement.
>
> ### Technical Requirements
> - [ ] Update the passive token earning logic to check that the message was sent in `GENERAL_CHANNEL_ID` before granting tokens …(truncated)

Implemented in `3860976`. Files: `README.md`, `features/economy.py`, `features/quests.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Restores the baseline's general-only earning dropped back in January 2026. XP deliberately remained un-gated here — the "XP everywhere" bug was deferred and finally fixed by #353 in v1.11.0.

#### #309 — Feature: Add `/active-matches` command to display all active matches (Feature)

> ### Overview
> This sub-issue will implement a new command, `/active-matches`, to provide users with an overview of all currently active match scores, including those not considered bottleneck matches, thus complementing the existing `/tourney progress` command.
>
> ### Technical Requirements
>
> - [ ] Implement new slash command `/active-matches`.
> - [ ] Develop logic to retrieve and identify all currently active matches within the system.
> - [ ] Format and display the match numbers and their current scores for all active matches.
>
> ### Acceptance Criteria
>
> - [ ] The `/active-matches` command is registered and accessible to users.
> - [ ] Executing `/active-matches` displays a list of all active matches …(truncated)

Implemented in `8151184`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Restricted to staff despite the spec saying "accessible to users"; output is grouped by round (unspecced nicety).

#### #312 — Feature: Generate Monthly Tournament Reporting (Feature)

> ### Overview
> This feature will implement a scheduled task to generate a monthly report for tournaments, specifically detailing total tickets submitted by each tournament admin for the preceding month. This report will be generated automatically on the first of each month.
>
> ### Technical Requirements
>
> - [ ] Implement a scheduled job to run on the 1st of every month.
> - [ ] Aggregate total tickets submitted by each tournament admin for the previous month.
>
> - [ ] Include additional relevant metrics for the report (e.g., total tournaments, total participants).
> - [ ] Determine the output format and delivery mechanism for the report.
>
> ### Acceptance Criteria
>
> - [ ] A monthly report is successfully …(truncated)

Implemented in `d47690c`, `5cc6ced`. Files: `tests/test_tourney_reports.py`, `features/config.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_reports.py`, `main.py`

⚠️ as-implemented differs from #312: goes far beyond the filed spec — per-tourney reports enriched with the Matcherino tournament name and schedule date and archived to a new channel, a monthly rollup that aggregates by parsing the bot's own archived report embeds (not DB queries), Matcherino-ID auto-detection on !starttourney from the schedule channel, and a manual re-run path with streamed status. The spec's "total participants" metric is not among those reported.


#### #316 — Enhancement: Remove 5-match display cap for bottleneck matches in tourney progress embed (Enhancement)

> ### Overview
> This enhancement modifies the tourney progress embed by removing the current limit on the number of bottleneck matches displayed, allowing users to see all relevant matches.
>
> ### Current Behavior
> The tourney progress embed currently limits the display of bottleneck matches to a maximum of 5, even if more exist.
>
> ### Proposed Behavior
> The bot should display all existing bottleneck matches in the tourney progress embed without any arbitrary numerical limit.
>
> ### Technical Requirements
> - [ ] Modify the logic that generates the bottleneck match list in the embed to remove the 5-match cap.
> - [ ] Ensure the embed can gracefully handle a larger number of matches without exceeding Disco …(truncated)

Implemented in `7797c14`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #317 — Enhancement: Remove slow mode after 1 hour in tournament channels (Enhancement)

> ### Overview
> This enhancement proposes an automatic mechanism to disable slow mode in tournament-specific channels after a set duration, improving channel usability during extended tournaments.
>
> ### Current Behavior
> Currently, slow mode, if enabled in tournament channels, remains active indefinitely until manually disabled by a moderator or admin. This can hinder communication during longer tournament periods.
>
> ### Proposed Behavior
> After 1 hour from the time slow mode is initially set in a tournament channel, the bot should automatically remove or disable the slow mode for that channel.
>
> ### Technical Requirements
> - [ ] Implement a timer or scheduler that triggers 1 hour after slow mode is …(truncated)

Implemented in `2786a3a`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The timer is in-memory — a bot restart during the hour cancels the auto-disable.

#### #318 — Enhancement: Replace daily event cleanup warnings instead of sending new ones (Enhancement)

> ### Overview
> This enhancement aims to prevent channel flooding by replacing previous daily event cleanup warning messages instead of posting new ones, modifying the existing 'red, blue, green event cleanup warnings' feature.
>
> ### Current Behavior
> Every night at 12 AM EST, the bot posts new 'red, blue, green event cleanup warning' messages. If a channel has messages older than 7 days, a new warning is posted daily, leading to channel flooding with multiple cleanup warnings.
>
> ### Proposed Behavior
> Instead of posting a new warning, the bot should attempt to find and delete the previous day's event cleanup warning message (if one exists) and then post the new warning. This will ensure only one c …(truncated)

Implemented in `4974f32`. Files: `features/event.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Previous-warning tracking is in-memory, so the first warning after a restart can still stack once.

#### #325 — Enhancement: Update documentation and help commands for v1.10.0 deployment (Enhancement)

> ### Overview
> This enhancement focuses on updating the project's documentation, specifically the README and in-bot help commands, to ensure they are current and accurate in preparation for the v1.10.0 deployment.
>
> ### Current Behavior
> The README and existing help commands may contain outdated information or lack details regarding new features or changes introduced in the upcoming v1.10.0 update.
>
> ### Proposed Behavior
> Before the v1.10.0 deployment, the project's README will be updated to reflect all current features and usage instructions. Additionally, all relevant in-bot help commands will be reviewed and modified as needed to provide users with accurate and up-to-date information.
>
> ### Tec …(truncated)

Implemented in `db46b21`. Files: `README.md`, `features/general.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Two small inaccuracies shipped — /help claims a wrong number "resets the count" (it doesn't; the message is just deleted) and documents !sticky <message> although the command is reply-based.


#### #326 — Enhancement: Add unit tests for existing features (Enhancement)

> ### Overview
> This enhancement focuses on improving code quality and reliability by adding unit tests to existing features and functions that currently lack test coverage.
>
> ### Current Behavior
> Many existing features, functions, and modules within the bot's codebase do not have corresponding unit tests, leading to potential regressions and difficulty in refactoring without breaking existing functionality.
>
> ### Proposed Behavior
> Implement comprehensive unit tests for identified features and functions that currently lack test coverage. This will involve writing test cases to validate expected behavior, edge cases, and error handling.
>
> ### Technical Requirements
> - [ ] Identify features/functions …(truncated)

Implemented in `c201cfe`. Files: `tests/test_convert_time.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #327 — Enhancement: Update bot version to v1.10.0 in pyproject.toml (Enhancement)

> ### Overview
> This enhancement updates the bot's version number in the project configuration file to reflect a new release.
>
> ### Current Behavior
> The bot's version in `pyproject.toml` is currently set to v1.9.2.
>
> ### Proposed Behavior
> The bot's version in `pyproject.toml` should be updated to v1.10.0.
>
> ### Technical Requirements
> - [ ] Update 'version' field in pyproject.toml to v1.10.0
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file reflects version `v1.10.0`
>
> ### Benefit/Impact
> Accurately reflects the current development version of the bot, which is important for package management and release tracking.
>
> ### Branch
> [code block omitted]

Implemented in `245354a`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.11.0 — 2026-07-18

#### #332 — Feature: Create `docs/` folder with initial documentation files (Feature)

> ### Overview
>
> This sub-issue focuses on establishing a `docs/` folder within the project, which will house Markdown files explaining various bot functionalities and implementation details. This contributes to better project maintainability and onboarding for new contributors.
>
> ### Technical Requirements
>
> - [ ] Create a new `docs/` directory at the project root.
> - [ ] Add initial Markdown files (e.g., `tourney_matcherino.md`, `token_system.md`, `hacked_system.md`) within the `docs/` folder.
>
> - [ ] Populate these initial files with placeholder content or basic explanations for the respective functionalities.
>
> ### Acceptance Criteria
>
> - [ ] A `docs/` folder exists in the project root.
> - [ ] At …(truncated)

Implemented in `d72ba7f`. Files: `docs/BRAWL_COLLECTION.md`, `docs/BRAWL_DROPS.md`, `docs/BRAWL_PROGRESSION.md`, `docs/CONFIG_SYSTEM.md`, `docs/COUNTING_GAME.md`, `docs/DATABASE.md`, `docs/ECONOMY_SHOP.md`, `docs/EVENT_MANAGEMENT.md`, `docs/GITHUB_TICKETS.md`, `docs/HACKED_SYSTEM.md`, `docs/PAYOUT_SYSTEM.md`, `docs/QUEST_SYSTEM.md`, `docs/SETUP.md`, `docs/STICKY_MESSAGES.md`, `docs/SUPPORT_TICKETS.md`, `docs/TICKET_ROUTER.md`, `docs/TIME_CONVERSION.md`, `docs/TOKEN_SYSTEM.md`, `docs/TOURNEY_BLACKLIST.md`, `docs/TOURNEY_MATCHERINO.md`, `docs/TOURNEY_OVERVIEW.md`, `docs/TOURNEY_PROGRESS.md`, `docs/TOURNEY_REPORTS.md`, `docs/TOURNEY_TICKETS.md`, `docs/TOURNEY_VIEWS.md`, `docs/TRANSLATION.md`, `docs/XP_AND_LEVELING.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Far exceeds the "placeholder content" spec — 27 full implementation guides (~2,900 lines) covering every feature area.

#### #333 — Enhancement: Remove redundant !lock and !unlock commands (Enhancement)

> ### Overview
> Remove the `!lock` and `!unlock` commands as their functionality is already covered by existing tournament management commands.
>
> ### Current Behavior
> The bot currently includes `!lock` and `!unlock` commands which are intended to control channel access.
>
> ### Proposed Behavior
> Completely remove the `!lock` and `!unlock` commands from the bot. Their functionality is made redundant by the `!starttourney` and `!endtourney` commands, which implicitly manage channel locking/unlocking.
>
> ### Technical Requirements
> - [ ] Remove `!lock` command definition and associated handler.
> - [ ] Remove `!unlock` command definition and associated handler.
> - [ ] Update any command help documentation o …(truncated)

Implemented in `d7ecfa8`. Files: `README.md`, `docs/TOURNEY_OVERVIEW.md`, `docs/TOURNEY_TICKETS.md`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The commands are removed but their bodies survive as internal helpers still called by !starttourney/!endtourney.

#### #337 — Feature: Image Upload for Ticket Creation (Feature)

> ### Overview
> This feature adds an optional image upload capability to the ticket creation process, allowing users to attach screenshots or relevant images when opening a ticket. This will greatly enhance the clarity and context provided to support staff, improving the efficiency of ticket resolution.
>
> ### Technical Requirements
>
> - [ ] Implement an optional image input field (e.g., URL input or follow-up attachment mechanism) within the ticket creation flow.
> - [ ] Handle and store the uploaded image data temporarily with the ticket.
> - [ ] Display the uploaded images as embeds or attachments in the newly opened ticket channel.
> - [ ] Attach the uploaded images to the ticket transcript message i …(truncated)

Implemented in `1dc474b`. Files: `docs/SETUP.md`, `docs/TOURNEY_TICKETS.md`, `docs/TOURNEY_VIEWS.md`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_utils.py`, `features/tourney/tourney_views.py`, `tests/test_tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Transcripts attach only the modal-submitted images (found via marker messages, capped at 9); attaching all images posted later in the ticket was deferred as a follow-up.

#### #338 — Bug: R7 Token Redemption Budget Does Not Account for Pending Tickets (Bug)

> ### Overview
> The current system for R7 token redemption tickets calculates available budget without considering existing pending redemption amounts. This can result in overspending the allocated monthly budget. Furthermore, there is no mechanism to handle redemption requests that exceed the available budget, even when pending tickets are accounted for, which should instead be queued for future months.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] The system accurately calculates the available budget for R7 token redemptions by subtracting the total value of all pending redemption tickets from the monthly budget.
> - [ ] Users are prevented from creating a new R7 redemption ticket if …(truncated)

Implemented in `1ece0c8`. Files: `database/mongo.py`, `docs/ECONOMY_SHOP.md`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #341 — Feature: Scam image auto-detection with hacked protocol (Feature)

> ### Overview
>
> Add an automated scam image detection system to `features/scam_detection.py` that monitors all message attachments, compares them against a MongoDB-persisted blacklist using MD5 hashing and OpenCV ORB feature matching, and fires `_execute_hacked_action` on a positive match.
>
> ### Technical Requirements
>
> - [ ] Create `features/scam_detection.py` as a new cog (`ScamDetection`) loaded in `main.py`
> - [ ] Add a `scam_images` MongoDB collection -- each document stores `{ filename: str, data: Binary, md5: str }`
> - [ ] On cog load, fetch all documents from `scam_images` and index into RAM: MD5 hashes into a `set`, ORB descriptors into a list of `(filename, descriptors)` tuples via `Thre …(truncated)

Implemented in `b5150bb`, `945be59`. Files: `README.md`, `docs/SCAM_DETECTION.md`, `features/general.py`, `database/mongo.py`, `features/scam_detection.py`, `main.py`, `requirements.txt`

⚠️ as-implemented differs from #341: the shipped system deliberately redesigns the filed spec — instead of auto-firing the full hacked protocol on match, it applies a 10-minute precautionary timeout plus a mod alert with Confirm Hacked / False Positive buttons; it adds an unspecced pHash matcher, a cross-channel purge of image copies (30-minute lookback), a MongoDB TTL lock preventing duplicate alerts, MD5-keyed storage, and !scam-rename; !scam-remove works by MD5 prefix rather than filename.

#### #346 — Enhancement: Increase passive token boost, add passive XP boost, and daily bonus for server boosters (Enhancement)

> ### Overview
> Increases the existing server booster passive token bonus, introduces a matching passive XP bonus, and adds a flat token bonus to `/daily`, modifying the passive earning and daily claim logic in `features/economy.py`.
>
> ### Current Behavior
> Server boosters have a 17.5% chance of receiving +1 extra token per eligible message, resulting in a ~5% average token increase. No passive XP boost exists for boosters and `/daily` grants 80–160 tokens with no booster bonus.
>
> ### Proposed Behavior
> The token bonus chance is raised to 35% (~10% average increase). An equivalent 35% chance of +1 extra XP per eligible message is added for boosters. Server boosters also receive a flat +20 tokens on …(truncated)

Implemented in `4487521`. Files: `docs/TOKEN_SYSTEM.md`, `features/config.py`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The booster XP bonus is gated to the general (later also booster) channel and rolls independently of the token cooldown — the spec's "same passive earning block" wording predates the channel gating.

#### #347 — Feature: 10% shop discount for server boosters (Feature)

> ### Overview
> Introduces a monthly, gated 10% token discount on all shop items for eligible server boosters, adding discount logic to `/buy` and `/shop` in `features/economy.py`.
>
> ### Technical Requirements
> - [ ] Gate discount eligibility on: Booster role + `member.premium_since` ≥ 14 days ago + no discount used this calendar month
> - [ ] Apply 10% token reduction at purchase time in the `/buy` command handler
> - [ ] Deduct the original pre-discount price from the $50 monthly budget cap, not the discounted price
> - [ ] Display discounted price with strikethrough on the original price in `/shop` for eligible boosters
> - [ ] Track monthly discount usage per user in MongoDB and reset on calendar mon …(truncated)

Implemented in `3389af1`. Files: `database/mongo.py`, `docs/CONFIG_SYSTEM.md`, `docs/DATABASE.md`, `docs/ECONOMY_SHOP.md`, `docs/TOKEN_SYSTEM.md`, `docs/XP_AND_LEVELING.md`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: A concurrent double-/buy could in principle use the discount twice before the month stamp lands (accepted edge). The spec's budget requirement is satisfied trivially: the discount never touches REDEMPTION_BUDGET_COSTS.

#### #348 — Feature: Reduce quest thresholds by 20% for server boosters (Feature)

> ### Overview
> Introduces reduced quest thresholds for server boosters across all quest types, stored at assignment time and applied at the next quest cycle.
>
> ### Technical Requirements
> - [ ] Check for Booster role at quest assignment time and store the appropriate threshold directly on the quest record
> - [ ] Apply the 20% reduction across all four quest types: daily message (64/128/192), weekly message (400/600/800), daily megabox (80), weekly megabox (400)
> - [ ] Ensure `/reset-quests` re-evaluates booster status at the time of forced reassignment
>
> ### Acceptance Criteria
> - [ ] Boosters are assigned reduced thresholds at the next quest cycle after boosting
> - [ ] Thresholds revert to standard …(truncated)

Implemented in `410c7d7`. Files: `database/mongo.py`, `docs/QUEST_SYSTEM.md`, `features/brawl/commands.py`, `features/quests.py`, `tests/test_quests.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #349 — Feature: Auto-created shoutout ticket on server boost (Feature)

> ### Overview
> Automatically creates a ticket when a member begins boosting, giving them a space to write a message for the announcements channel subject to admin review.
>
> ### Technical Requirements
> - [ ] Listen on `on_member_update` for `premium_since` transitioning from `None` to a datetime value to detect new boosts
> - [ ] Auto-create a ticket in the booster ticket category on boost detection
> - [ ] Scope ticket creation to once per boost month — skip if a shoutout ticket was already opened in the current calendar month
> - [ ] Booster closes the ticket manually to opt out; no additional flow required
>
> ### Acceptance Criteria
> - [ ] A ticket is automatically created when a member begins boosting …(truncated)

Implemented in `288820c`. Files: `database/mongo.py`, `docs/BOOSTER_SHOUTOUT.md`, `docs/CONFIG_SYSTEM.md`, `docs/DATABASE.md`, `docs/SETUP.md`, `docs/SUPPORT_TICKETS.md`, `docs/TICKET_ROUTER.md`, `features/booster_shoutout.py`, `features/config.py`, `features/ticket_command_router.py`, `main.py`, `tests/test_booster_shoutout.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: One deliberate, maintainer-approved deviation — close/reopen/delete are staff-only; the booster opts out by asking staff, rather than closing the ticket themselves as the spec proposed.


#### #350 — Feature: Booster-exclusive channel with dedicated supply drops (Feature)

> ### Overview
> Introduces a booster-exclusive social channel with its own supply drop task, providing boosters a secondary community space and additional passive token earning opportunities.
>
> ### Technical Requirements
> - [ ] Add `BOOSTER_CHANNEL_ID` to `features/config.py`
> - [ ] Create a dedicated background task for booster channel drops posting 10–25 tokens on a randomised 0–14400 second interval, averaging ~2 hours, with a hard pity cap of 4 hours
> - [ ] Store the active drop message ID in the MongoDB `settings` collection; edit the previous drop message to indicate expiry when a new drop fires
> - [ ] Passive token earning and quest progress apply in the booster channel identically to general …(truncated)

Implemented in `cc1a260`. Files: `docs/CONFIG_SYSTEM.md`, `docs/TOKEN_SYSTEM.md`, `features/config.py`, `features/economy.py`, `features/quests.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Earning/quest parity in the booster channel also extends #346's XP bonus there (approved scope extension); the 4-hour pity cap is inherent to the 0–4h random sleep rather than a tracked counter; channel permissions are managed manually in Discord, not by the bot.

#### #351 — Feature: Booster benefits command (Feature)

> ### Overview
> Introduces a slash command that displays all active server booster perks in a clean embed, giving boosters and prospective boosters a single reference for what they receive.
>
> ### Technical Requirements
> - [ ] Add a `/booster-perks` slash command accessible to all members
> - [ ] Render a styled embed listing all active booster perks with relevant details (percentages, limits, gates where applicable)
> - [ ] Clearly distinguish perks that are immediately active on boost from those with additional gates (e.g. 14-day `premium_since` for the shop discount)
>
> ### Acceptance Criteria
> - [ ] Command is accessible to all server members
> - [ ] Embed accurately reflects all active booster perks
> - …(truncated)

Implemented in `a347c51`. Files: `docs/BOOSTER_SHOUTOUT.md`, `docs/ECONOMY_SHOP.md`, `docs/QUEST_SYSTEM.md`, `docs/TOKEN_SYSTEM.md`, `docs/XP_AND_LEVELING.md`, `features/general.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #353 — Bug: XP can be gained in any channel, should be limited to general chat (Bug)

> ### Overview
> The bot currently grants XP to users for activity in any channel. This behavior is inconsistent with the intended design, which dictates that XP should only be gainable within the designated 'general chat' channel, mirroring the token acquisition system.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] XP is only gained for messages sent in the configured general chat channel.
> - [ ] XP is not gained for messages sent in any other channel.
> - [ ] The XP gaining mechanism is consistent with the token gaining mechanism regarding channel restrictions.
>
> ### Steps to Reproduce Bug
> - [ ] Send a message in a non-general chat channel where the bot is active.
> - [ ] Check user's XP. …(truncated)

Implemented in `a9aaedd`. Files: `docs/TOKEN_SYSTEM.md`, `docs/XP_AND_LEVELING.md`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Closes the "XP everywhere" defect present since the January 2026 earning rebuild and deferred in #301/#346. XP is gated to the general and booster channels — the booster channel slightly exceeding the issue's "general chat only" wording, consistent with #350.

#### #354 — Enhancement: Remove 'Tourney Admin' option from Staff Application (Enhancement)

> ### Overview
> This enhancement modifies the staff application process by removing the 'Tourney Admin' role option, reflecting that the position is no longer open for applications.
>
> ### Current Behavior
> The staff application `/support-panel` currently lists 'Tourney Admin' as an available role option for applicants. Additionally, during ticket creation, 'Tourney Admin' may appear as an selectable or visible role.
>
> ### Proposed Behavior
> The 'Tourney Admin' role option should be completely removed from the selection within the `/support-panel` for staff applications. Furthermore, if 'Tourney Admin' is displayed in any capacity during the ticket creation process (e.g., in a list of available role …(truncated)

Implemented in `2a23fcc`. Files: `README.md`, `docs/SUPPORT_TICKETS.md`, `features/support_tickets.py`

✅ Reviewed against the diff: implementation matches the filed spec.


#### #359 — Feature: Moderator webhook message mirroring (Feature)

> ### Overview
> Allows moderators to paste a Discord message link anywhere in the server and have the bot repost that message via webhook in the same channel, rendered with the original author's username and avatar.
>
> ### Technical Requirements
> - [ ] Listen for Discord message links posted by members with the Moderator role
> - [ ] Fetch the linked message via Discord API and retrieve its content, author username, and author avatar
> - [ ] Create a webhook in the channel where the link was posted and send the message content using the original author's username and avatar
> - [ ] Strip all user and role mentions from the mirrored content before posting to prevent unintended pings
> - [ ] Delete the mode …(truncated)

Implemented in `f60da2e`. Files: `docs/MESSAGE_MIRROR.md`, `features/message_mirror.py`, `main.py`, `tests/test_message_mirror.py`

⚠️ as-implemented differs from #359: two deliberate deviations from the filed spec — the moderator's link message is left in place (spec said delete it after mirroring), and only messages that are exactly one Discord link trigger the mirror (an unspecced guard protecting conversational messages containing links).


#### #366 — Enhancement: Update token shop prices and correct USD display values (Enhancement)

> ### Overview
> This enhancement updates the token prices for various shop items and corrects stale USD display values in the bot's configuration, improving pricing accuracy.
>
> ### Current Behavior
> The token shop items are currently priced at 1,700 tokens per dollar. Some USD display values for items like Brawl Pass ($9.00) and Brawl Pass+ ($13.00) are outdated in `SHOP_DATA`.
>
> ### Proposed Behavior
> All token shop item prices will be adjusted to 2,000 tokens per dollar. The specific new costs will be:
> - Brawl Pass: 18,000 tokens
> - Brawl Pass+: 26,000 tokens
> - CoC Gold Pass: 14,000 tokens
> - CR Diamond Pass: 24,000 tokens
> - Discord Nitro: 20,000 tokens
> - PayPal $15: 30,000 tokens
> - Shoutout: 14,00 …(truncated)

Implemented in `b56b718`. Files: `docs/ECONOMY_SHOP.md`, `features/config.py`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The issue's claim that the USD values lived in SHOP_DATA was wrong — the real fix updates REDEMPTION_BUDGET_COSTS in features/economy.py (mirrored in docs). Token prices match the spec exactly.

#### #368 — Enhancement: Bump project version to v1.11.0 (Enhancement)

> ### Overview
> This enhancement updates the project version in `pyproject.toml` from v1.10.0 to v1.11.0, preparing for a new release.
>
> ### Current Behavior
> The project's version in `pyproject.toml` is currently set to `v1.10.0`.
>
> ### Proposed Behavior
> The project's version in `pyproject.toml` should be updated to `v1.11.0`.
>
> ### Technical Requirements
> - [ ] Update version string in `pyproject.toml` to `v1.11.0`
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file reflects version `v1.11.0`
> - [ ] All relevant CI checks pass after the version bump
>
> ### Benefit/Impact
> This ensures the project's metadata accurately reflects the upcoming release version, maintaining proper version control and r …(truncated)

Implemented in `bb3f237`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #370 — Enhancement: Fix stale and missing docs for v1.11.0 (Enhancement)

> ### Overview
> Corrects stale prices and booster bonus info in `docs/ECONOMY_SHOP.md` and `README.md`, and adds missing Booster Perks content.
>
> ### Current Behavior
> `docs/ECONOMY_SHOP.md` has pre-rebase price examples. `README.md` understates the booster passive bonus (5% vs ~10%), is missing a Booster Perks section, omits booster shoutout tickets and the moderator message-link mirror, and has a stale version string.
>
> ### Proposed Behavior
> All docs reflect current behavior as of v1.11.0.
>
> ### Technical Requirements
> - [ ] `ECONOMY_SHOP.md` line 15: `"price": 5000` → `"price": 18000`
> - [ ] `ECONOMY_SHOP.md` line 49: `~~5000~~ **4500**` → `~~18000~~ **16200**`
> - [ ] `README.md` line 75: correct b …(truncated)

Implemented in `b85d891`. Files: `README.md`, `docs/ECONOMY_SHOP.md`

✅ Reviewed against the diff: implementation matches the filed spec.

### v1.11.1 — 2026-07-20

#### #373 — Feature: Add logs/SPECS.md and logs/CHANGELOG.md as persistent development history (Enhancement)

> ### Overview
> Adds a `logs/` directory at repo root containing two files that preserve development history and intent in a form that survives outside of GitHub — `SPECS.md` as a chronological as-implemented spec record and `CHANGELOG.md` as a chronological record of PR descriptions and release notes.
>
> ### Technical Requirements
> - [ ] Create `logs/` directory at repo root
> - [ ] Create `logs/SPECS.md` with three-era structure: Part 1 (Baseline — inherited SQLite monolith, pre-Dec 14 2025), Part 2 (Pre-Release R7 — MongoDB rewrite through Jan 30 2026), Part 3 (Tracked — Jan 31 2026 onwards, issue-referenced specs)
> - [ ] Create `logs/CHANGELOG.md` populated chronologically from existing release n …(truncated)

Implemented in `013339e`, `473cc3b`, `8b72088`, `a01b2e4`. Files: `logs/CHANGELOG.md`, `logs/SPECS.md`, `scripts/generate_specs.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Self-referential — this issue created SPECS.md and CHANGELOG.md themselves. Parts 1–2 of SPECS.md were authored manually; Part 3 and the CHANGELOG PR-description blocks were produced by `scripts/generate_specs.py` from GitHub data, covering releases through v1.11.0. The generator is one-shot (aborts if its output already exists), so this v1.11.1 section was appended by hand in the same format.

#### #374 — Enhancement: Automate Hall of Fame generation on tournament end (Enhancement)

> ### Overview
> This enhancement integrates the Hall of Fame generation process directly into the `!endtourney` command, ensuring that the Hall of Fame is automatically updated upon tournament completion.
>
> ### Current Behavior
> The Hall of Fame likely requires a separate, manual trigger to generate or update. The `!endtourney` command currently only concludes a tournament without initiating Hall of Fame generation.
>
> ### Proposed Behavior
> When the `!endtourney` command is executed, the bot should automatically trigger the Hall of Fame generation. This process should utilize the tournament ID of the recently concluded tournament to fetch and process relevant data for the Hall of Fame.
>
> ### Technic …(truncated)

Implemented in `4898c3d`. Files: `README.md`, `docs/TOURNEY_OVERVIEW.md`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The `/hall-of-fame` slash command was refactored into a shared `post_hall_of_fame(guild, tournament_id)` helper returning `(success, message)`, called by both the slash command and `!endtourney`. Auto-post is skipped when the session has no `matcherino_id`, and any failure is caught and reported to the command channel without blocking the rest of `!endtourney`.

#### #377 — Bug: Previous booster drops sometimes remain after new drop (Bug)

> ### Overview
> The system is failing to consistently expire previous booster drops in the booster channel when a new drop occurs. This results in multiple active drops being visible simultaneously.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] Verify that when a new booster drop is initiated, any previous unclaimed drop in the same channel is correctly expired.
> - [ ] Confirm that only one active booster drop is present in the booster channel at any given time.
>
> ### Steps to Reproduce Bug
> - [ ] Monitor the booster channel for drops.
> - [ ] Observe instances where a new drop occurs, but a previous, unclaimed drop still remains active.
> - [ ] Test initiating multiple drops in quick succe …(truncated)

Implemented in `163d999`. Files: `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: `_expire_previous_booster_drop()` now returns a bool that gates the new drop. Transient Discord `HTTPException`s while fetching or editing the previous drop return `False`, so the new drop is skipped and retried next cycle instead of posting on top of an un-expired one; a missing message or invalid stored ID clears the setting and lets the drop proceed. This guarantees at most one live drop at a time.

#### #379 — Enhancement: Move documentation files to `docs/logs/` (Enhancement)

> ### Overview
> This enhancement aims to reorganize the project's documentation by moving `CHANGELOG.md` and `SPECS.md` from the `logs/` directory to a new `docs/logs/` directory. This improves clarity and consistency for documentation location.
>
> ### Current Behavior
> The `CHANGELOG.md` and `SPECS.md` files are currently located in the `logs/` directory, which is inconsistent with general documentation practices and can make them less discoverable.
>
> ### Proposed Behavior
> The `logs/` directory containing `CHANGELOG.md` and `SPECS.md` will be moved inside `docs/`, resulting in the files being located at `docs/logs/CHANGELOG.md` and `docs/logs/SPECS.md`.
>
> ### Technical Requirements
> - [ ] Create `do …(truncated)

Implemented in `75f0916`. Files: `docs/logs/CHANGELOG.md`, `docs/logs/SPECS.md`, `scripts/generate_specs.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The move also updated the `SPECS_PATH` and `CHANGELOG_PATH` constants in `scripts/generate_specs.py` to point at `docs/logs/`.

#### #381 — Enhancement: Bump project version to v1.11.1 in pyproject.toml (Enhancement)

> ### Overview
> This enhancement updates the project version in `pyproject.toml` to `v1.11.1`, reflecting recent changes or a new release. It modifies the existing version tracking mechanism.
>
> ### Current Behavior
> The project's declared version in `pyproject.toml` is currently `v1.11.0`.
>
> ### Proposed Behavior
> The project's declared version in `pyproject.toml` should be updated to `v1.11.1`.
>
> ### Technical Requirements
> - [ ] Modify the `version` field in `pyproject.toml` to `1.11.1`.
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file contains `version = "1.11.1"`.
>
> ### Benefit/Impact
> Ensures the project's version accurately reflects its current state, providing clear version tracking for …(truncated)

Implemented in `3fce9b0`. Files: `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #382 — Enhancement: Update documentation for v1.11.1 release (Enhancement)

> ### Overview
> This enhancement aims to update all relevant documentation to reflect the changes introduced in release v1.11.1, ensuring accuracy and currency for users and developers.
>
> ### Current Behavior
> Documentation may be outdated or incomplete regarding features, commands, or functionalities introduced or modified in v1.11.1.
>
> ### Proposed Behavior
> Review all existing documentation, identify sections affected by the v1.11.1 release, and update them to accurately reflect the current state of the bot's features and commands.
>
> ### Technical Requirements
> - [ ] Identify all changes/features introduced in v1.11.1.
> - [ ] Review existing documentation (e.g., README, command help, wiki).
> - [ ] U …(truncated)

Implemented in `<pending — set to the 382-Enhancement doc commit sha once committed>`. Files: `README.md`, `docs/TOKEN_SYSTEM.md`, `docs/logs/CHANGELOG.md`, `docs/logs/SPECS.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Self-referential — this is the release-doc pass that wrote this very v1.11.1 SPECS section, the CHANGELOG release notes + PR descriptions, the #377 booster-drop expiry update in `TOKEN_SYSTEM.md`, and the README version bump. The commit sha above is a placeholder until the branch is committed and merged.

### v1.12.0 — 2026-08-14

#### #390 — Bug: Slow mode message is contradictory regarding duration (Bug)

> ### Overview
> The Discord bot displays a slow mode message that indicates the slow mode is for the duration of a tournament but also states it will be automatically removed after 1 hour, which is contradictory.
>
> ### Acceptance Criteria
> How do we know it's done?
> - [ ] The slow mode message accurately reflects the actual duration or removal conditions.
> - [ ] The message is no longer contradictory.
>
> ### Steps to Reproduce Bug
> - [ ] Enable slow mode for a tournament using the bot's relevant command.
> - [ ] Observe the message displayed by the bot regarding slow mode status.
>
> ### Impact
> Users may be confused about the actual duration of the slow mode, leading to misunderstanding or frustration rega …(truncated)

Implemented in `9ad8fea`. Files: `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #391 — Enhancement: Auto-resume tourney state after bot restart (Enhancement)

> ### Overview
>   Make the tourney system automatically recover its runtime state on boot so an in-progress tournament survives a bot restart.
>
>   ### Current Behavior
>   If the bot restarts mid-tourney, the DB session survives but all runtime state is lost: dashboards stop, slowmode/lock timers vanish (can get stuck forever), region redirect and
>   admin-role name are forgotten, and the ticket counter resets. The only recovery is re-running `!starttourney`, which is destructive.
>
>   ### Proposed Behavior
>   On boot, detect an active session and non-destructively rehydrate: restart dashboards, re-arm the slowmode/lock timers (or fire immediately if elapsed), restore region + admin-role
>   name, and r …(truncated)

Implemented in `efa71ea`. Files: `database/mongo.py`, `docs/DATABASE.md`, `docs/TOURNEY_OVERVIEW.md`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Adds the codebase's first boot-time reconcile hook, `resume_tourney_if_active()` on `on_ready` — every crash-safety fix later in this release (#410 onward) hangs its own startup reconcile task alongside it. `!starttourney` now warns on an active session unless `force` is passed, and the milestone-announcement scan was widened so a resume re-adopts existing announcements instead of duplicating them.

#### #395 — Bug: CI lint fails on PR #394 (391-Enhancement) due to unpinned Ruff version (Bug)

> ### Overview
> CI installs Ruff unpinned (`pip install ruff`) with no `[tool.ruff.lint]` config in the repo. A newer Ruff version released between 07-21 and 07-27 has stricter defaults, now flagging 292 pre-existing issues on PR #394 (branch `391-Enhancement`). Confirmed on the live PR: local Ruff and `make fix` report clean, since the local Ruff install doesn't have these newer rule categories enabled at all. This is a CI tooling issue, not a code issue.
>
> ### Acceptance Criteria
> - [ ] `pyproject.toml` has an explicit `[tool.ruff.lint]` `select` list
> - [ ] `.github/workflows/lint.yml` pins Ruff to the same version used locally
> - [ ] PR #394 lint check passes with zero code changes
>
> ### Steps t …(truncated)

Implemented in `f2bd1c9`. Files: `.github/workflows/lint.yml`, `pyproject.toml`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: CI-tooling only, no feature code. Added an explicit `[tool.ruff.lint] select` set to `pyproject.toml` and pinned the CI Ruff version in `lint.yml` so `ruff check` is deterministic across Ruff releases; unblocked PR #394 with zero code changes.

#### #398 — Enhancement: Update docs to reflect migration from Pella to RamNaym Cloud (Enhancement)

> ### Overview
> The bot has moved hosts from Pella to RamNaym Cloud (Nano plan) after repeated Pella outages, the last straw being the server randomly stopping during a live tournament and needing a manual restart, combined with a lack of transparency and communication from Pella around these issues. RamNaym has been consistent since the switch. Docs, configs, and any references to Pella need to be replaced with the new host, and the reasoning behind the switch should be documented for future reference.
>
> ### Current Behavior
> Docs and any leftover config/deploy references still assume or mention Pella as the host. No record of the new host, its specs, or the reasoning for switching exists anywhe …(truncated)

Implemented in `58f6a21`. Files: `README.md`, `database/mongo.py`, `docs/HOSTING.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Replaced all Pella references with RamNaym Cloud and added a new `docs/HOSTING.md` capturing the migration history, plan specs, and the reliability reasoning for the switch, plus a Hosting section in the README.

#### #404 — Enhancement: Allow Event Staff to use `!sticky` and `!unsticky` commands (Enhancement)

> ### Overview
> This enhancement will extend the permission set for the `!sticky` and `!unsticky` commands to include the Event Staff role.
>
> ### Current Behavior
> Currently, the `!sticky` and `!unsticky` commands are only accessible to administrator-level roles or specific moderator roles as configured.
>
> ### Proposed Behavior
> The `!sticky` and `!unsticky` commands should be accessible to users with the 'Event Staff' role in addition to their current permitted roles. The 'Event Staff' role is already defined in the bot's configuration.
>
> ### Technical Requirements
> - [ ] Update the permission check logic for `!sticky` command to include the 'Event Staff' role.
> - [ ] Update the permission check logi …(truncated)

Implemented in `d65b8a2`. Files: `docs/STICKY_MESSAGES.md`, `features/sticky.py`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #410 — Bug: /redeem can permanently lose a user's item on a mid-operation crash (Bug)

> ### Overview
> `/redeem` removes the user's item token, then creates a redemption ticket. If the bot crashes or is killed between those two steps, the item is gone and no ticket was ever created. The current try/except rollback only catches in-process exceptions, it does nothing for an OOM kill or forced restart.
>
> ### Acceptance Criteria
> - [ ] A pending-redemption record is written to MongoDB before the item token is removed
> - [ ] Once `create_redemption_ticket` succeeds, the resulting ticket channel id is written back into the pending record before it is cleared, so a crash between ticket creation and record deletion is decidable on reconcile
> - [ ] On startup, the bot reconciles any pending r …(truncated)

Implemented in `7c9c05a`. Files: `database/mongo.py`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: First of the Tier-1 crash-safety epic. Writes a pending-redemption record (with a unique key and stale-age guard so a legitimately in-flight `/redeem` isn't refunded by a concurrent reconcile) before removing the item token, and stamps the ticket channel id back into the record once the ticket exists. A second `on_ready` reconcile task refunds only when no ticket was created — never both keeps a ticket and refunds. Branched from dev: the reconcile would be dead code on main without the #391 boot hook.

#### #411 — Bug: /buy can deduct tokens without granting the item on a mid-operation crash (Bug)

> ### Overview
> `/buy` deducts tokens from the user's balance, then grants the item token. There is no rollback of any kind between these two writes, so a crash between them leaves the user debited with nothing to show for it.
>
> ### Acceptance Criteria
> - [ ] The deduct and grant steps are wrapped so a crash between them can be safely rolled back or completed on next startup
> - [ ] A forced restart between the two writes results in either the item being granted or the tokens being refunded, never neither
>
> ### Steps to Reproduce Bug
> - [ ] Run `/buy` for an item
> - [ ] Kill the bot process between the balance deduction and the item grant
> - [ ] Restart the bot and confirm tokens are gone with no item …(truncated)

Implemented in `eff6c51`. Files: `database/mongo.py`, `docs/ECONOMY_SHOP.md`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: `/buy` deduct-then-grant collapsed into a single atomic write so a crash can no longer debit tokens without granting the item.

#### #412 — Bug: Quest rewards can be permanently lost if the bot crashes right after completion is flagged (Bug)

> ### Overview
> When a quest completes, the quest is flagged `completed: True` in MongoDB before tokens and XP are granted. Re-entry is blocked once a quest is flagged completed. If the bot crashes after the flag is written but before the reward payout runs, the quest shows as done forever and the user never receives tokens or XP, with no retry possible.
>
> ### Acceptance Criteria
> - [ ] Completion and reward payout are tracked separately, e.g. a `rewarded: True` flag distinct from `completed: True`
> - [ ] Re-grant logic is gated on the reward flag, not the completion flag, so an incomplete payout can be retried without re-granting a reward twice
> - [ ] A forced restart between the completion flag w …(truncated)

Implemented in `f967f8b`. Files: `database/mongo.py`, `docs/QUEST_SYSTEM.md`, `features/quests.py`, `tests/test_quests.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Split the single `completed` flag into distinct `completed` and `rewarded` flags; re-grant is gated on `rewarded`, so a crash between marking a quest done and paying it out is retried on next completion check without double-paying.

#### #413 — Bug: /event-rewards has no crash protection and can double-pay everyone on retry (Bug)

> ### Overview
> `/event-rewards` loops through parsed users and pays each one, then marks the source message with a reaction at the very end. The "processed" state only exists in memory on the view object, it is not persisted anywhere. A crash mid-loop, or simply a bot restart, means re-running the command re-pays every user from scratch, including anyone already paid.
>
> ### Acceptance Criteria
> - [ ] A persisted per-recipient reward ledger tracks who has already been paid for a given event-rewards message
> - [ ] Payout logic checks the ledger before paying each recipient, skipping anyone already paid
> - [ ] Re-running the command after a crash results in only unpaid recipients receiving tokens, ne …(truncated)

Implemented in `bbb7e86`. Files: `database/mongo.py`, `docs/DATABASE.md`, `features/event.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Introduces the shared per-recipient `reward_payouts` ledger (claim-before-pay) that #414 and #432 later reuse. A crash mid-loop and retry pays only recipients not yet claimed for that message.

#### #414 — Bug: /poll-rewards can double-pay voters caught mid-loop during a crash (Bug)

> ### Overview
> `/poll-rewards` already has a persisted message-level gate (`is_poll_reward_processed`) that prevents a full re-run from re-paying everyone. However the gate is only marked after the entire payout loop finishes, so a crash mid-loop leaves the message unmarked, and a retry re-pays every voter who was already paid before the crash.
>
> ### Acceptance Criteria
> - [ ] Payout tracking moves from a single whole-message gate to a per-voter ledger, sharing the same underlying mechanism as the /event-rewards fix
> - [ ] Payout logic checks the per-voter ledger before paying each voter, skipping anyone already paid
> - [ ] Re-running the command after a mid-loop crash results in only unpaid voter …(truncated)

Implemented in `9f99b56`. Files: `database/mongo.py`, `docs/DATABASE.md`, `features/event.py`, `tests/test_reward_payouts.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Migrates `/poll-rewards` off its whole-message `is_poll_reward_processed` gate onto the per-voter `reward_payouts` ledger from #413, closing the mid-loop double-pay window the message-level gate left open.

#### #415 — Bug: Redemption queue treats any member cache miss as "user left the server" (Bug)

> ### Overview
> The redemption queue checks `guild.get_member(user_id)` to decide if a queued user has left the server. `get_member` only checks the local cache and returns `None` for any user not yet cached, which includes users who are still in the server but haven't been re-cached since the last bot restart. On a cache miss, the queue immediately deletes the entry and refunds tokens, even if the user never left.
>
> ### Acceptance Criteria
> - [ ] On a `get_member` cache miss, the bot calls `fetch_member` to confirm against the Discord API before concluding the user left
> - [ ] A `discord.NotFound` result confirms the user genuinely left and the existing refund/remove logic runs
> - [ ] A `discord.H …(truncated)

Implemented in `2260cd3`. Files: `docs/ECONOMY_SHOP.md`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: On a `get_member` cache miss the queue now calls `fetch_member` — `NotFound` confirms a genuine leave (refund runs), while a transient `HTTPException` skips the entry for that cycle instead of wrongly refunding an active member across a cold restart. Lands before #416, which depends on this guard.

#### #416 — Bug: Redemption queue can create duplicate tickets and double-spend budget on retry (Bug)

> ### Overview
> The redemption queue creates a redemption ticket, then removes the queue entry afterward. If the bot crashes after the ticket is created but before the entry is removed, the next scheduled run processes the same entry again, creating a second ticket and spending the item's budget a second time.
>
> ### Acceptance Criteria
> - [ ] Depends on ticket 415 landing first
> - [ ] Ticket creation and entry removal happen atomically, or the entry is marked in a "processing"/"ticket created" state immediately after ticket creation succeeds
> - [ ] On startup or next scheduled run, any entry already marked as having a ticket created is not reprocessed
> - [ ] A forced restart between ticket creation …(truncated)

Implemented in `75f0057`. Files: `database/mongo.py`, `docs/DATABASE.md`, `docs/ECONOMY_SHOP.md`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Marks the queue entry with its created ticket channel id immediately after creation, and the cold-boot reconcile skips any already-ticketed entry, so a crash between ticket creation and entry removal no longer double-creates tickets or double-spends budget. Depends on and branched from #415; a stuck reconcile refunds the item rather than leaving it lost.

#### #417 — Bug: Scam image purge leaves remaining channels un-purged forever after a crash (Bug)

> ### Overview
> When a scam image is detected, the bot purges matching copies of it across every text channel and thread in a sequential loop. If the bot crashes partway through this loop, the remaining channels are never purged. There is no persisted record of which channels were already checked, and the detection's freshness guard prevents this from ever being caught and retried automatically.
>
> ### Acceptance Criteria
> - [ ] The purge operation persists a session doc listing target channels and a cursor of which have been completed
> - [ ] On startup, any incomplete purge session is detected and resumed from where it left off
> - [ ] A forced restart mid-purge results in all originally targeted ch …(truncated)

Implemented in `867d799`. Files: `database/mongo.py`, `docs/DATABASE.md`, `docs/SCAM_DETECTION.md`, `features/scam_detection.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Persists a purge-session doc listing target channels with a completion cursor; an incomplete session is detected and resumed on startup, so a crash mid-purge no longer leaves scam images live in un-visited channels.

#### #418 — Bug: Brawl ability and brawler purchases can deduct currency without granting the item (Bug)

> ### Overview
> Buying a brawler ability deducts coins then grants the ability; buying a brawler deducts credits then grants the brawler. Both are two separate writes with no atomicity between them. A crash between the deduction and the grant leaves the user's currency spent with nothing received. `upgrade_brawler_level` already handles this correctly elsewhere in the same file and should be used as the reference pattern.
>
> ### Acceptance Criteria
> - [ ] Ability purchases combine the deduct and grant into a single atomic operation, mirroring `upgrade_brawler_level`
> - [ ] Brawler purchases combine the deduct and grant into a single atomic operation, mirroring `upgrade_brawler_level`
> - [ ] A forced …(truncated)

Implemented in `1049de4`. Files: `database/mongo.py`, `docs/BRAWL_COLLECTION.md`, `docs/BRAWL_PROGRESSION.md`, `features/brawl/commands.py`, `tests/test_brawl_purchase.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Brawl ability and brawler purchases now collapse deduct-then-grant into a single atomic operation, mirroring the existing `upgrade_brawler_level` pattern in the same file.

#### #419 — Bug: Ticket close, budget, and daily claim flows can double-refund or double-charge on retry (Bug)

> ### Overview
> Several lower-severity flows write a destructive or financial step before the final closing action, rather than after. This includes redemption ticket close-with-refund (refund happens before channel delete), close-with-budget-deduction (budget deducted before channel delete), and /daily (tokens granted before the cooldown is stamped). In each case, an interruption between the two steps leaves a persistent button or retryable state that can trigger the first step a second time.
>
> ### Acceptance Criteria
> - [ ] Redemption ticket close-with-refund reorders or guards against a duplicate refund if the close button is clicked again after a crash
> - [ ] Redemption ticket close-with-budge …(truncated)

Implemented in `39781b1`. Files: `database/mongo.py`, `docs/ECONOMY_SHOP.md`, `docs/TOKEN_SYSTEM.md`, `features/economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Lower-severity tail of the epic — reorders redemption close-with-refund and close-with-budget so the destructive step follows the channel delete (or is guarded against a re-click), and stamps the `/daily` cooldown atomically with the token grant. Deploy-timing (not mid-tourney) and the intentional split-storage of the pending marker are noted caveats carried from the fix's PR.

#### #423 — Feature: Add `make commit` shortcut for git add/commit/push (Feature)

> ### Overview
> Adds a `make commit` target to the Makefile that runs `git add .`, `git commit -m "<message>"`, and `git push` in sequence, saving the dev from typing all three manually.
>
> ### Technical Requirements
> - [ ] Add a `commit` target to the Makefile
> - [ ] Accept the commit message via an `m` variable (e.g. `make commit m="fix ci lint"`), since Make can't take a quoted positional argument directly
> - [ ] Target runs, in order: `git add .`, `git commit -m "$(m)"`, `git push`
> - [ ] Fail early with a clear error if `m` is not provided (don't let it fall through to `git commit` with no `-m`)
>
> ### Acceptance Criteria
> - [ ] Running `make commit m="some message"` stages all changes, commits wit …(truncated)

Implemented in `91d9433`. Files: `Makefile`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Dev tooling only. `make commit m="..."` runs add/commit/push in order and fails early with a clear error if `m` is unset, rather than opening an editor or committing blank.

#### #432 — Bug: Tourney staff payout batches can be silently lost or double-paid on crash (Bug)

> ### Overview
> `add_payout_batch` (called by `/payout-add`) inserts a `payout_logs` record claiming everyone in the batch was paid, then loops through each user id applying the `$inc`/`$push` to their `payouts` doc. If the bot crashes mid-loop, staff before the crash point get credited and staff after don't, with no trace that anything went wrong, since nothing ever replays `payout_logs` back into `payouts` (it's read-only, used for `/payout-history` display). A retry after a crash also mints a fresh batch id and re-pays the entire list, double-crediting anyone already paid in the failed run. This is the same loop-then-log-completion shape that 413 and 414 already fixed for `/event-rewards` an …(truncated)

Implemented in `8a107f7`. Files: `database/mongo.py`, `features/event.py`, `features/tourney/tourney_commands.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: `/payout-add` now derives a deterministic `batch_id` and claims each recipient in the shared `reward_payouts` ledger before crediting, so a crash-and-retry pays only staff not already credited. This flow was missed by the earlier #409 audit; batch-id collision and stuck-window handling are noted caveats from the fix's PR. Tournament-day flow, prioritized ahead of the next tourney.

#### #433 — Bug: Redemption queue still has two unprotected delete-then-pay crash windows (Bug)

> ### Overview
> Two remaining paths in the redemption queue still delete a record before paying out, the same class of bug 416 fixed for queue ticket creation, left unprotected here: `/redemption-queue-remove` deletes the queue entry then grants the item token back, and the member-left refund path deletes the queue entry then refunds tokens. In both cases, a crash between the delete and the payout leaves the record gone with nothing granted or refunded, a silent, untraceable loss. Notably, the member-left refund path sits right next to the properly-fixed ticket-creation branch in the same function, 415's `fetch_member` guard hardened the cache check for this branch but didn't touch its delete-t …(truncated)

Implemented in `23008e3`. Files: `database/mongo.py`, `docs/DATABASE.md`, `docs/ECONOMY_SHOP.md`, `features/economy.py`, `tests/test_economy.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Closes the two remaining delete-then-pay windows in the redemption queue (`/redemption-queue-remove` and the member-left refund path) via a claim plus an on-user-doc refund receipt (`apply_queue_refund`), reconciled by the existing cold-boot task. The reconcile refund branch must order ahead of the delete; refund-accumulation and balance-recompute behavior are noted caveats from the fix's PR.

#### #434 — Bug: Remaining low-severity crash-safety and restart gaps across drops, tourney, and boosters (Bug)

> ### Overview
> A handful of smaller, non-destructive gaps remain from the crash-safety audit, none of them touch existing balances or cause silent value loss, but each leaves the bot in a degraded or inconsistent state after a restart. Bundled here as one lower-priority cleanup rather than four separate urgent tickets: DropView claim buttons stop working after a restart because they have no `custom_id` and are never re-registered via `add_view` at startup, leaving outstanding supply/booster/admin drops permanently unclaimable; the booster drop's `booster_drop_message_id` marker has no startup reconcile and only self-clears after roughly 4 hours; `!endtourney`'s winner announcement uses an in-m …(truncated)

Implemented in `ac2bb6c`. Files: `database/mongo.py`, `docs/BOOSTER_SHOUTOUT.md`, `docs/DATABASE.md`, `docs/TOKEN_SYSTEM.md`, `docs/TOURNEY_OVERVIEW.md`, `features/booster_shoutout.py`, `features/economy.py`, `features/event.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_reports.py`, `tests/test_booster_shoutout.py`, `tests/test_economy.py`, `tests/test_tourney_reports.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Tier-3 cleanup bundle — DropView given a stable `custom_id` and re-registered via `add_view` at startup so drops stay claimable after a restart; booster-drop marker gains a startup reconcile; `!endtourney`'s winner announcement uses a persisted retry marker instead of an in-memory sleep; the per-message token reward switches to the atomic `$inc` helper and stamps the cooldown first; booster-shoutout ticket creation is guarded against its duplicate window; and `tasks.loop(time=)` jobs catch up / log clearly when a scheduled run is missed to downtime.

#### #435 — Enhancement: Bump project version to v1.12.0 (Enhancement)

> ### Overview
> This enhancement updates the project version in `pyproject.toml` from v1.11.1 to v1.12.0, preparing for a new release.
>
> ### Current Behavior
> The project's version in `pyproject.toml` is currently set to `v1.11.1`.
>
> ### Proposed Behavior
> The project's version in `pyproject.toml` should be updated to `v1.12.0`.
>
> ### Technical Requirements
> - [ ] Update version string in `pyproject.toml` to `v1.12.0`
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file reflects version `v1.12.0`
> - [ ] All relevant CI checks pass after the version bump
>
> ### Benefit/Impact
> This ensures the project's metadata accurately reflects the upcoming release version, maintaining proper version control and r …(truncated)

Implemented in `f74ec32`. Files: `pyproject.toml`, `README.md`

✅ Reviewed against the diff: implementation matches the filed spec.

#### #436 — Enhancement: Update documentation for v1.12.0 release (Enhancement)

> ### Overview
> This enhancement aims to update all relevant documentation to reflect the changes introduced in release v1.12.0, ensuring accuracy and currency for users and developers.
>
> ### Current Behavior
> Documentation may be outdated or incomplete regarding features, commands, or functionalities introduced or modified in v1.12.0.
>
> ### Proposed Behavior
> Review all existing documentation, identify sections affected by the v1.12.0 release, and update them to accurately reflect the current state of the bot's features and commands.
>
> ### Technical Requirements
> - [ ] Identify all changes/features introduced in v1.12.0.
> - [ ] Review existing documentation (e.g., README, command help, wiki).
> - [ ] U …(truncated)

Implemented in `<pending — set to the 436-Enhancement doc commit sha once committed>`. Files: `docs/logs/SPECS.md`, `docs/logs/CHANGELOG.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Self-referential — this is the release-doc pass that wrote this very v1.12.0 SPECS section and the v1.12.0 CHANGELOG release notes + PR descriptions. The README/`pyproject.toml` version bump is handled separately by #435 (PR #440). The commit sha above is a placeholder until this branch is committed and merged.

### v1.13.0 — 2026-08-30

#### #355 — Enhancement: Add mathematical computation support to counting channel (Enhancement)

> ### Overview
> This enhancement modifies the existing counting channel feature to allow users to input mathematical computations instead of just plain numbers for counting up.
>
> ### Proposed Behavior
> The bot should be updated to parse messages in the counting channel. If a message contains a valid mathematical computation (e.g., `7*10`, `6+9`), the bot should evaluate the expression and use its result as the number for counting…
>
> ### Technical Requirements
> - [ ] Implement a parser to detect and evaluate mathematical expressions in user messages.
> - [ ] Integrate a safe math evaluation library or mechanism to process computations.
> - [ ] Update the counting channel's message processing logic to accept evaluated results.
> - [ ] Handle error cases for invalid or malformed mathematical expressions gracef …(truncated)

Implemented in `142ba1a`. Files: `features/counting.py`, `docs/COUNTING_GAME.md`, `tests/test_counting.py`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: The "safe math evaluation mechanism" is an `ast`-based allowlist (`ast.parse` walked through `_eval_node`, permitting only `Add/Sub/Mult/Div` and unary `+/-` over numeric constants) — no `eval()` on user input. Anything that isn't an integer-valued arithmetic expression falls through to `None` and is rejected exactly as a non-numeric message would be.

#### #356 — Feature: Implement Enhanced Story Bot (Feature)

> ### Overview
> This feature replaces the existing one-word story bot with a more robust and versatile story-building bot, allowing for new moderation capabilities and extended functionality.
>
> ### Technical Requirements
> - [ ] Reimplement core story-building logic for a collaborative story.
> - [ ] Add functionality for a configurable banned word list.
> - [ ] Add functionality for a configurable banned character list.
> - [ ] Integrate the new bot into the existing Discord server environ …(truncated)

Implemented in `f6f2e25`. Files: `features/story.py`, `database/mongo.py`, `features/config.py`, `features/general.py`, `main.py`, `docs/ONE_WORD_STORY.md`, `docs/DATABASE.md`, `README.md`, `tests/test_story.py`

✅ Reviewed against the diff: both a configurable banned-word list and a configurable banned-character list ship (`validate_word` returns `"banned_word"` / `"banned_char"` reasons), with the collaborative story state persisted in Mongo.

📝 Review note: The issue is framed as *replacing* "the existing one-word story bot," but no prior story feature existed at v1.12.0 — `features/story.py` is net-new, so there was nothing to migrate. It also ships as a cog inside R7, not as the standalone "bot… invited to a Discord server" the acceptance criteria describe; that wording is generic template boilerplate, not a second bot.

#### #388 — Bug: Pre-tourney ticket opening fails to ping user (Bug)

> ### Overview
> When a user opens a pre-tourney ticket, the bot currently does not ping the user in the newly created ticket channel. This results in the user potentially not knowing where their ticket has been created.
>
> ### Acceptance Criteria
> - [ ] The user who opens a pre-tourney ticket receives a ping (@mention) in the newly created ticket channel.
> - [ ] The ping is visible and clickable, directing the user to the tic …(truncated)

Implemented in `935a34b`. Files: `features/tourney/tourney_utils.py`

✅ Reviewed against the diff: implementation matches the filed spec — a one-line change adding the opener's mention to the pre-tourney ticket channel's opening message.

#### #448 — Enhancement: Track Claude Code configuration in the repository (Enhancement)

> ### Overview
> Reverse #158 and track `.claude/` and `CLAUDE.md` in git, so hooks, skills, and project context survive a fresh clone instead of living on one machine.
>
> ### Technical Requirements
> - [ ] Replace the `.claude/` and `CLAUDE.md` entries in `.gitignore` with an allowlist… then re-ignore `.claude/settings.local.json`
> - [ ] Confirm the hook scripts are committed as mode `100755` so they stay executable
> - [ ] Replace the absolute path in the `PostToolUse` handler with `${CLAUDE_PROJECT_DIR}`
>
> ### Notes
> Reverses #158. Note that in the SPECS entry, as #274 did for #254 …(truncated)

Implemented in `7f745e3`, `792b330`. Files: `.gitignore`, `.claude/settings.json`, `.claude/hooks/` (`check-config-parity.py`, `require-tests.sh`, `stop-checks.sh`, `format-file.sh`), `.claude/skills/` (docs-sync, spec-record, ship, write-tests, new-cog, pr-desc, commit-message, release-notes, write-ticket, improve-codebase-architecture, thermo-nuclear-code-quality-review), `Makefile`, `README.md`

**Reverses #158**, which had un-tracked and git-ignored `.claude/` and `CLAUDE.md` back when the directory only held machine-specific `settings.local.json`. The allowlist (`.claude/*` ignored, then specific paths un-ignored, `settings.local.json` re-ignored) preserves the #143 accident guard while tracking the now-shared hook/skill config. The `PostToolUse` absolute path was replaced with `${CLAUDE_PROJECT_DIR}` as specced.

⚠️ as-implemented differs from #448: the ticket's title and Technical Requirements call for tracking `CLAUDE.md`, but no repo-level `CLAUDE.md` exists — the workspace `CLAUDE.md` lives one directory above the repo root, outside version control — so only `.claude/` was tracked and that acceptance criterion is unmet by necessity, not satisfied. Separately, the second commit (`792b330`) bundles a hook-quality refactor beyond "track the config": it adds `format-file.sh`, rewrites `check-config-parity.py` (−40 lines), and reworks `require-tests.sh`, `stop-checks.sh`, and the `Makefile`.

#### #450 — Bug: `make lint` and `make test` fail locally while CI passes (Bug)

> ### Overview
> The `Makefile` dev targets don't resolve to the same toolchain CI uses… Two separate symptoms, one root cause — nothing pins the local toolchain.
> **1. Ruff version drift.** … Ruff 0.16 formats Python code blocks *inside markdown*, which 0.15.15 does not…
> **2. `make test` uses bare `pytest`.** It resolves through `PATH` rather than the project venv…
>
> ### Acceptance Criteria
> - [ ] … Local and CI resolve to the same ruff version…
> - [ ] An explicit decision on markdown: either reformat the 9 `docs/*.md` files… or exclude `*.md` from the formatter…
> - [ ] `make test` invokes the venv interpreter rather than whatever `pytest` is on `PATH …(truncated)

Implemented in `1a2acd8`. Files: `.github/workflows/lint.yml`, `Makefile`, `pyproject.toml`, `requirements.txt`, `docs/SETUP.md`

✅ Reviewed against the diff: implementation matches the filed spec, and picks a concrete answer to each open decision the ticket posed.

📝 Review note: Of the two either/or choices the acceptance criteria offered, both were resolved toward pinning-newer rather than pinning-older: ruff is exact-pinned to `0.16.0` in `requirements.txt` (the one source of truth `lint.yml` now installs against), and `*.md` is excluded from the formatter via `[tool.ruff.format] exclude = ["*.md"]` rather than reformatting the 9 docs. `make test` now runs the `.venv` interpreter, and the stale contradictory comments in `lint.yml`/`pyproject.toml` were corrected.

#### #443 — Bug: Hall of Fame command sometimes shows $0 prizepool (Bug)

> ### Overview
> The `hall of fame` command occasionally displays a total prizepool of $0, even when there should be a non-zero value. This issue appears intermittently.
>
> ### Acceptance Criteria
> - [ ] The `hall of fame` command consistently displays the correct total prizepool amount.
> - [ ] The command never displays $0 as the total prizepool when the actual prizepool value is greater than z …(truncated)

Implemented in `c489642`, `d62a5e7`. Files: `features/tourney/hall_of_fame.py`, `features/tourney/matcherino.py`, `features/tourney/tourney_commands.py`, `features/config.py`, `pyproject.toml`, `docs/TOURNEY_OVERVIEW.md`, `tests/test_hall_of_fame.py`, `tests/test_matcherino.py`

⚠️ as-implemented differs from #443: the ticket describes a display bug ("sometimes shows $0"), and `c489642` is the proportionate fix — it distinguishes an *unknown* prizepool (read failure → `None`) from a genuine `$0`, so a failed read no longer renders as `$0.00`. But `d62a5e7` then builds an entire prizepool retry/alert subsystem that the ticket never asked for: on a failed read it posts an alert embed to `#tourney-admin` with a manual-override control, schedules capped automatic retries (`HOF_MAX_ATTEMPTS`) anchored to a persisted `next_hof_retry_at` marker, and closes the alert out on resolution. This is a crash-safety epic bundled into a display-bug fix (the `tourney_commands.py` change alone is ~538 lines).

📝 Review note: The retry uses an in-memory `asyncio.Task` handle (`hof_retry_task`) to cancel a superseded run, but the persisted marker is the source of truth, so a restart mid-wait is recoverable rather than silently dropped. This PR also carried the version bump `1.12.0 → 1.12.1` (see #493 on the per-PR bump cadence).

#### #408 — Feature: Implement Level Leaderboard (Feature)

> ### Overview
> This sub-issue focuses on implementing a new level leaderboard feature, allowing users to view a ranked list of server members based on their experience points (XP) and levels.
>
> ### Technical Requirements
> - [ ] … Create a new command (e.g., `/leaderboard level`) to trigger the display.
> - [ ] Ensure the display format is consistent with the existing token leaderboard.
>
> ### Notes
> Refer to the existing token leaderboard implementation for guidance… to maintain consist …(truncated)

Implemented in `a4568e9`, `8edc6aa`. Files: `features/economy.py`, `database/mongo.py`, `features/general.py`, `pyproject.toml`, `README.md`, `docs/TOKEN_SYSTEM.md`, `docs/XP_AND_LEVELING.md`, `tests/test_leaderboards.py`

⚠️ as-implemented differs from #408: the ticket scopes a single new level leaderboard "consistent with the existing token leaderboard." The implementation instead restructured *both* into an `app_commands.Group` — `/leaderboard token` and `/leaderboard level` under one group — reshaping the existing token command rather than leaving it alone, and bundled an unspecced crash fix: ranking previously raised `KeyError` for users with no `balance`/`level`/`exp` field, now guarded with `.get(..., default)` plus a Mongo `{"$exists": True}` filter so missing-field users sort last. The bug fix is related to level ranking (users without XP fields) but also touches the token/balance path.

📝 Review note: This PR carried the version bump `1.12.1 → 1.12.2` (see #493).

#### #457 — Enhancement: Rename ALLOWED_STAFF_ROLES to TOURNEY_STAFF_ROLES (Enhancement)

> ### Overview
> Rename the `ALLOWED_STAFF_ROLES` config constant to `TOURNEY_STAFF_ROLES`, and update every reference. The current name sounds like a general server-wide staff list, but it's used exclusively by the tourney feature.
>
> ### Acceptance Criteria
> - [ ] No occurrences of `ALLOWED_STAFF_ROLES` remain in code or docs
> - [ ] `TOURNEY_STAFF_ROLES` holds the same role IDs
> - [ ] Tourney behavior is unchanged; lint and tests p …(truncated)

Implemented in `70796d4`. Files: `features/config.py`, `features/tourney/tourney_commands.py`, `features/tourney/tourney_reports.py`, `features/tourney/tourney_utils.py`, `docs/CONFIG_SYSTEM.md`, `docs/SETUP.md`, `docs/TOURNEY_TICKETS.md`

✅ Reviewed against the diff: pure rename, same role IDs, no behavior change. A repo-wide grep confirms no `ALLOWED_STAFF_ROLES` occurrences remain outside `docs/logs/`.

#### #455 — Enhancement: Disable Claude attribution and tighten the pr-desc skill (Enhancement)

> ### Overview
> Two small changes ahead of running scheduled Claude Code tasks against this repo: stop Claude attribution appearing in commits and PR bodies, and make the `pr-desc` skill state that PR descriptions stay short.
>
> ### Technical Requirements
> - [ ] Add an `attribution` block to `.claude/settings.json` with `commits` and `pullRequests` both set to `false`…
> - [ ] Add a tracked `.githooks/commit-msg` hook that strips any `Co-Authored-By: Claude`… lines, as a backstop…
> - [ ] Update the `pr-desc` skill to state that descriptions are sho …(truncated)

Implemented in `5d70e82`. Files: `.claude/settings.json`, `.githooks/commit-msg`, `.claude/skills/pr-desc/SKILL.md`, `.claude/skills/pr-desc/references/pr-guide.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: First of the attribution-hardening cluster [#455 → #477 → #484 → #486]. This ticket establishes the `attribution` block and the `.githooks/commit-msg` backstop; the git-author identity (`session-setup.sh`) and the `Claude-Session:`/PR-footer stripping arrive later in #477 and #484, and the PR-title-shape CI check in #486.

#### #484 — Enhancement: Correct commit author and strip the Claude Code PR footer in cloud sessions (Enhancement)

> ### Overview
> Two attribution problems in Claude Code cloud/remote sessions:
> 1. **Commit author.** Commits are authored by `Claude <noreply@anthropic.com>` instead of `RemainingDelta`…
> 2. **PR footer.** A `_Generated by [Claude Code](...)_` footer is appended to PR bodies… added **server-side by the GitHub MCP integration at PR-creation time**…
>
> ### Notes
> Overlaps with the still-open PR #482 (`477-Enhancement`), which introduces an equivalent `session-setup.sh` but not the footer-stripping workflow. If #482 merges first, the hook half here becomes a no-op; the workflow is additive either w …(truncated)

Implemented in `4083a80`, `b0ad17d`. Files: `.claude/hooks/session-setup.sh`, `.claude/settings.json`, `.github/workflows/strip-pr-footer.yml`

✅ Reviewed against the diff: adds the `SessionStart` `session-setup.sh` (pins `core.hooksPath`, `user.name`, `user.email`) and the `strip-pr-footer.yml` workflow that removes the server-injected `_Generated by [Claude Code]_` footer from PR bodies targeting `dev`.

📝 Review note: The overlap the ticket predicted with #477 played out in reverse — #485 (this) merged *before* #482 (#477), so this PR's `session-setup.sh` landed first and #477's equivalent reconciled onto it rather than the other way around. The tree ends with a single `session-setup.sh`; this PR's uniquely surviving contribution is the `strip-pr-footer.yml` workflow, which no other ticket in the cluster provides.

#### #486 — Enhancement: Enforce PR title format in CI (no colon, lowercase word after the type) (Enhancement)

> ### Overview
> PR titles drift from the repo convention `<issue>-<Type> <lowercase verb> …` — several open PRs used `<issue>-<Type>: Capitalized …`… There is no CI check enforcing the title shape…
>
> ### Technical Requirements
> - [ ] Add a GitHub Actions workflow (`.github/workflows/pr-title-format-check.yml`)… fails when the title does not match `<number>-<Type> <lowercase word> …`
> - [ ] The check must reject a colon after the type… and reject an uppercase first word after the ty …(truncated)

Implemented in `140c76f`. Files: `.github/workflows/pr-title-format-check.yml`

✅ Reviewed against the diff: implementation matches the filed spec — a new workflow on PRs into `dev` rejecting a colon after the type and an uppercase first word, leaving `pr-issue-reference-check.yml` untouched.

#### #490 — Feature: Privacy policy document, /privacy-policy command, and auto-posted privacy channel (Feature)

> ### Overview
> R7 Bot has no published privacy policy… This adds one policy, written once and rendered in three places: a repo document, a `/privacy-policy` slash command, and a channel that is kept current on every restart.
> No external website exists yet, so nothing links out — the only link anywhere is to the in-server tickets channel.
>
> ### Acceptance Criteria
> - [ ] `/privacy-policy` responds successfully for a member with no roles, and the response is public (not ephemeral)
> - [ ] … No link to any external website appears in the embeds, README, or docs …(truncated)

Implemented in `588c108`, `c6bb2f4`, `014b663`, `ef4462e`. Files: `features/privacy_policy.py`, `PRIVACY_POLICY.md`, `features/config.py`, `features/general.py`, `main.py`, `pyproject.toml`, `README.md`, `docs/PRIVACY_SYSTEM.md`, `tests/test_privacy_policy.py`

⚠️ as-implemented differs from #490: two acceptance criteria were reversed by the final commit (`ef4462e`). The ticket states "No external website exists yet, so nothing links out" and requires "No link to any external website… in the embeds, README, or docs" — but the shipped embed carries `[Read this policy on our website](https://remaining7.netlify.app/privacy)`. And AC required the command be "public (not ephemeral)" — the shipped `/privacy-policy` replies with `ephemeral=True`. Both reversals reflect a later decision (a website now exists; the response was made private) rather than the filed spec.

📝 Review note: The single-source-of-truth structure holds — the policy text lives once in `features/privacy_policy.py` and is rendered to both the slash command and the `on_ready` auto-post (delete-then-repost, per the #149 support-panel pattern). `PRIVACY_CHANNEL_ID` shipped as placeholder `0` in `c6bb2f4` (auto-post logs a warning and skips) and was set to real IDs for both servers in `014b663`. This PR also carried the version bump `1.12.2 → 1.13.0` — a *minor* jump that broke the per-PR patch cadence and pre-empted the dedicated bump ticket #493 (see below).

#### #477 — Enhancement: Enforce commit authorship and strip AI attribution in cloud sessions (Enhancement)

> ### Overview
> Routine and cloud session commits are authored as Claude and carry a `Claude-Session:` trailer, and PR bodies carry the session URL. This enforces author identity and attribution suppression at the repo level so it applies to every cloud run without being restated in the prompt.
>
> ### Technical Requirements
> - [ ] Add `"sessionUrl": false` to the `attribution` block…
> - [ ] Create `.claude/hooks/session-setup.sh` setting `core.hooksPath`, `user.name`, and `user.email`…
> - [ ] Extend `.githooks/commit-msg` to strip `Claude-Session:`… lines…
> - [ ] Gate the bot restart in `stop-checks.sh` behind `[ "$CLAUDE_CODE_REMOTE" != "true" ]` …(truncated)

Implemented in `9a049b2`. Files: `.claude/hooks/session-setup.sh`, `.claude/hooks/stop-checks.sh`, `.claude/settings.json`, `.githooks/commit-msg`

✅ Reviewed against the diff: implementation matches the filed spec — `sessionUrl: false`, the `session-setup.sh` author-identity hook, an extended `commit-msg` that strips `Claude-Session:`/`Co-Authored-By: Claude`/`Generated with [Claude Code]` and collapses trailing blanks, and the cloud-gated bot restart in `stop-checks.sh`.

📝 Review note: Closes the attribution-hardening cluster [#455 → #477 → #484 → #486]. Although #477's code was authored earliest, its PR (#482) merged *last* — after #484 had already landed an equivalent `session-setup.sh` — so the final tree carries one reconciled script rather than two. Its uniquely surviving contributions are the `sessionUrl: false` key, the extended `commit-msg` trailer stripping, and the `CLAUDE_CODE_REMOTE` gate on the Stop-hook bot restart.

#### #493 — Enhancement: Bump project version to v1.13.0 (Enhancement)

> ### Overview
> This enhancement updates the project version in `pyproject.toml` from v1.12.0 to v1.13.0, preparing for a new release.
>
> ### Acceptance Criteria
> - [ ] The `pyproject.toml` file reflects version `v1.13.0`
> - [ ] All relevant CI checks pass after the version b …(truncated)

Version bump only, but with no commit of its own. Files: (none — no `493-Enhancement` branch).

⚠️ as-implemented differs from #493: the bump had already been applied ahead of this ticket, inside the #490 privacy-policy PR (`c6bb2f4`, `1.12.2 → 1.13.0`), so #493 was closed as absorbed rather than implemented. Note the cadence break: every intervening PR since v1.12.0 did a single *patch* bump (`1.12.0 → 1.12.1` in #443, `→ 1.12.2` in #408), but #490 jumped the *minor* digit to `1.13.0`. The end number is correct for the release — the feature set (new `/privacy-policy`, `/leaderboard` group, one-word story) warrants a minor bump — but a feature PR unilaterally setting the release's minor version is the reason this ticket had nothing left to do.

#### #494 — Enhancement: Update documentation for v1.13.0 release (Enhancement)

> ### Overview
> This enhancement aims to update all relevant documentation to reflect the changes introduced in release v1.13.0, ensuring accuracy and currency for users and developers.
>
> ### Technical Requirements
> - [ ] Identify all changes/features introduced in v1.13.0.
> - [ ] Review existing documentation (e.g., README, command help, wiki).
> - [ ] U …(truncated)

Implemented in `<pending — set to the 494-Enhancement doc commit sha once committed>`. Files: `docs/logs/SPECS.md`, `docs/logs/CHANGELOG.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Self-referential — this is the release-doc pass that wrote this very v1.13.0 SPECS section (and the v1.13.0 CHANGELOG release notes + PR descriptions, which are the separate half of this ticket). The `README`/`pyproject.toml` version bump was handled out-of-band by #490/#493 above, not here. The full README/`docs/`/help-command audit is tracked separately as #495. The commit sha above is a placeholder until this branch is committed and merged.

---

### v1.13.1 — 2026-09-03

#### #503 — Bug: One failing cog aborts the whole startup load and the global sync deletes 20 slash commands (Bug)

> ### Overview
> `/support-panel` disappeared from Discord entirely, and the existing support panel's dropdown answered **"Remaining 7 Bot didn't respond in time"** while creating **no ticket channel**. The support ticket feature is not the cause.
>
> `main.py:44-101` loads all 17 feature cogs inside **one shared `try`**. `features.scam_detection` (position 5, `main.py:59`) raised during load, the shared `except` swallowed it, and the 12 cogs listed after it were never attempted — including `features.support_tickets` at position 9. `SupportTicketPanelView` therefore never reached `add_view` (`features/support_tickets.py:586`), so the old panel's select matched no registered view, discord.py dropped the interaction, and nothing ever ACKed it.
>
> `main.py:117` then ran `bot.tree.sync()` in its own `try`, unaffected by the load failure. A global sync publishes the tree as the **authoritative** command list, so Discord **deleted** the 20 commands belonging to the skipped cogs.
>
> ### Fixes
> 1. `main.py` — load each cog in its own `try`, so one failure cannot skip the rest. Treat `ExtensionAlreadyLoaded` as success, not failure, since it is the normal case on every reconnect.
> 2. `main.py` — log `repr(e)` plus `traceback.print_exc()`. The current `print(f"...{e}")` loses the traceback, which is why the underlying cause of the `scam_detection` failure is still unknown.
> 3. `main.py` — before syncing, diff the tree against `tree.fetch_commands()` and skip the sync only if it would **delete** a command owned by a failed cog…(truncated)

Implemented in `da08239`. Files: `main.py`, `database/mongo.py`, `features/support_tickets.py`, `tests/test_startup.py`, `tests/test_support_tickets.py`

✅ Reviewed against the diff: all five filed fixes shipped as specified.

📝 Review note: The diff goes slightly beyond the five numbered fixes, in the same direction as their intent — `setup_tourney_commands` failures now feed the same failure list (it registers 19 top-level commands, so its failure must also block a destructive sync), the previously unguarded `repost_privacy_policy` call was wrapped, and a closing summary line reports the failed features. Two acceptance criteria are unverifiable until the release deploys, since production runs `main`: "Boot log shows 72 commands synced with `scam_detection` still failing" and "`/support-panel` is present in the picker". The root cause of the `scam_detection` import failure itself remains unknown and is deliberately out of scope — fix 2 exists precisely to surface it on the next boot. It is the only cog importing `cv2`, so the leading suspects are a numpy/opencv version mismatch (both unpinned `>=` in `requirements.txt`) or a system library missing from the deploy image.

#### #505 — Enhancement: Bump project version to v1.13.1 in pyproject.toml (Enhancement)

> ### Overview
> Updates the declared project version to `1.13.1` for the v1.13.1 patch release, which ships the startup fix from #503.
>
> ### Technical Requirements
> - [ ] Set `version = "1.13.1"` in `pyproject.toml`
> - [ ] Update the `**Version:**` line in `README.md` to `v1.13.1`
>
> ### Acceptance Criteria
> - [ ] `pyproject.toml` contains `version = "1.13.1"`
> - [ ] `README.md` states `v1.13.1`
> - [ ] `BOT_VERSION` resolves to `v1.13.1` with no edit to `features/config.py` (it is derived, not stored)…(truncated)

Implemented in `8d44ff1`. Files: `pyproject.toml`, `README.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: `.claude/skills/release-notes/references/release-guide.md` still instructs bumping `BOT_VERSION` in `features/config.py`. That guidance is stale and was not followed, correctly — `features/config.py:11` derives the constant from `pyproject.toml` by regex, so an edit there would have no effect. The guide itself was left uncorrected in this release.

#### #506 — Enhancement: Update documentation for v1.13.1 release (Enhancement)

> ### Overview
> Adds the v1.13.1 sections to the two persistent history files so the patch release is recorded before the `dev → main` release PR opens.
>
> ### Technical Requirements
> - [ ] Add a `### v1.13.1` section to `docs/logs/SPECS.md`, with the as-implemented entry for #503 and a reviewed verdict against the diff
> - [ ] Add a `## v1.13.1 — <date>` section to `docs/logs/CHANGELOG.md`, containing the release notes body and the `### PR Descriptions` block for PR #504
> - [ ] Follow the release notes format in `.claude/skills/release-notes/references/release-guide.md`, dropping sections with nothing to report…(truncated)

Implemented in `<pending — set to the 506-Enhancement doc commit sha once committed>`. Files: `docs/logs/SPECS.md`, `docs/logs/CHANGELOG.md`

✅ Reviewed against the diff: implementation matches the filed spec.

📝 Review note: Self-referential — this is the release-doc pass that wrote this very v1.13.1 SPECS section, along with the v1.13.1 CHANGELOG release notes and PR descriptions. The ticket scoped SPECS to "#503" only; entries for #505 and #506 were added as well, matching the v1.13.0 precedent of documenting every issue in the release rather than only the code changes. The version bump was handled separately by #505 above, per the split used for v1.11.1 (#381/#382) and v1.12.0 (#435/#436). The commit sha above is a placeholder until this branch is committed and merged.
