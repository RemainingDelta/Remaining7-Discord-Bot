# Ticket Command Router

## Overview
The ticket command router (`features/ticket_command_router.py`) is a dispatcher that intercepts prefix commands (`!close`, `!delete`, `!reopen`) and routes them to the correct handler based on which Discord category the current channel belongs to. This allows a single set of short commands to work seamlessly across tournament tickets, support tickets, and redemption tickets.

---

## How It Works

`route_shared_ticket_command(ctx, action)` is called at the top of every prefix ticket command before any tourney-specific logic:

```python
@bot.command(name="close", aliases=["c"])
async def close_command(ctx):
    if await route_shared_ticket_command(ctx, "close"):
        return  # handled by router — don't fall through to tourney logic
    # ... tourney-specific close logic follows
```

The function checks the current channel's `category_id` against known category IDs from `features/config.py`:

```python
def get_support_category_ids() -> set[int]:
    return {SUPPORT_TICKET_CATEGORY_ID, REDEMPTION_TICKET_CATEGORY_ID, ...}
```

If the channel is in a support or redemption category, the router dispatches to the appropriate handler and returns `True` (telling the caller to stop). If the channel is in a tourney category, it returns `False` and the caller handles it directly.

---

## Dispatch Table

| Channel Category | Action | Handler Called |
|-----------------|--------|---------------|
| Redemption ticket category | `close` | `close_redemption_ticket_via_command()` in `economy.py` |
| Redemption ticket category | `reopen` | `reopen_redemption_ticket_via_command()` in `economy.py` |
| Redemption ticket category | `delete` | `handle_redemption_delete_attempt()` (blocks with error — use `!close` instead) |
| Support ticket category | `close` | support ticket close handler in `support_tickets.py` |
| Support ticket category | `delete` | support ticket delete handler |
| Support ticket category | `reopen` | support ticket reopen handler |
| Tourney / pre-tourney category | any | router returns `False`, tourney handler takes over |

---

## Why This Pattern

Without the router, each ticket type would need its own set of commands (`!t-close`, `!s-close`, `!r-close`) which would be confusing for staff. The router lets all ticket channels share `!close`, `!delete`, and `!reopen` with context-aware behavior.

---

## Adding a New Ticket Type

1. Add the new category ID to `features/config.py`
2. Register it in `get_support_category_ids()` in `ticket_command_router.py`
3. Add a dispatch branch in `route_shared_ticket_command()` for the new category

---

## Source File
`features/ticket_command_router.py`
