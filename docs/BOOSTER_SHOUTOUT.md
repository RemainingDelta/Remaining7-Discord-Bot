# Booster Shoutout Tickets

## Overview
When a member starts boosting the server, the bot automatically opens a private ticket where the booster can write a message to be featured in the announcements channel. Staff review the message and manually post a link to it in announcements — Discord renders message links natively with the author's username and avatar, so no bot-side posting is needed. There is no content enforcement; moderation is entirely at staff discretion.

Source: `features/booster_shoutout.py`

---

## Boost Detection

The `BoosterShoutout` cog listens on `on_member_update` and fires when `premium_since` transitions from `None` to a datetime (`_is_new_boost()`). Adding a *second* boost does not change `premium_since`, so only the first active boost triggers a ticket.

The `Server Members` intent (already enabled in `main.py`) is required for this event.

---

## Once-Per-Month Guard

A ticket is created at most once per calendar month per user:

- The month key is `datetime.utcnow().strftime("%Y-%m")` (same convention as the booster shop discount).
- Stored per-user in `users.booster_shoutout_month` via `get_booster_shoutout_month()` / `set_booster_shoutout_month()` in `database/mongo.py`.
- The marker is set **after** successful channel creation, so a failed creation (e.g. category full, API error) can retry on a later boost in the same month.
- The marker is never cleared on close/delete — a ticket opened this month blocks new ones regardless of its current state.

---

## Ticket Channel

- Created in the **Booster Shoutouts** category (`BOOSTER_SHOUTOUT_CATEGORY_ID` in `features/config.py`).
- Named `「❗」shoutout-NNN` using the shared `support_ticket_counters` MongoDB collection (`_id = "booster_shoutout"`).
- Topic stores the opener: `booster-opener:{user_id}|type:booster_shoutout`.
- Permissions: `@everyone` hidden; the booster can view/send/attach; Admin and Moderator roles get full access with `manage_messages`.
- A welcome embed explains the flow and that the booster can ask staff to close the ticket to opt out.

---

## Lifecycle (Staff-Only)

Close, reopen, and delete are **staff-only** (Admin + Moderator) — the booster cannot close their own ticket; they opt out by saying so in the ticket and staff close it. This intentionally deviates from the original issue spec ("booster closes to opt out") per maintainer decision.

- `!close` — revokes the booster's send permission, renames to `「👍」shoutout-NNN`, posts a message with the persistent `BoosterShoutoutClosedView` (Delete / Reopen buttons).
- `!reopen` (or the Reopen button) — restores send permission and the `「❗」` prefix.
- `!delete` (or the Delete button) — builds a plain-text transcript, DMs it to the booster, posts it to `SUPPORT_TRANSCRIPT_LOG_CHANNEL_ID`, then deletes the channel.

Prefix commands are dispatched through `features/ticket_command_router.py` (`is_booster_shoutout_ticket_channel()`), the same mechanism used by support and redemption tickets — see `docs/TICKET_ROUTER.md`.

The closed view is re-registered in `cog_load()` via `bot.add_view()` so buttons keep working across restarts.
