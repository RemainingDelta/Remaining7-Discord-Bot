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
1. A staff member or admin posts the panel with `/event-ticket-panel` (restricted to
   `EVENT_TICKET_PANEL_CHANNEL_ID` when that ID is configured).
2. A member clicks the **🎫 Open Event Ticket** button (`custom_id="event_open_ticket"`).
3. `create_event_ticket_channel()` runs:
   - Rejects the request if the member already has an **open** event ticket (**one open
     ticket per user at a time**), pointing them at their existing channel. Closed
     (`「👍」`) tickets do not block a new one, so a member can open another ticket once
     staff have closed the previous one.
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
Three IDs, set in **both** the PROD and DEV blocks. Every guard treats `0` as
"not configured" and disables the feature rather than raising, so a value missing
from one branch leaves event tickets silently inert on that server:

| Constant | Purpose |
|----------|---------|
| `EVENT_TICKET_PANEL_CHANNEL_ID` | Channel the `/event-ticket-panel` button lives in |
| `EVENT_TICKET_CATEGORY_ID` | Category new ticket channels are created in |
| `EVENT_TICKET_TRANSCRIPT_CHANNEL_ID` | Channel transcripts are logged to on deletion |

Staff access is gated on `EVENT_STAFF_ROLE_ID` **or** `ADMIN_ROLE_ID`. Both come from
the one `_event_staff_role_ids()` set, so either role grants the panel command, access
to every ticket channel, and `!close` / `!reopen` / `!delete`. An admin can therefore
read every event submission.

---

## Auto-posted panel channel

`EVENT_TICKET_PANEL_CHANNEL_ID` (`features/config.py`, both branches) holds the panel.
`main.py` calls `repost_event_ticket_panel(bot)` from `on_ready`, after the privacy
repost and before the command sync.

The flow:

1. If `EVENT_TICKET_PANEL_CHANNEL_ID` is falsy (`0` = not set up on this server yet),
   log a warning and return. Startup is never blocked by an unconfigured channel.
2. If the panel has already been reposted in this process, return.
3. Resolve the channel; skip if it is missing or not a `TextChannel`.
4. Skip if the bot lacks **Manage Messages** there — posting without being able to clear
   the channel would stack another panel on every restart.
5. Clear the channel with `channel.purge(limit=None)`, falling back to individual
   deletes when Discord refuses a bulk delete (anything older than 14 days).
6. Post `build_event_panel_embed(bot.user)` with a fresh `EventTicketPanelView()`.

This is the repost-on-restart pattern from `repost_privacy_policy()`. The embed is
**rebuilt from source** rather than re-sent from the message it replaces, which is how
`restore_tourney_panels()` does it — that version keeps a stale copy forever, so an edit
to the panel wording never reaches the channel.

Unlike the privacy repost, this deletes messages from **every** author, not just the
bot's. The channel is expected to hold nothing but the panel, so it should be locked to
members.

The repost is guarded to once per process: `on_ready` re-fires on every gateway
reconnect, and a reconnect is not a restart.

---

## Source Files
- `features/event_tickets.py` — all event-ticket logic, UI, and the cog.
- `features/ticket_command_router.py` — routes `!close`/`!delete`/`!reopen` to it.
- `main.py` — loads the extension.
