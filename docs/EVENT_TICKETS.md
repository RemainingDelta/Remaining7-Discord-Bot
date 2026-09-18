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
1. Builds the transcript in a single pass over the channel history: the plain-text
   log, plus the bytes of up to **25 images** posted in the ticket.
2. DMs the transcript and its images to the opener (skipped silently if their DMs
   are closed).
3. Posts the same set to `EVENT_TICKET_TRANSCRIPT_CHANNEL_ID` (when configured).
4. Deletes the channel.

### Why images are re-uploaded, not linked
Discord attachment URLs are signed and expire within about a day, and deleting the
channel makes the originals collectable — so a transcript that only linked a
screenshot would be dead by the time anyone read it. `_build_transcript()` downloads
the bytes while the channel still exists and re-uploads them alongside the `.txt`.
This is the same reasoning `features/github_tickets.py` uses for inlining log files.

An attachment is downloaded only if all of these hold:

| Rule | Why |
|------|-----|
| Fewer than 25 images collected so far | A policy cap on how much of a ticket is worth keeping — collection is oldest-first, so a busier ticket keeps its earliest images |
| Extension in `.png` / `.jpg` / `.jpeg` / `.webp` | Same list as `features/scam_detection.py`; `.gif` is excluded |
| Under `_MAX_IMAGE_BYTES`, and the running total under `_MAX_TOTAL_IMAGE_BYTES` | Memory guards while downloading — deliberately **not** Discord upload limits |
| `attachment.read()` succeeds | The file may already be gone |

### Delivery adapts instead of predicting
`guild.filesize_limit` is deliberately **not** used. It is a stale local constant
discord.py never enforces on send, and Discord's real limit is variable — the live
value is reported only on interactions, as `attachment_size_limit`. Using it as a
download budget capped transcripts at four images regardless of the 9-image limit.

Two independent ceilings apply, and Discord reports them differently:

| Ceiling | How Discord says no | How delivery handles it |
|---------|--------------------|-------------------------|
| More than 10 attachments in a message | `400` | Known up front, so `_send_transcript()` chunks the payload by count before sending |
| Too many bytes in a message | `413` | Not knowable up front, so `_send_one_message()` attempts the send and halves on rejection |

The 413 path deliberately does not retry a `400`, which is why the count has to be
respected in advance rather than discovered: an over-long message would otherwise
be swallowed and lose the transcript entirely.

So `_send_one_message()` attempts one chunk with everything, and splits only when
Discord answers `413`, halving and retrying until each part is accepted. This is
correct whether the limit is 10 MB or 20 MB, per file or per payload: if it all
fits, it is one message; if not, Discord says so. Files are rebuilt from bytes on
each attempt, since a `discord.File` wraps a single-use stream. A file rejected
even on its own is dropped and logged. Any non-413 error is not retried.

Anything skipped still has its filename and URL in the transcript text, under
"Not attached (links above expire)", so nothing disappears without a trace. Image
filenames are prefixed (`01-shot.png`) so two `image.png` from different messages
stay distinguishable. A failed upload never blocks the channel deletion.

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
