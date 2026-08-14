# Tournament Overview

## Overview
The tournament system orchestrates the full lifecycle of a Brawl Stars tournament on the Remaining7 server. `!starttourney` performs a large coordinated setup across multiple channels, roles, and background tasks. `!endtourney` reverses all of it and generates a stat report. Both commands are restricted to `TOURNEY_ADMIN_CHANNEL_ID`.

---

## `!starttourney [region] [force]`

`force` is an optional flag (e.g. `!starttourney sa force`) — see **Restart / Auto-Resume** below. Without it, `!starttourney` refuses to run when a session is already active.

### What it does (in order)

1. **Validates** caller is staff and command is in the admin channel
2. **Resets** the live ticket counter back to 1 (`reset_ticket_counter()`)
3. **Creates or resets** the active tournament session in MongoDB (`tourney_sessions` collection)
4. **Auto-detects Matcherino ID**: Scans the last 100 messages in `TOURNEY_SCHEDULE_CHANNEL_ID` for a message containing `• Date:` within ±1 day of today. If found, extracts the Matcherino URL with:
   ```python
   re.search(r"matcherino\.com/supercell/tournaments/(\d+)", content)
   ```
   and saves the ID to the active session. If not found, posts a warning telling staff to set it manually with `/set-matcherino`.
5. **Locks** `OTHER_TICKET_CHANNEL_ID` from members via the internal `lock_command()` helper (6-hour auto-reopen timer starts)
6. **SA region mode** (`!starttourney sa`): locks the Spanish support channel (`SPANISH_CHANNEL_ID`) and posts a redirect embed in Spanish pointing members to the main tourney support channel
7. **Main tourney support channel** (`TOURNEY_SUPPORT_CHANNEL_ID`):
   - Sets permissions: `@everyone` can view but not send; staff roles can send
   - Purges all existing messages
   - Posts the live ticket panel embed with `TourneyOpenTicketView` button
   - Renames channel to `「🔴」tourney-support` in the background
8. **Pre-tourney support channel** (`PRE_TOURNEY_SUPPORT_CHANNEL_ID`):
   - Sets permissions: `@everyone` hidden; staff can send
   - Purges all existing messages
   - Renames channel to `「❌❌❌」「🟡」pre-tourney-support` in the background
9. **Deletes all pre-tourney tickets** from both `PRE_TOURNEY_CATEGORY_ID` and `PRE_TOURNEY_CLOSED_CATEGORY_ID` (saves transcripts first)
10. **Grants Tourney Admin role** `moderate_members` permission (ability to timeout members) for the duration of the tournament
11. **Renames Admin role** to `[NOT TOURNEY ADMIN] Admin` so members don't ping the wrong people
12. **Enables 60-second slowmode** on the general channel for 1 hour (auto-removed after 1 hour via `asyncio.sleep(3600)` or on `!endtourney`)
13. **Resets announcement state** (semi-final, finals, winner announcement tracking)
14. **Starts dashboard loops** (queue dashboard every 15s, progress dashboard every 5m) and immediately posts the first progress update

---

## Restart / Auto-Resume

The MongoDB session survives a bot restart, but all runtime state (dashboard loops, the slowmode/lock timers, the SA region redirect, the Admin-role-name memory, and the in-memory ticket counter) is lost when the process dies. To avoid a mid-tourney restart leaving things broken, `!starttourney` persists the recoverable bits onto the active session (`region`, `admin_role_original_name`, and the absolute deadlines `slowmode_ends_at` / `lock_reopens_at`), and a boot-time routine (`resume_tourney_if_active` in `tourney_commands.py`) rehydrates on startup:

- Restarts the queue + progress dashboard loops (idempotent via `start_dashboard()`).
- Rebuilds the live ticket counter by scanning existing ticket channels in `TOURNEY_CATEGORY_ID` / `TOURNEY_CLOSED_CATEGORY_ID` and continuing from the highest number + 1 (no collisions).
- Restores the SA region redirect state and the Admin-role original name.
- Re-arms the slowmode auto-disable and the lock auto-reopen from their persisted deadlines — or performs the action immediately if the deadline already passed while the bot was down (so nothing gets stuck on forever).

This is fully automatic and a no-op when no session is active. Milestone announcements (semi-final / finals / winner) self-heal separately: their history cross-check window is wide enough that the next progress tick re-adopts the existing messages instead of re-posting.

Because the bot auto-resumes, re-running `!starttourney` while a session is active is treated as an error (it would purge channels, delete pre-tourney tickets, and reset the session clock). It replies with a warning and does nothing. To intentionally tear down and restart setup from scratch, pass `force`: `!starttourney [region] force`.

---

## `!endtourney`

### What it does (in order)

1. **Forces a final announcement sync**: calls `fetch_bracket_progress()` and `announce_high_stakes_matches()` one last time so the winner post doesn't depend on the 5-minute loop timing
2. **Arms a crash-safe winner retry** if the winner isn't yet available (Matcherino API lag). Instead of a fire-and-forget `asyncio.create_task` (lost on a restart, and the session is already `finished` so `resume_tourney_if_active` can't recover it), it persists a `pending_winner_announcement` marker in `settings` (`matcherino_id`, `updates_channel_id`, and a ~1h deadline) and starts a retry loop that re-checks every 5 minutes until the winner is posted or the deadline passes. On boot, `QueueDashboard.winner_reconcile_task` (a `count=1` loop) re-arms the loop from the marker, so a restart mid-wait no longer drops the announcement. Posting is idempotent (it scans the updates channel for the exact `# GGs!` message before sending).
3. **Stops dashboard loops** and deletes dashboard messages from the admin channel
4. **Disables sticky redirects** and cleans up any redirect messages posted during the tournament
5. **Revokes Tourney Admin** `moderate_members` permission
6. **Fetches session stats** from MongoDB:
   - Duration (start_time → now)
   - Total tickets, total messages, peak queue size
   - Top staff leaderboard (tickets closed per staff member, up to 12)
   - Tournament name (from Matcherino `fetch_payout_report()`)
   - Tournament date (back-looked-up from `TOURNEY_SCHEDULE_CHANNEL_ID` using the `matcherino_id`)
7. **Posts the tournament report embed** to the command channel and archives it to `TOURNEY_REPORT_CHANNEL_ID`
8. **Closes the session** in MongoDB (`end_tourney_session()`) and disables data collection
9. **Clears the bracket team cache** (`clear_bracket_teams_cache()`)
10. **Auto-posts Hall of Fame** using the session's `matcherino_id` (shared `post_hall_of_fame()` helper, also used by `/hall-of-fame`) — skipped if no `matcherino_id` was set; failures are caught and reported without blocking the rest of `!endtourney`
11. **Reopens** `OTHER_TICKET_CHANNEL_ID` (unlocks members)
12. **Restores Admin role name** to its original value
13. **Cancels the slowmode timer** and removes slowmode from general channel immediately
14. **Unlocks Spanish channel** (`SPANISH_CHANNEL_ID`)
15. **Main tourney support channel**: hides from `@everyone`, purges, renames to `「❌❌❌」「🔴」tourney-support`
16. **Pre-tourney support channel**: re-opens for viewing (not sending), purges, posts pre-tourney panel, renames to `「🟡」pre-tourney-support`

---

## SA Region Mode

When `!starttourney sa` is used:
- `SPANISH_CHANNEL_ID` is locked (`send_messages=False` for `@everyone`)
- A Spanish-language redirect embed is posted: `¡Atención! Por favor, utiliza #tourney-support para abrir un ticket`
- On `!endtourney`, the Spanish channel is unlocked and restored

The region state is tracked in a closure-scoped dict `sticky_redirect_state = {"enabled": False, "region": None}` inside `setup_tourney_commands()`.

---

## Session Data (MongoDB)

Active sessions are stored in `tourney_sessions`:

| Field | Purpose |
|-------|---------|
| `start_time` | UTC datetime of `!starttourney` |
| `matcherino_id` | Linked bracket ID |
| `total_tickets` | Count of opened tickets |
| `total_messages` | Count of messages in all tickets |
| `peak_queue` | Max simultaneous open tickets |
| `collect_data` | Whether bracket snapshots are being saved |
| `region` | Region flag (e.g. `SA`) for restoring the sticky redirect on restart |
| `admin_role_original_name` | Admin role's pre-tourney name, for correct restore on `!endtourney` after a restart |
| `slowmode_ends_at` | Absolute UTC deadline for the general-channel slowmode auto-disable |
| `lock_reopens_at` | Absolute UTC deadline for the ticket-channel lock auto-reopen |

---

## Background Tasks Started by `!starttourney`

| Task | Interval | Purpose |
|------|----------|---------|
| `dashboard_task` | 15 seconds | Updates live queue count in `#tourney-support` |
| `progress_dashboard_task` | 5 minutes | Updates bracket progress in `#tourney-admin` |
| `match_refresher_task` | 1 minute | Refreshes Matcherino scores in each active ticket |
| `auto_disable_slowmode` | 1 hour (one-shot) | Removes slowmode from general channel |
| `auto_reopen` (lock) | 6 hours (one-shot) | Re-opens `OTHER_TICKET_CHANNEL_ID` |

---

## Source Files
- `features/tourney/tourney_commands.py` — `!starttourney`, `!endtourney`, queue and progress dashboards
- `features/tourney/tourney_utils.py` — ticket creation, closing, deletion, reopening
- `features/tourney/tourney_views.py` — UI buttons and modals
