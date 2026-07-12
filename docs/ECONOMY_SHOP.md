# Economy Shop

## Overview
The shop lets members spend R7 Tokens on real-world rewards. Redemptions open a private ticket channel where staff fulfill the order. Each fulfilled redemption reduces the monthly USD budget. The budget auto-resets on the first of each calendar month by detecting a month key change.

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

1. Member uses `/redeem` and selects an item
2. Bot checks their token balance ≥ item price
3. Deducts tokens immediately via `update_user_balance()`
4. Creates a private ticket channel in `REDEMPTION_TICKET_CATEGORY_ID`:
   - Channel topic: `redemption-opener:{user_id}|item:{item_key}|budget_usd:{cost}`
   - Opener gets full access + slash commands; Admin/Mod roles get full access
5. Ticket shows the item requested, token cost deducted, and remaining balance

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

The budget state lives in the `settings` MongoDB collection as three keys:

| Key | Value |
|-----|-------|
| `budget_month_key` | `"YYYY-MM"` string for the current month |
| `monthly_budget` | Total cap as float string (default `"50.00"`) |
| `manual_total_spent` | Cumulative USD spent this month as float string |

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

This is lazy reset — it only resets when something touches the budget, not on a scheduled task.

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
