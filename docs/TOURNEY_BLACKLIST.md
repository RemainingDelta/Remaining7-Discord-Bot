# Tournament Blacklist

## Overview
The blacklist prevents banned players from participating in Remaining7 tournaments. When a blacklisted user opens a ticket, staff are immediately alerted in the admin channel with the ban details. The blacklist is stored in MongoDB and persists across sessions.

---

## Commands

### `/blacklist add <user> <reason> [matcherino] [alts]`

Adds a user to the blacklist. The `alts` parameter accepts a space-separated list of Discord IDs or mentions; these are parsed by stripping `<@!...>` formatting with `re.findall(r"\d+", alts)` and deduplicated with `set()`.

Stored in MongoDB:
```json
{
  "_id": "user_discord_id",
  "reason": "Cheating in June tournament",
  "matcherino": "https://matcherino.com/users/...",
  "alts": ["111111111", "222222222"],
  "admin_id": "staff_discord_id",
  "timestamp": "2026-06-21T00:00:00Z"
}
```

### `/blacklist remove <user>`

Checks if the user is actually in the blacklist first (returns a warning if not). If found, calls `remove_blacklisted_user(user_id)` to delete the document.

### `/blacklist list`

Fetches all documents from the `blacklist` collection. Formats each entry as:
```
• @User (123456789) — 2026-06-21
  Reason: Cheating in June tournament
```

Truncates at 4000 characters if the list is very long.

---

## Automatic Alert on Ticket Open

`check_and_alert_blacklist()` is called at the end of both `create_tourney_ticket_channel()` and `create_pre_tourney_ticket_channel()`:

```python
blacklist_data = await get_blacklisted_user(str(user.id))
if not blacklist_data:
    return  # not banned
# Post alert to TOURNEY_ADMIN_CHANNEL_ID
```

The alert embed includes:
- The ticket channel mention (so staff can click straight to it)
- Ban reason
- Ban date
- Matcherino profile link
- Known alts (as mentions)
- Pings `@Tourney Admin` role

The ticket is **not blocked** — it opens regardless. The alert is informational so staff can decide how to handle it. This avoids situations where a user correctly disputes their blacklist status.

---

## Notes
- The blacklist is not automatically enforced in the bracket — staff must manually check the alert and act accordingly
- Alt accounts tracked in `alts[]` are stored as Discord IDs; they are not automatically cross-referenced unless staff manually look them up
- `get_blacklisted_user()` queries by `_id` (exact Discord ID match) — alts are not indexed for automatic lookups

---

## Source File
- `features/tourney/tourney_commands.py` — `BlacklistGroup` slash command group
- `features/tourney/tourney_utils.py` — `check_and_alert_blacklist()`
- `database/mongo.py` — `add_blacklisted_user()`, `remove_blacklisted_user()`, `get_blacklisted_user()`, `get_all_blacklisted_users()`
