# Tournament Progress

## Overview
The progress system maintains two live feeds during a tournament: a **progress dashboard** in the admin channel (updates every 5 minutes) and **per-ticket match embeds** that refresh every minute with live scores. It also handles stage announcements (Semi-Finals, Finals, Winner) in the tourney updates channel.

---

## Queue Dashboard (15-second loop)

Posted and edited in `TOURNEY_SUPPORT_CHANNEL_ID`. Shows members how many tickets are waiting and which ticket is currently being served.

**"Currently Serving" logic**:
1. Finds the highest ticket number in the Closed category (`max_closed_num`)
2. The next expected ticket is `max_closed_num + 1`
3. If that number exists in the Active category, it's shown as currently serving
4. Otherwise, falls back to `min(active_ticket_numbers)`

The dashboard message is edited in place if it's already the latest message in the channel. If not (other messages were sent after it), the old message is deleted and a new one is sent — keeping the dashboard anchored at the bottom.

---

## Progress Dashboard (5-minute loop)

Posted and edited in `TOURNEY_ADMIN_CHANNEL_ID`. Shows the bracket's overall completion state.

**Displayed fields**:
- Total duration since `!starttourney`
- Completion percentage (`closed_matches / total_matches * 100`)
- Dominant round (highest round currently seeing active play)
- Rounds remaining to finals
- Active match count
- Bottleneck matches (active matches lagging behind the dominant round)

**Message management**: The bot stores the dashboard message ID. On each tick:
- If the existing message is still the latest in the channel → edit in place (no flash)
- If other messages were sent after it → delete old, send new (so it's always the newest message)
- If bot restarted and message ID was lost → scans the last 30 messages for one titled `📈 Live Tournament Progress` to recover it

---

## Match Refresher (1-minute loop)

Runs on every active ticket channel in `TOURNEY_CATEGORY_ID`. For each ticket:

1. Parses `bracket:{num}` and `team:{name}` from the channel topic
2. If no bracket number, falls back to `find_match_by_team_name()` and persists the resolved number back into the topic
3. Calls `fetch_ticket_context()` with the bracket URL, match number, and topic team name
4. Builds a live embed with team names, rosters (Matcherino display names), scores, match status, and a relative Discord timestamp (`<t:X:R>`)
5. If team name mismatch detected → embed color turns red + warning field added + auto-attempts to re-resolve via team name fallback
6. Locates the existing match embed in the channel (matches by title containing `Match #{num}`) and either edits it in place or deletes + reposts to keep it at the bottom
7. `asyncio.sleep(1.5)` between tickets to avoid hitting Discord rate limits

The refresher starts automatically when the `QueueDashboard` cog loads — it runs even outside a tournament to keep any lingering active tickets updated.

---

## Stage Announcements

Posted to `TOURNEY_UPDATES_CHANNEL_ID`. Handled by `announce_high_stakes_matches()` which runs on every progress dashboard tick.

### Semi-Finals
- Detected when `all_matches` (active + closed) contains 2 matches at `round == max_round - 1` with both teams known
- Required count is exactly 2; if fewer, no announcement is made

### Finals
- Detected when `all_matches` contains 1 match at `round == max_round` with both teams known
- **Ordering guard**: Finals are not posted until the Semi-Finals announcement message exists (prevents out-of-order posts in small brackets or when the API updates in a single tick)

### Winner
- Detected when `completion_pct >= 100` or `remaining_matches == 0` and `winner_team` is populated
- **Ordering guard**: Winner is not posted until the Finals announcement exists
- Once posted, the winner message is never deleted

### Deduplication
Each stage has a **signature** built from the participating team names:
```python
"|".join(f"{m['id']}::{m['team_a']}::{m['team_b']}" for m in sorted_matches)
```
If the signature matches the last posted announcement, no action is taken. If teams change (e.g. a TBD slot fills), the existing message is **edited in place** (no delete/repost gap). Recent channel history is also checked to catch duplicate posts from concurrent loop ticks.

---

## Snapshot Collection (POC)

When `session.collect_data == True`, every progress dashboard tick writes a snapshot to MongoDB (`tourney_snapshots` collection) via `_write_snapshot()`:

| Field | Meaning |
|-------|---------|
| `dominant_round` | Current dominant round |
| `round_position_from_end` | `max_round - dominant_round` |
| `round_duration` | Seconds from first to last match in a completed round (only on round transition) |
| `duration_per_match` | `round_duration / match_count` |
| `bottleneck_count` | Number of lagging matches |
| `time_of_day` | UTC hour (0–23) |
| `day_of_week` | 0=Monday … 6=Sunday |

Round duration is computed on transition only: when `dominant_round` changes, the bot calculates the duration for the **completed** round using `min(statusAt)` across all its matches as the start and `max(endAt)` across its closed matches as the end.

---

## Source File
`features/tourney/tourney_commands.py` — `QueueDashboard` cog
