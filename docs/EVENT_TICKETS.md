# Event Tickets

## Overview
Event tickets are private Discord text channels members open to submit their answer
for an event, replacing the old flow of DMing event staff directly. Each ticket is a
channel in the configured event-ticket category; the opener's ID is stored in the
channel topic. Event staff can see and manage every open ticket. On deletion the bot
saves a transcript to a dedicated event transcript channel and DMs a copy to the opener.

Implemented in `features/event_tickets.py` (a self-contained cog), wired into the shared
`!close`/`!delete`/`!reopen` router in `features/ticket_command_router.py`.

---

## Creation Flow
1. A staff member posts the panel with `/event-ticket-panel` (restricted to
   `EVENT_TICKET_PANEL_CHANNEL_ID` when that ID is configured).
2. A member clicks the **🎫 Open Event Ticket** button (`custom_id="event_open_ticket"`).
3. `create_event_ticket_channel()` runs:
   - Rejects the request if the member already has an open event ticket (**one ticket
     per user at a time**), pointing them at their existing channel.
   - Creates a private text channel named `「❗」event-<username>`, where `<username>` is
     the opener's Discord username sanitized to Discord's channel-name charset (lowercase,
     `[a-z0-9-]`, hyphen-collapsed; falls back to the user ID if nothing usable remains).
   - Permission overwrites: `@everyone` hidden; the opener gets full access; every
     `EVENT_STAFF_ROLE_ID` role gets full access plus manage-messages.
   - Writes the channel topic `event-opener:<user_id>` (the source of truth for the
     opener, used by close/reopen/delete).
   - Posts a submission-prompt embed that **pings the opener** via `content=` (an embed
     field alone would not notify them).

### Channel Naming
| State | Name |
|-------|------|
| Open | `「❗」event-<username>` |
| Closed | `「👍」event-<username>` |

---

## Closing (in place)
`!close`/`!c` or the **Delete/Reopen** buttons route through
`route_shared_ticket_command`. Closing:
- Locks the opener to read-only (`send_messages=False`).
- **Flips the emoji prefix** `「❗」` → `「👍」` — the channel is **not** moved to another
  category.
- Posts a close message carrying the `EventClosedTicketView` (Delete / Reopen buttons).

Reopening restores the opener's send permission and flips the prefix back.

---

## Deleting (with transcript)
`!delete`/`!del` or the **Delete Ticket** button:
1. Builds a plain-text transcript of the channel history.
2. DMs the transcript to the opener (skipped silently if their DMs are closed).
3. Posts the transcript to `EVENT_TICKET_TRANSCRIPT_CHANNEL_ID` (when configured).
4. Deletes the channel.

---

## Configuration (`features/config.py`)
Three IDs must be set in **both** the PROD and DEV blocks before the feature works
(they ship as `0` placeholders):

| Constant | Purpose |
|----------|---------|
| `EVENT_TICKET_PANEL_CHANNEL_ID` | Channel the `/event-ticket-panel` button lives in |
| `EVENT_TICKET_CATEGORY_ID` | Category new ticket channels are created in |
| `EVENT_TICKET_TRANSCRIPT_CHANNEL_ID` | Channel transcripts are logged to on deletion |

Staff access is gated on the existing `EVENT_STAFF_ROLE_ID`.

---

## Source Files
- `features/event_tickets.py` — all event-ticket logic, UI, and the cog.
- `features/ticket_command_router.py` — routes `!close`/`!delete`/`!reopen` to it.
- `main.py` — loads the extension.
