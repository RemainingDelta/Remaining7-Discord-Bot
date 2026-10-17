# Token System

## Overview
R7 Tokens are the primary server currency. Members earn them passively through chat messages and via `/daily` claims, plus drops, events, polls and quests. Every earned token is tagged with its source (see Token Source Tracking below). The passive listener runs on every `on_message` event and enforces a per-user cooldown tracked in an in-memory dict. Server Boosters receive a ~10% average bonus on passive token earnings, a passive XP bonus in the general channel, a flat +20 tokens on every `/daily` claim, and a once-monthly 10% shop discount (see `ECONOMY_SHOP.md`).

> When changing any booster perk here, also update the `/booster-perks` embed in `features/general.py`.

---

## Passive Earning

The `on_message` listener in `features/economy.py` fires on every message. Token earning, XP earning, daily message count tracking, and quest progress apply identically in the general channel (`GENERAL_CHANNEL_ID`) and the booster-only channel (`BOOSTER_CHANNEL_ID`, `#general-plus`) — no rewards are granted outside these two channels:

1. Ignores bots, DMs, and channels in `PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS`
2. Enforces a **20-second cooldown** per user via the `settings` key `last_message_{user_id}` (an epoch-seconds float), compared against `time.time()`
3. Awards a random amount of `2–5 tokens` (`random.randint(2, 5)`)
4. If the member has the **Server Booster** role (`SERVER_BOOSTER_ROLE_ID`), there is a 35% chance of +1 bonus token (~10% average increase). Boosters also roll a separate 35% chance of +1 bonus XP on every general/booster-channel message, independent of the token cooldown.
5. **Stamps the cooldown first, then grants** the tokens with the atomic `increment_user_balance()` (`$inc`) — never a read-modify-write. Because the balance lives on the user doc and the cooldown in `settings`, the two can't be one atomic write; stamping first means a crash between them loses a tiny 2–6 token reward rather than re-awarding on the next message. (This deliberately reverses #412's paid-first choice, where the reward was large enough to prioritize never-lose over never-double.)
6. Fires the quest listener (`process_quest_update()`) for the message action

The cooldown lives in the `settings` collection, so the check is one small DB read. A residual same-20s-window concurrency race (two messages both passing the check before either stamps) remains — it's pre-existing and worth only ~2–6 tokens, so it's left as-is.

---

## Daily Reward (`/daily`)

```
base   = random 80-160
tokens = int(base * (1 + (level - 1) * 0.05))
```

Level **multiplies** a random base rather than adding to it, and nothing caps the result — a Level 20 member rolls 156-312 tokens where a Level 1 member rolls 80-160.

Requires:
- 24-hour cooldown since last claim (stored on the user doc as `users.daily_last_claimed`, an epoch-seconds float)
- At least **5 messages sent** since the last daily. The counter lives in `settings` under `daily_msg_count_{user_id}` as a `"WINDOW_KEY:COUNT"` string, where `WINDOW_KEY` is `str(daily_last_claimed)`. The `on_message` listener increments it; it resets implicitly when the window key changes (i.e. after a claim), not via an explicit write.

On claim:
1. Reads `daily_last_claimed` from the user doc and derives the message-count window key from it
2. Checks the message count for the current window is `>= 5` and the 24h cooldown has passed
3. Rolls a random 80-160 base and multiplies it by `1 + (level - 1) * 0.05`
4. Adds a flat **+20 tokens** if the member has the Server Booster role (shown as a separate line in the claim embed)
5. Grants the tokens and stamps the cooldown in **one atomic write** — `claim_daily_reward()` (`database/mongo.py`) does `find_one_and_update` with a `{"$inc": {"balance": ...}, "$set": {"daily_last_claimed": now}}` guarded by a `daily_last_claimed < cutoff` predicate. This closes the crash window where tokens could be granted before the cooldown was stamped (which allowed a second immediate claim), and also blocks concurrent double-invocations. If the predicate loses (already claimed), the command shows the cooldown status instead of granting.

> **Storage note:** the cooldown lives on the user doc while the message counter stays in `settings` — this split is intentional. Only the cooldown needs to be part of the atomic grant; moving the counter too would add churn for no safety benefit.

---

## Balance Commands

| Command | Who | Notes |
|---------|-----|-------|
| `/balance [user]` | Anyone | Shows token balance; defaults to self |
| `/economy-stats [days]` | Admin only | Server-wide earned tokens by source over the last `days` UTC days (1-365, default 30); ephemeral |
| `/token-sources [user]` | Anyone | Percentage breakdown of a user's earned tokens by source; defaults to self (see below) |
| `/give <user> <tokens/xp/levels> <amount>` | Admin only | Grants tokens via atomic `increment_user_balance()` tagged `admin`; no transfer from the caller |
| `/set-balance <user> <amount>` | Admin only | Directly sets balance, no transfer logic |
| `/leaderboard token` | Anyone | Paginated 10-per-page view using `LeaderboardView`; shows your rank in the footer |

The leaderboard paginates using `get_leaderboard_page(offset, per_page)` — a MongoDB `find()` sorted by `balance` descending, restricted to users that have a `balance` field. Page bounds come from `get_leaderboard_total()`, which counts the same filtered set. The viewer's own rank is fetched separately with `get_user_rank()` and shown in the footer on every page.

Both boards share `BaseLeaderboardView`, so their buttons, footer and pagination are one implementation; `/leaderboard token` and `/leaderboard level` differ only in the data they read and their titles.

---

## Supply Drop (`/drop <amount>`)

Admin command. Posts a single claimable crate that the first clicker wins:
1. Builds an embed with a persistent `DropClaimButton` via `build_drop_view(amount)`
2. Posts the crate to the channel
3. The **first** user to click the button wins the full `amount` (single-claim guard via the `drop_claims` collection)

---

## Booster Channel Supply Drops

The `booster_drop_task` in `features/economy.py` posts automatic supply drops of **10–25 tokens** into the booster-only channel (`BOOSTER_CHANNEL_ID`, `#general-plus`):

1. Sleeps a uniform random 0–14400 seconds between drops (average ~2 hours, hard 4-hour pity cap)
2. Posts an embed with a persistent claim button (`DropClaimButton`) — first booster to click gets the tokens; staff cannot claim (they can only claim negative drops)
3. Stores the active drop's message ID in the `settings` collection under `booster_drop_message_id`; claiming clears it
4. When a new drop fires, it first expires the previous drop: the previous **unclaimed** drop message is edited to an EXPIRED state with the button removed (claimed drops keep their CLAIMED state). If the previous message is gone or its stored ID is invalid, the ID is cleared and the new drop proceeds. If Discord returns a transient error while fetching or editing the previous drop, the new drop is **skipped for this cycle** and retried on the next one — guaranteeing at most one live drop at a time rather than posting a second before the first is expired

On cold boot, `booster_drop_reconcile_task` (a `count=1` loop) runs `_expire_previous_booster_drop` once so a `booster_drop_message_id` left set by a crash is resolved immediately, instead of waiting up to ~4h for the next drop to expire it lazily.

Channel access is restricted to the Server Booster role via manual Discord permission setup — the bot only needs the channel ID.

### Persistent claim button (all drop types)

The supply (`/drop` and the auto `supply_drop_task`), booster, and admin drops all share one claim button, `DropClaimButton` — a `discord.ui.DynamicItem` whose `custom_id` is `drop_claim:{amount}`. The `amount` may be negative (the template matches `-?\d+`), so an admin can post a negative `/drop` that deducts tokens from the claimer rather than paying them out. Staff (moderator, admin and trial moderator roles) can claim only negative drops; positive and zero drops reject them. It's re-registered once in `Economy.cog_load` via `bot.add_dynamic_items(DropClaimButton)`, so a drop message posted **before** a restart stays claimable (the token amount is recovered from the `custom_id`; the old plain `DropView` had no `custom_id` and was never re-added, leaving pre-restart buttons dead). The single-claim guard is the atomic `claim_drop(message_id, user_id)` (a `$setOnInsert` on the `drop_claims` collection, TTL-expired after 7 days), which replaces the old in-memory `claimed` flag — so it survives restarts and serializes two near-simultaneous clicks. Payout is the atomic `increment_user_balance()` (`$inc`).

---

## Token Source Tracking (`/token-sources`)

Every earned token is tagged with where it came from. The user doc carries a `token_sources` map of per-source totals, bumped **in the same `$inc` as `balance`**, so a user's breakdown can never disagree with what they were paid.

| Source | Granted by |
|--------|-----------|
| `chat` | Passive `on_message` earning |
| `daily` | `claim_daily_reward()` (always, no parameter) |
| `drop` | `DropClaimButton` claimed outside the booster channel (`/drop` and the auto supply drop) |
| `booster_drop` | `DropClaimButton` claimed in `BOOSTER_CHANNEL_ID` |
| `event` | `/event-rewards` payouts |
| `poll` | `/poll-rewards` payouts |
| `quest` | `add_quest_reward()` (always, no parameter) |
| `admin` | `/give tokens` |

Rules:
- The list lives in `TOKEN_SOURCES` in `database/mongo.py`. An unknown source raises `ValueError` before any write, so a typo can't silently create a new bucket. Adding a source there (plus a label in `TOKEN_SOURCE_LABELS` in `features/economy.py`) is all a new earning path needs.
- `increment_user_balance(user_id, amount, source=None)` only records a source when one is passed. **Redemption refunds pass none**: those tokens were already counted under their real source when first earned. `apply_queue_refund()` and `/set-balance` never touch the counters either.
- Only **positive** grants count. A negative drop or negative `/give` moves the balance but doesn't reduce "earned".
- Tracking starts at deploy. Tokens earned before it are not in anyone's breakdown, so the command's footer says it counts tokens "since tracking began".

`/token-sources [user]` (anyone, defaults to self) reads the map with `get_token_sources()`, which reads the doc directly rather than through `get_user_data()` so looking someone up doesn't create a brawl profile. `token_source_breakdown()` turns it into `(source, tokens, percent)` rows, largest first, dropping zero and unknown keys so the percentages always sum to 100 over what's shown.

### Server-wide log (`/economy-stats`)

Each earning grant also bumps that UTC day's `token_stats` doc (`_id = "YYYY-MM-DD"`, one field per source) via `_log_token_generation()`. This runs **after** the balance write and isn't atomic with it (different collection); a failure is printed and swallowed so it can never break a payout. The same rules apply as for the per-user map: no source, a non-positive amount, or a `/daily` claim that lost its cooldown predicate logs nothing.

`/economy-stats [days]` (Admin, `has_permission`) sums the last `days` buckets including today with `get_token_stats()` and renders them with the same `token_source_breakdown()` as `/token-sources`. Like the per-user map, the log starts at deploy, so earlier months can't be reconstructed.

---

## Excluded Channels

`PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS` in `features/config.py` is a list of channel IDs where the passive `on_message` listener skips token/XP earning. This is used for channels like bot-spam or announcement channels where engagement shouldn't be rewarded.

---

## Source File
`features/economy.py`
