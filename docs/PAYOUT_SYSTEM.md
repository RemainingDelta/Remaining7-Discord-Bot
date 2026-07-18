# Payout System

## Overview
The payout system tracks USD compensation owed to tournament staff. Payouts accumulate in the `payouts` collection and are archived to `payout_logs` when cleared. All commands are staff-only and can only be used in the admin channel.

---

## `/payout-add <users...> <amount>`

Records a payout for one or more staff members.

**Split mode** (default when multiple users): The `amount` is divided equally among all listed recipients.
```
/payout-add @Alice @Bob @Carol 150
→ Alice: $50, Bob: $50, Carol: $50
```

**Flat mode**: Each recipient receives the full `amount` individually.
```
/payout-add @Alice @Bob 50 flat
→ Alice: $50, Bob: $50
```

Internally, `add_payout_batch()` upserts each user's balance in the `payouts` collection (adds to existing balance, doesn't overwrite) and inserts a batch record in `payout_logs`.

---

## `/payout-list`

Reads all documents from the `payouts` collection where `balance > 0` (pending/unpaid). Displays as an embed listing each staff member and their owed balance.

---

## `/payout-history [page]`

Reads from `payout_logs` — the full audit trail of every payout batch that has been recorded. Paginated, 10 per page. Filters out users whose balance has been reset (they appear in logs as historical records but are excluded from the "outstanding" view).

---

## `/payout-reset`

Clears a staff member's pending balance:

1. Reads current balance from `payouts`
2. Writes a final "settled" record to `payout_logs` with `outcome: "paid"`
3. Sets `balance = 0` (or deletes the document) in `payouts`

This is the "I paid them" action. After reset, the staff member no longer appears in `/payout-list`.

---

## Data Model

### `payouts` collection
```json
{
  "_id": "user_discord_id",
  "user_name": "StaffMember",
  "balance": 75.00
}
```

### `payout_logs` collection
```json
{
  "batch_id": "uuid",
  "users": [
    {"user_id": "123", "name": "Alice", "amount": 50.0},
    {"user_id": "456", "name": "Bob", "amount": 50.0}
  ],
  "mode": "split",
  "total": 100.0,
  "timestamp": "2026-06-21T00:00:00Z"
}
```

---

## Source File
`features/tourney/tourney_commands.py` — `PayoutResetConfirmView` and payout slash commands
