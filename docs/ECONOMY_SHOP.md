# Economy Shop

## Overview
The shop lets members spend R7 Tokens on real-world rewards. Redemptions open a private ticket channel where staff fulfill the order. Each fulfilled redemption reduces the monthly USD budget. Open (pending) tickets also reserve budget: the available budget is `monthly_budget − spent − pending`, so redemptions can never collectively exceed the cap. Requests that don't fit the available budget can be queued for the next month instead. The budget auto-resets on the first of each calendar month by detecting a month key change.

---

## Shop Data

All items are defined in `SHOP_DATA` in `features/config.py`. Each entry looks like:

```python
"brawl pass": {
    "display": "**Brawl Pass**",
    "price": 5000,        # R7 token cost
    "description": "..."
}
```

Token prices are read via `_token_price_for_item(item_name)`. USD budget costs per item are defined separately in `REDEMPTION_BUDGET_COSTS`:

```python
REDEMPTION_BUDGET_COSTS = {
    "brawl pass": 10.0,
    "brawl pass+": 15.0,
    "coc gold pass": 7.0,
    "cr diamond pass": 12.0,
    "nitro": 10.0,
    "paypal": 15.0,
    "matcherino pin": 5.0,
    "pin": 5.0,
    "shoutout": 0.0,
}
```

---

## Redemption Flow

1. Member uses `/redeem` and selects an item they own
2. Bot checks the **available budget**: `monthly_budget − manual_total_spent − pending`, where pending is computed by `_pending_redemptions_total()` — it scans the redemption category's channel topics and sums each ticket's `budget_usd` (falling back to `REDEMPTION_BUDGET_COSTS` if the topic value is missing/corrupt)
3. If the item's USD cost exceeds the available budget, the member is offered the **redemption queue** (see below) instead of a ticket
4. Otherwise the item is consumed and `create_redemption_ticket()` opens a private ticket channel in `REDEMPTION_TICKET_CATEGORY_ID`:
   - Channel topic: `redemption-opener:{user_id}|item:{item_key}|budget_usd:{cost}`
   - Opener gets full access + slash commands; Admin/Mod roles get full access
5. Ticket shows the item requested, token cost deducted, and remaining balance

The budget guard is re-checked once after the interaction defer, so two near-simultaneous redemptions can't both claim the last of the budget.

### Redemption Ticket Resolution

When staff close a redemption ticket, a `RedemptionClosedOptionsView` appears with three buttons:

| Button | Action |
|--------|--------|
| **Reopen** | Restores opener's send permissions |
| **Give back tokens and delete** | Refunds `_token_price_for_item(item)` tokens to the opener, saves transcript with `outcome="refunded"`, deletes the channel |
| **Reduce from budget and delete** | Adds item's USD cost to `manual_total_spent` via `add_budget_spent()`, saves transcript with `outcome="fulfilled"`, deletes the channel |

The budget cost on the "Reduce from budget" path is read from `budget_usd` in the topic first (set at creation), falling back to `_budget_cost_for_item(item)` from the `REDEMPTION_BUDGET_COSTS` dict. This allows manual override by editing the topic.

`!delete` is explicitly disabled for redemption tickets — staff must use `!close` first and then choose a button outcome.

---

## Monthly Budget System

The budget state lives in the `settings` MongoDB collection as these keys:

| Key | Value |
|-----|-------|
| `budget_month_key` | `"YYYY-MM"` string for the current month |
| `monthly_budget` | Total cap as float string (default `"50.00"`) |
| `manual_total_spent` | Cumulative USD spent this month as float string |
| `redemption_queue_processed_month` | `"YYYY-MM"` of the last month whose queue run completed |

`ensure_monthly_budget_state()` runs on every budget interaction:
```python
current_key = datetime.utcnow().strftime("%Y-%m")
stored_key = await get_setting("budget_month_key")
if stored_key != current_key:
    # New month — reset everything
    await set_setting("budget_month_key", current_key)
    await set_setting("monthly_budget", "50.00")
    await set_setting("manual_total_spent", "0.00")
    # Also resets legacy per-item counters
```

This is lazy reset — it only resets when something touches the budget, not on a scheduled task. The hourly redemption-queue task (below) touches the budget at the start of every month, so in practice the reset also happens within an hour of rollover.

---

## Redemption Queue

When a `/redeem` request exceeds the available budget, the member gets an ephemeral prompt with **Join queue for next month** / **Cancel** buttons (`RedemptionQueueConfirmView`). Confirming consumes the item token immediately and inserts a FIFO entry into the `redemption_queue` MongoDB collection:

```python
{
  "user_id": "1234567890",   # str, matches users collection convention
  "item": "brawl pass",      # SHOP_DATA key
  "budget_usd": 10.0,        # snapshot at queue time (audit/display only)
  "queued_at": datetime,     # FIFO sort key
}
```

`budget_usd` is a snapshot for display; processing always recomputes the cost from `REDEMPTION_BUDGET_COSTS` so a cost change while queued uses the current value.

### Processing

`redemption_queue_task` is an hourly `tasks.loop` on the Economy cog. Each tick it compares `redemption_queue_processed_month` with the current month key; if they differ (new month, or bot was offline on the 1st), it runs `process_redemption_queue()` and stamps the key only on success (a failed run retries next hour).

`process_redemption_queue()` walks the queue in FIFO order:
- **Member left the server** → entry is dropped, the item's token price is refunded to their balance, and a note is posted to `REDEMPTION_TRANSCRIPT_CHANNEL_ID`.
- **Cost > available budget** (recomputed every iteration, so tickets opened earlier in the run count as pending) → entry is skipped and carries over to the next month; cheaper later entries may still be fulfilled.
- **Otherwise** → a ticket is created via `create_redemption_ticket()` (pinging the member) and the entry is removed — only after the channel is successfully created, so failures leave the entry queued.

### Queue Commands

| Command | Who | Notes |
|---------|-----|-------|
| `/redemption-queue` | Anyone | Your queued redemptions with overall FIFO position (ephemeral) |
| `/redemption-queue-list` | Admin/Mod | Full queue with entry ids and estimated USD total |
| `/redemption-queue-remove <entry_id>` | Admin/Mod | Removes an entry and returns the item to the user's inventory |

`/check-budget` also shows the pending-ticket total and the queued-entry count/estimate.

---

## Redemption Transcript

When a redemption ticket is deleted (either path), `_save_redemption_transcript()` saves a full log:

- Header: channel name, opener ID, item, token cost, balance before/after
- Chronological message history with timestamps
- Outcome line: either `✅ Fulfilled | Balance: X → Y` or `🔄 Refunded | Balance: X → Y → Z` (the refund path shows three values since tokens go: original → deducted → refunded)

Transcript is posted to `REDEMPTION_TRANSCRIPT_CHANNEL_ID`.

---

## Source File
`features/economy.py`
