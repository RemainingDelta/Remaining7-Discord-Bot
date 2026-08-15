# Event Management

## Overview
The event management system helps staff manage three colored event channels (Red, Blue, Green). A daily background task at 12:00 AM ET scans these channels for messages older than 7 days and posts a warning — keeping staff ahead of Discord's 14-day bulk-delete limit. Manual cleanup commands wipe channels instantly.

---

## Daily Monitoring Task

A `tasks.loop` fires at 12:00 AM Eastern Time (converted to UTC considering DST):

1. For each event channel (Red, Blue, Green), scans recent message history
2. Finds the oldest message in the channel
3. If that message is **7+ days old**, the task posts (or replaces) a staff alert
4. The alert embed shows: channel name, oldest message timestamp, and how many days until the 14-day bulk-delete limit expires

**Alert replacement**: The task stores the previous alert's message ID. On the next day's run, it deletes the old alert before posting the new one — so stale warnings don't accumulate.

The 7-day threshold gives staff a 7-day window to act before losing the ability to bulk-delete (Discord's limit is 14 days).

---

## Manual Cleanup Commands

`/clear-red`, `/clear-blue`, `/clear-green` each trigger a `ClearChannelView`:

1. Bot posts a confirmation embed with two buttons (Confirm / Cancel)
2. Buttons are dynamically styled to match the channel color (red button for `/clear-red`, etc.)
3. On Confirm: `await channel.purge()` deletes all messages in the channel
4. On Cancel: interaction is acknowledged with no action

`ClearChannelView` uses `timeout=30` — if no response in 30 seconds, the buttons are disabled.

---

## Event Rewards (`/event-rewards <message_id>`)

Distributes tokens to winners listed in a specific message. Expected message format (one per line):

```
@Username1 500
@Username2 300
@Username3 500
```

Bot flow:
1. Fetches the message by ID from the current channel
2. Parses each line with a regex: `@mention + integer`
3. Displays a confirmation embed listing all recipients and amounts
4. On confirm, pays each recipient through the shared `reward_payouts` ledger in a **claim → pay → commit** sequence: `claim_reward_payout(..., source="event")` → `increment_user_balance` → `mark_reward_paid`
5. Posts a final embed confirming distribution

This flow (v1.12.0) is **crash-safe** — a crash-and-retry never double-pays, because a recipient already claimed in the ledger is skipped on re-run. A cold-boot `reconcile_reward_payouts` task recovers stuck claims (rows claimed but never confirmed paid), and `/check-stuck-payouts [resolve]` lets an admin list or resolve those stuck payouts.

---

## Poll Rewards (`/poll-rewards <message_id>`)

Distributes tokens to all users who voted on a Discord poll:

1. Fetches the poll message by ID
2. Reads all reactions (or poll voters depending on Discord.py version)
3. Collects unique non-bot voter IDs
4. Distributes a fixed token amount to each (amount configured as command parameter or hardcoded), claiming each voter in the shared per-voter `reward_payouts` ledger (`source="poll"`) before crediting — so a crash-and-retry never double-pays an individual voter
5. Checks `processed_poll_rewards` MongoDB collection to prevent double-paying the same poll (a fast-path whole-message gate that sits above the per-voter ledger)
6. Logs the processed poll ID to prevent future duplicates

---

## `/event-staff-help`

Posts a help embed in-channel listing all event management commands, their syntax, and brief descriptions. Visible only in the staff channel.

---

## Source File
`features/event.py`
