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

*(To be filled in.)*
