# Token System

## Overview
R7 Tokens are the primary server currency. Members earn them passively through chat messages and via `/daily` claims. The passive listener runs on every `on_message` event and enforces a per-user cooldown tracked in an in-memory dict. Server Boosters receive a ~10% average bonus on passive token earnings, a passive XP bonus in the general channel, a flat +20 tokens on every `/daily` claim, and a once-monthly 10% shop discount (see `ECONOMY_SHOP.md`).

> When changing any booster perk here, also update the `/booster-perks` embed in `features/general.py`.

---

## Passive Earning

The `on_message` listener in `features/economy.py` fires on every message. Token earning, XP earning, daily message count tracking, and quest progress apply identically in the general channel (`GENERAL_CHANNEL_ID`) and the booster-only channel (`BOOSTER_CHANNEL_ID`, `#general-plus`) — no rewards are granted outside these two channels:

1. Ignores bots, DMs, and channels in `PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS`
2. Enforces a **20-second cooldown** per user via `_cooldowns: dict[int, float]` mapping `user_id → last_earn_timestamp`
3. Awards a random amount of `2–5 tokens` (`random.randint(2, 5)`)
4. If the member has the **Server Booster** role (`SERVER_BOOSTER_ROLE_ID`), there is a 35% chance of +1 bonus token (~10% average increase). Boosters also roll a separate 35% chance of +1 bonus XP on every general/booster-channel message, independent of the token cooldown.
5. Updates balance in MongoDB via `update_user_balance()`
6. Fires the quest listener (`process_quest_update()`) for the message action

The cooldown is checked against `time.time()` — no database reads involved, making this path very fast.

---

## Daily Reward (`/daily`)

```
Tokens = 80 + (level * 5) capped at 160
```

Requires:
- 24-hour cooldown since last claim (stored in `users.daily_last_claimed`)
- At least **5 messages sent** since the last daily (tracked in `users.daily_message_count`)

On claim:
1. Reads `daily_last_claimed` from MongoDB
2. Checks `daily_message_count >= 5`
3. Calculates token reward based on user's current level
4. Adds a flat **+20 tokens** if the member has the Server Booster role (shown as a separate line in the claim embed)
5. Resets `daily_message_count` to 0 and updates `daily_last_claimed` to now

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
2. Posts an embed with a claim button (`DropView`) — first booster to click gets the tokens; staff cannot claim
3. Stores the active drop's message ID in the `settings` collection under `booster_drop_message_id`; claiming clears it
4. When a new drop fires, the previous **unclaimed** drop message is edited to an EXPIRED state with the button removed; claimed drops keep their CLAIMED state

Channel access is restricted to the Server Booster role via manual Discord permission setup — the bot only needs the channel ID.

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
