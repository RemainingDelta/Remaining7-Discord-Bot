# Tournament Tickets

## Overview
Tournament tickets are private Discord text channels created when a member submits the ticket modal during a live or pre-tournament session. Each ticket stores its metadata (opener ID, team, bracket number, issue) in the channel topic as a pipe-delimited string. The system enforces per-user limits, supports auto-translation, and generates a plain-text transcript on deletion.

---

## Ticket Creation Flow

1. Member clicks the **Open Ticket** button on the tourney panel
2. A Discord modal appears with three fields:
   - Team Name
   - Match / Bracket Number
   - Issue description
3. On submit, `create_tourney_ticket_channel()` runs:
   - Defers the response (ephemeral) immediately to buy time
   - Checks that the active category has **< 50 channels** (Discord's hard limit)
   - Calls `_check_ticket_limits_for_user()` — max 3 open tickets, 180s cooldown
   - Allocates the next ticket number via `get_next_ticket_number()`
   - Creates a text channel named `「❗」ticket-NNN` at **position 0** (top of category)
   - Sets permission overwrites: opener gets full access + slash commands; all `ALLOWED_STAFF_ROLES` get full access + manage messages; `@everyone` is hidden
   - Writes the channel topic: `tourney-opener:{user_id}|team:{team}|bracket:{num}|issue:{issue}`
   - Auto-detects and translates the issue text if non-English
   - Sends the ticket embed + a "proof required" embed
   - Checks the opener against the blacklist and alerts admins if flagged

### Channel Naming Convention
| State | Name Format |
|-------|-------------|
| Active | `「❗」ticket-001` |
| Closed | `「👍」ticket-001` |

---

## Channel Topic Format

All ticket metadata lives in the channel topic as a pipe-delimited key:value string:

```
tourney-opener:123456789|team:Fire Boys|bracket:7|issue:No show opponent
```

Parsed wherever needed:
```python
for part in channel.topic.split("|"):
    key, _, value = part.partition(":")
```

This is the source of truth for the opener ID (used for permission restore on reopen and DM on delete), team name (used for Matcherino fuzzy matching), and bracket number (used by the 1-minute match refresher).

---

## Rate Limiting

Limits are enforced in-memory (reset on bot restart) in `tourney_utils.py`:

```python
_user_open_tickets: dict[int, set[int]] = {}
_user_last_ticket_open_time: dict[int, datetime] = {}
```

`_check_ticket_limits_for_user()` checks both:
1. **Max open tickets**: Default 3. Test Mode raises to 100.
2. **Cooldown**: Default 180 seconds between opens. Test Mode drops to 0.1 seconds.

Test Mode is read live from `config.TOURNEY_TEST_MODE` on every check so it can be toggled at runtime without restarting.

Category capacity is checked separately — if the active category hits 50 channels (Discord's hard limit per category), the bot rejects the creation with a "System Full" error.

---

## Auto-Translation

When a ticket is created, the issue field is passed through `_get_translation()`:

```python
async def _get_translation(text: str) -> str | None:
    detected = await asyncio.to_thread(detect, text)  # langdetect
    if detected == "en":
        return None
    translated = await asyncio.to_thread(
        GoogleTranslator(source="auto", target="en").translate, text
    )
    return translated
```

Both the `detect()` and `translate()` calls are run in a thread pool (`asyncio.to_thread`) so they don't block the async event loop. If a translation is produced, it appears as an additional embed field in the ticket.

---

## Blacklist Check on Open

After creating the channel, `check_and_alert_blacklist()` runs:
1. Queries MongoDB `blacklist` collection for the opener's Discord ID
2. If found, sends an embed to `TOURNEY_ADMIN_CHANNEL_ID` pinging `@Tourney Admin` with the ban reason, date, Matcherino profile, and known alts

This is non-blocking — the ticket opens regardless.

---

## Closing a Ticket

`close_ticket_via_command()` (triggered by `!close` or `!c`):

1. Checks the caller has a staff role
2. Determines destination category (Closed) based on current category (Active)
3. Checks if the Closed category is at its 40-channel soft limit; if so, auto-deletes the oldest closed tickets to make room
4. Moves the channel to the Closed category
5. Parses the channel topic to extract `opener_id`, then calls `_unregister_ticket_for_user()` to release one slot from the user's open count
6. Renames the channel in the background (`「👍」ticket-NNN`) via `asyncio.create_task` — non-blocking
7. Strips `send_messages` from every non-staff member overwrite (opener + anyone `/add`ed)
8. Restores full send access for all staff roles
9. Sends a close message with a `DeleteTicketView` button

**Closed category soft limit (40)**: When the closed category fills, the bot sorts existing closed tickets by `created_at` (oldest first) and auto-deletes them with transcript until there's space for the incoming one.

---

## Deleting a Ticket (with Transcript)

`delete_ticket_with_transcript()` handles both button and command deletion:

1. Validates the channel is in a valid tourney category (active or closed)
2. Extracts `opener_id` from topic
3. Calls `_unregister_ticket_for_user()` to release the slot
4. Builds a plain-text transcript via `build_transcript_text()`
5. Creates two `io.BytesIO` copies of the transcript (one for DM, one for log channel) — must be separate because `discord.File` is single-use
6. DMs the transcript to the opener (if findable via `client.get_user()` or `client.fetch_user()`)
7. Posts the transcript to `LOG_CHANNEL_ID` with metadata extracted from the topic (team name, match number)
8. Calls `channel.delete()`

### Transcript Format

The plain-text transcript has a header block then chronological messages:

```
Team: Fire Boys
Match Number: 7
Issue: No show opponent

[2026-06-21 14:32] SomeUser#1234 (123456789): Hi, the other team isn't showing up
[2026-06-21 14:33] StaffMember#5678 (987654321): We'll look into it now
```

Translation embeds are parsed and formatted as:
```
[14:33] R7 Bot#9997 (Spanish >> English): "Hola" >> "Hello"
```

---

## Reopening a Ticket

`reopen_tourney_ticket()` and `reopen_ticket_via_command()`:

1. Validates the channel is in a Closed category
2. Checks the Active category is not at 50 channels
3. Moves the channel back to the Active category and sets `position=0` (top of queue)
4. Parses topic for `opener_id`, re-registers with `_register_ticket_for_user()`
5. Renames the channel back to `「❗」ticket-NNN` in the background
6. Restores `send_messages=True` for the opener via `channel.set_permissions()`
7. Sends a "Ticket Reopened" embed mentioning the opener

---

## Ticket Counters

Two independent in-memory counters, reset on `!starttourney`:

```python
_ticket_counter: int = 1           # live tourney tickets
_pre_tourney_ticket_counter: int = 1  # pre-tourney tickets
```

Both wrap back to 1 after 999. `reset_ticket_counter()` is called during `!starttourney` to reset the live counter. The pre-tourney counter resets independently.

---

## Source Files
- `features/tourney/tourney_utils.py` — all ticket lifecycle logic
- `features/tourney/tourney_views.py` — UI components (buttons, modals)
- `features/tourney/tourney_commands.py` — `!close`, `!delete`, `!reopen`
