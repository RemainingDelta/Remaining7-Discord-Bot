# Token System

## Overview
R7 Tokens are the primary server currency. Members earn them passively through chat messages and via `/daily` claims. The passive listener runs on every `on_message` event and enforces a per-user cooldown tracked in an in-memory dict. Server Boosters receive a ~10% average bonus on passive token earnings, a passive XP bonus in the general channel, a flat +20 tokens on every `/daily` claim, and a once-monthly 10% shop discount (see `ECONOMY_SHOP.md`).

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
Tokens = 80 + (level * 5) capped at 160
```

Requires:
- 24-hour cooldown since last claim (stored on the user doc as `users.daily_last_claimed`, an epoch-seconds float)
- At least **5 messages sent** since the last daily. The counter lives in `settings` under `daily_msg_count_{user_id}` as a `"WINDOW_KEY:COUNT"` string, where `WINDOW_KEY` is `str(daily_last_claimed)`. The `on_message` listener increments it; it resets implicitly when the window key changes (i.e. after a claim), not via an explicit write.

On claim:
1. Reads `daily_last_claimed` from the user doc and derives the message-count window key from it
2. Checks the message count for the current window is `>= 5` and the 24h cooldown has passed
3. Calculates the token reward based on the user's current level
4. Adds a flat **+20 tokens** if the member has the Server Booster role (shown as a separate line in the claim embed)
5. Grants the tokens and stamps the cooldown in **one atomic write** — `claim_daily_reward()` (`database/mongo.py`) does `find_one_and_update` with a `{"$inc": {"balance": ...}, "$set": {"daily_last_claimed": now}}` guarded by a `daily_last_claimed < cutoff` predicate. This closes the crash window where tokens could be granted before the cooldown was stamped (which allowed a second immediate claim), and also blocks concurrent double-invocations. If the predicate loses (already claimed), the command shows the cooldown status instead of granting.

> **Storage note:** the cooldown lives on the user doc while the message counter stays in `settings` — this split is intentional. Only the cooldown needs to be part of the atomic grant; moving the counter too would add churn for no safety benefit.

---

## Balance Commands

| Command | Who | Notes |
|---------|-----|-------|
| `/balance [user]` | Anyone | Shows token balance; defaults to self |
| `/give <user> <amount>` | Anyone | Transfers from caller to target; fails if insufficient balance |
| `/set-balance <user> <amount>` | Admin only | Directly sets balance, no transfer logic |
| `/leaderboard [page]` | Anyone | Paginated 10-per-page view using `LeaderboardView`; shows your rank in the footer |

The leaderboard paginates using `get_leaderboard_page(offset, per_page)` — a MongoDB `find()` sorted by `balance` descending. The viewer's own rank is fetched separately with `get_user_rank()` and shown in the footer on every page.

---

## Supply Drop (`/drop <amount>`)

Admin command. Distributes tokens to members active in the general channel:
1. Reads recent messages from `GENERAL_CHANNEL_ID`
2. Collects unique non-bot member IDs
3. Divides `amount` among them (or gives `amount` to each — depends on config)
4. Calls `update_user_balance()` for each recipient
5. Posts a confirmation embed listing recipients and amount per person

---

## Booster Channel Supply Drops

The `booster_drop_task` in `features/economy.py` posts automatic supply drops of **10–25 tokens** into the booster-only channel (`BOOSTER_CHANNEL_ID`, `#general-plus`):

1. Sleeps a uniform random 0–14400 seconds between drops (average ~2 hours, hard 4-hour pity cap)
2. Posts an embed with a persistent claim button (`DropClaimButton`) — first booster to click gets the tokens; staff cannot claim
3. Stores the active drop's message ID in the `settings` collection under `booster_drop_message_id`; claiming clears it
4. When a new drop fires, it first expires the previous drop: the previous **unclaimed** drop message is edited to an EXPIRED state with the button removed (claimed drops keep their CLAIMED state). If the previous message is gone or its stored ID is invalid, the ID is cleared and the new drop proceeds. If Discord returns a transient error while fetching or editing the previous drop, the new drop is **skipped for this cycle** and retried on the next one — guaranteeing at most one live drop at a time rather than posting a second before the first is expired

On cold boot, `booster_drop_reconcile_task` (a `count=1` loop) runs `_expire_previous_booster_drop` once so a `booster_drop_message_id` left set by a crash is resolved immediately, instead of waiting up to ~4h for the next drop to expire it lazily.

Channel access is restricted to the Server Booster role via manual Discord permission setup — the bot only needs the channel ID.

### Persistent claim button (all drop types)

The supply (`/drop` and the auto `supply_drop_task`), booster, and admin drops all share one claim button, `DropClaimButton` — a `discord.ui.DynamicItem` whose `custom_id` is `drop_claim:{amount}`. It's re-registered once in `Economy.cog_load` via `bot.add_dynamic_items(DropClaimButton)`, so a drop message posted **before** a restart stays claimable (the token amount is recovered from the `custom_id`; the old plain `DropView` had no `custom_id` and was never re-added, leaving pre-restart buttons dead). The single-claim guard is the atomic `claim_drop(message_id, user_id)` (a `$setOnInsert` on the `drop_claims` collection, TTL-expired after 7 days), which replaces the old in-memory `claimed` flag — so it survives restarts and serializes two near-simultaneous clicks. Payout is the atomic `increment_user_balance()` (`$inc`).

---

## Permission System (`/perm`)

A simple allow-list (`allowed_users: set` in-memory) that gates certain admin-like economy commands (e.g. `/set-balance`) for non-Admin users:

```python
allowed_users = set()  # module-level set; reset on restart

# Grant access:
allowed_users.add(user.id)

# Revoke:
allowed_users.discard(user.id)
```

This is volatile — resets on bot restart. It's intended for temporary delegation, not permanent grants.

---

## Excluded Channels

`PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS` in `features/config.py` is a list of channel IDs where the passive `on_message` listener skips token/XP earning. This is used for channels like bot-spam or announcement channels where engagement shouldn't be rewarded.

---

## Source File
`features/economy.py`
