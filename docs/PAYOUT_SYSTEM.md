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

Internally, `add_payout_batch()` is **crash-safe**. It derives a deterministic `batch_id` (sha1 of the sorted `user_ids` + per-person amount + reason, truncated), does an idempotent upsert into `payout_logs` keyed on `batch_id` (so a re-run of the identical batch does not append a duplicate log row), and claims each recipient in the shared `reward_payouts` ledger (`source="payout"`) **before** applying the `$inc` to their `payouts` doc. As a result, re-running an identical `/payout-add` after a mid-loop crash credits only users who were never reached and never double-pays.

**Trade-off:** two intentionally-identical payouts (same users, same per-person amount, same reason) hash to the same `batch_id`, so the second is treated as a retry and skipped. Vary the reason to force a distinct batch.

---

## `/payout-list`

Reads all documents from the `payouts` collection where `amount > 0` (queries `{"amount": {"$gt": 0}}`; pending/unpaid). Displays as an embed listing each staff member and their owed balance.

---

## `/payout-history [page]`

Reads from `payout_logs` — the full audit trail of every payout batch that has been recorded. Paginated, 10 per page. Filters out users whose balance has been reset (they appear in logs as historical records but are excluded from the "outstanding" view).

---

## `/payout-reset`

Clears a staff member's pending balance:

1. Reads current balance from `payouts`
2. Sets `amount = 0` and clears `unpaid_batches` on the payouts doc (via `clear_pending_payout`)

No log or "settled" record is written to `payout_logs`. This is the "I paid them" action. After reset, the staff member no longer appears in `/payout-list`.

---

## Data Model

### `payouts` collection
```json
{
  "_id": "user_discord_id",
  "amount": 75.00,
  "unpaid_batches": ["batch_id_1", "batch_id_2"]
}
```

### `payout_logs` collection
```json
{
  "batch_id": "sha1-derived-id",
  "timestamp": "2026-06-21T00:00:00Z",
  "amount": 50.0,
  "user_ids": ["123", "456"],
  "reason": "Tournament staffing"
}
```

---

## Source File
`features/tourney/tourney_commands.py` — `PayoutResetConfirmView` and payout slash commands
