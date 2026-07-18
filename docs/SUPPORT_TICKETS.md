# Support Tickets

## Overview
The support ticket system provides four types of private help channels for members. Each type has its own Discord category, independent auto-incrementing counter, and ticket panel button. Staff manage tickets with the same `!close`, `!delete`, `!reopen` commands as tourney tickets — these are routed by `ticket_command_router.py`.

---

## Ticket Types and Categories

| Type Key | Name | Purpose | Category |
|----------|------|---------|---------|
| `bug` | Report an Issue | Bugs, violations, technical problems | Separate issue category |
| `support` | Server Support | General assistance | Separate support category |
| `staff_app` | Staff Application | Event Staff applications (Tourney Admin / Moderator closed, shown struck through) | Separate applications category |
| `partnership` | Server Partnership | Partnership proposals | Separate partnership category |

---

## Ticket Panel

`/support-panel` posts a single embed with four buttons, one per ticket type. Each button opens a modal asking for a brief description of the request.

---

## One-Per-Type Enforcement

A user can only have one open ticket per ticket type at a time. This is tracked in the `support_ticket_counters` collection and per-user state. If a user tries to open a second ticket of the same type, they receive an ephemeral error pointing them to their existing ticket.

---

## Auto-Increment Counters

Each ticket type has an independent counter in the `support_ticket_counters` MongoDB collection (also shared with booster shoutout tickets under `_id = "booster_shoutout"` — see `docs/BOOSTER_SHOUTOUT.md`):
- `_id = "bug"`, `_id = "support"`, etc.
- Contains a single `count` field
- Incremented via `$inc: {count: 1}` on each new ticket

Ticket channels are named `support-bug-001`, `support-support-001`, etc. using the counter with zero-padding.

---

## Ticket Creation Flow

1. Member clicks a panel button → modal appears
2. Modal submission creates the channel in the appropriate category:
   - `@everyone` hidden
   - Opener gets view + send + slash commands
   - Admin / Mod roles get full access
3. Channel topic stores: `support-opener:{user_id}|type:{ticket_type}`
4. Opening embed posted with user mention, description, and ticket type

---

## Transcript System

On delete, `build_support_transcript_text()` collects the full channel history into a plain-text file (same format as tourney transcripts). The transcript is:
1. DM'd to the ticket opener (if DMs are open)
2. Posted to the support log channel with metadata (ticket type, opener, ticket number)

---

## Staff Commands (Routed via `ticket_command_router.py`)

| Command | Action |
|---------|--------|
| `!close` / `!c` | Locks the ticket, moves it to the Closed category |
| `!delete` / `!del` | Saves transcript and deletes the channel |
| `!reopen` | Moves ticket back to active category, restores opener send permissions |

These commands are identical to tourney ticket commands because the router dispatches to the support handler when the channel is in a support category.

---

## Source File
`features/support_tickets.py`
