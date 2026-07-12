# Hacked System

## Overview
When a Discord account appears compromised (e.g. sending scam links), moderators can flag it with `/hacked` or `!hacked` (reply). This triggers a single shared action method that applies a timeout, purges messages, logs to the mod channel, DMs the user, and stores the flag in MongoDB. The two command surfaces call the same `_execute_hacked_action()` helper.

---

## `_execute_hacked_action(guild, target_user, moderator)`

This is the single shared method both slash and prefix commands call:

### Step 1 — Role Guard
```python
if target_user.top_role >= moderator.top_role:
    return error_embed  # can't target equal/higher roles
```
Only applies when the target is still in the server (`discord.Member`). If they've left, this check is skipped.

### Step 2 — Timeout
```python
duration = timedelta(days=7)
await target_user.timeout(duration, reason="Security: User Compromised/Hacked")
```
If the user has left the server, timeout is skipped with a `"⚠️ User Not in Server — Timeout Skipped"` status note.

### Step 3 — Database Flag
```python
await add_hacked_user(str(target_user.id))
```
Inserts into the `hacked_users` MongoDB collection. Used by `/hacked-list`.

### Step 4 — DM the Flagged User
Sends a `dark_red` embed explaining the flag, the timeout duration, and who to contact (hardcoded founder ID) to get removed after account recovery. If the DM fails (user has DMs closed), the error is silently swallowed.

### Step 5 — Global Message Purge
```python
cutoff_date = datetime.utcnow() - timedelta(hours=12)
```
Iterates **every channel** in the server (text channels + threads from all categories):
- Fetches messages after `cutoff_date` from the target user
- Calls `channel.purge(check=lambda m: m.author.id == target_user.id, after=cutoff_date)`
- Tracks total deleted count and earliest message timestamp across all channels
- Logs progress via print (not Discord message)

The 12-hour window is a deliberate choice — it covers the realistic spread of messages from a compromised account without trying to mass-delete older legitimate content.

---

## Commands

### `/hacked <user> [days]`
Slash command. Takes the target user and optional timeout duration (default 7 days). Calls `_execute_hacked_action()` and sends a summary embed in the channel showing timeout status, messages deleted, and channels affected.

### `!hacked` (reply)
Prefix command. Must be used as a reply to a message from the target. Extracts the author from the referenced message. Same flow as slash command.

### `/unhacked <user>`
1. Removes timeout if the user is still in the server (`await target_user.timeout(None)`)
2. Calls `remove_hacked_user(user_id)` to remove from `hacked_users` collection
3. Sends confirmation in channel

### `/hacked-list`
Fetches all documents from `hacked_users` collection via `get_hacked_users()` and formats them as a list of Discord mentions with their user IDs.

---

## Moderator Logging

After the action, a log embed is sent to `MODERATOR_LOGS_CHANNEL_ID` (configured in `features/config.py`) with:
- Moderator who ran the command
- Target user (mention + ID)
- Timeout duration
- Number of messages deleted
- Number of channels checked
- Timestamp of earliest purged message

---

## Permission Check

```python
async def has_security_permission(self, source):
    is_admin = user.get_role(ADMIN_ROLE_ID) is not None
    is_mod = user.get_role(MODERATOR_ROLE_ID) is not None
    return is_admin or is_mod
```

Both Admin and Moderator roles can run security commands. Trial Moderators cannot.

---

## Source File
`features/security.py` — `Security` cog
