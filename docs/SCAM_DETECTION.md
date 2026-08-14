# Scam Image Detection

## Overview
Compromised accounts spam the same scam screenshot (fake Nitro giveaways, phishing "free skins" images) across many channels at once. `features/scam_detection.py` scans every image attachment posted in the server against a MongoDB blacklist and reacts automatically: delete the message, purge other copies across channels, apply a short precautionary timeout, and alert moderators with Confirm/Dismiss buttons.

It complements the Hacked System (`docs/HACKED_SYSTEM.md`) — detection is automatic here, while the heavy action (7-day timeout + DB flag + DM) only happens after a mod clicks **Confirm Hacked**.

---

## Detection Pipeline

Each incoming image runs through three matchers in order (cheapest first), inside a `ThreadPoolExecutor` so CPU work never blocks the event loop:

| Matcher | Catches | Threshold |
|---|---|---|
| **MD5** | Byte-identical re-uploads | Exact match |
| **pHash** (64-bit DCT perceptual hash) | Re-compressed, resized, slightly edited copies | Hamming distance ≤ `PHASH_MATCH_THRESHOLD` (10) |
| **ORB** (OpenCV feature matching) | Cropped variants | ≥ `ORB_MATCH_THRESHOLD` (15) keypoints at distance < `_ORB_DISTANCE_CUTOFF` (20) |

Threshold tuning history:
- pHash alone misses crops (a crop of a blacklisted image measured distance 21/64 — well above 10). ORB exists specifically for crops.
- ORB at loose settings (25 keypoints @ distance 50) matched *everything* and deleted innocent images. The current tight cutoff (distance < 20) keeps only near-exact feature matches.
- Raise `PHASH_MATCH_THRESHOLD` cautiously — 10 already allows minor edits; much higher starts matching unrelated screenshots with similar layouts.

The pHash/ORB indexes are built in memory at cog load (`_reload_index()`) from the `scam_images` collection and hot-reloaded after every `!scam-add` / `!scam-remove` / `!scam-rename`.

---

## `on_message` Flow

1. Skip bots, DMs, messages older than 10s (prevents re-processing on reconnect backfill), and anything starting with `!scam` (otherwise `!scam-add`/`!scam-test` with a blacklisted image attached would delete the mod's own command message and time them out).
2. For each allowed attachment (`.png .jpg .jpeg .webp`): in-memory dedup check on `(author_id, filename, size)`, then download via the shared `aiohttp` session, then run the detection pipeline in the executor.
3. On match, claim the **atomic detection lock** (see below). The lock loser still **deletes its copy of the message** but skips the alert/timeout/purge.
4. Lock winner: delete the message → purge other copies across all channels/threads (`_PURGE_LOOKBACK_MINUTES = 30`, newest-first, MD5-verified by size pre-filter then download; see **Crash-Safe Purge** below) → 10-minute timeout → mod alert to `MODERATOR_LOGS_CHANNEL_ID` with the image re-uploaded (so it survives the deletion) and a `ScamAlertView`.

### Duplicate-Alert Prevention (the hard-won part)
When the same image lands in 5 channels simultaneously, 5 `on_message` coroutines race. In-memory sets alone do **not** fix this reliably (tried twice — coroutine interleaving and key-expiry races both produced duplicate alerts). The working solution is a MongoDB atomic lock:

```python
acquire_scam_detection_lock(author_id, image_md5)
# find_one_and_update with $setOnInsert + upsert — only one caller gets None back
```

Locks live in `scam_detection_locks` and expire via a **TTL index on `ts` (60s)**, created at cog load by `ensure_scam_lock_ttl_index()`. Without that index locks never expire and re-posts of the same image by the same user are ignored forever. Mongo's TTL monitor runs every ~60s, so real expiry is 60–120s.

### Crash-Safe Purge
The cross-channel purge is a long sequential loop over every text channel + thread. If the bot crashed partway through, the remaining channels used to be abandoned silently — the 10s freshness guard and the 60s detection lock both suppress re-detection, so it was never retried, leaving scam copies live indefinitely.

The purge is now backed by a **`scam_purge_sessions`** doc that survives restarts:

1. Before any deletes, the lock winner writes a session with the full target channel list (`channels`), an empty `completed` cursor, and the original lookback `cutoff` (persisted so a resumed run reuses the *same* 30-minute window, not a fresh one from restart time).
2. `_run_purge_session` processes each channel and `$addToSet`s its id into `completed` the instant it finishes (a deleted or permission-less channel counts as done so the session always reaches completion). The doc is deleted only once every channel is processed.
3. `scam_purge_reconcile_task` (`@tasks.loop(count=1)`, cold-boot only, after `wait_until_ready()`) picks up any leftover session and resumes it from its `completed` cursor. If the guild isn't cached yet the session is deferred untouched for a later boot.

Resuming is safe to run twice because MD5 deletes are idempotent (a copy already gone → caught exception), so no per-session lock is needed. A resumed purge that actually removed copies posts a distinct **"Scam Purge Completed After Restart"** embed to `MODERATOR_LOGS_CHANNEL_ID` (separate from the original detection alert), and every resumed session prints a console audit line.

If the DB is down, `create_scam_purge_session` returns `None` and the purge still runs in memory (just not crash-safe) — behaviour is otherwise unchanged.

---

## `ScamAlertView` Buttons

Both buttons gate on the Security cog's `has_security_permission()` (Admin or Mod role).

- **🚨 Confirm Hacked** — role-hierarchy guard, upgrade to 7-day timeout, `add_hacked_user()` DB flag, DM the user (same wording as the hacked protocol), edit the alert to a dark-red "Confirmed" embed, disable buttons.
- **✅ False Positive** — remove the 10-minute timeout, edit the alert to a green "Dismissed" embed, disable buttons.

**Known limitation:** the view is `timeout=None` but not a *persistent* view — buttons stop working after a bot restart. Pending alerts across a deploy must be handled with `/hacked`/`/unhacked` manually. Fixing this requires a `discord.ui.DynamicItem` refactor with the target user ID in the `custom_id`.

---

## Commands

All commands require the Admin or Moderator role (via Security cog's `has_security_permission()`).

| Command | Behavior |
|---|---|
| `!scam-add` | Reply to a message with an image, or attach image(s) directly. Downloads, stores in `scam_images` (max 15MB — Mongo doc limit), hot-reloads index. |
| `!scam-remove <md5> [md5 ...]` | Removes entries by MD5 prefix. Accepts multiple prefixes; reports removed vs. not-found per prefix; reloads index once. |
| `!scam-list` | Lists `filename — md5[:8]` for every entry (fetches without binary data). |
| `!scam-rename <md5_prefix> <new name...>` | Renames **one** matching entry (use a unique prefix). Multi-word names allowed. |
| `!scam-test` | Dry run — reply/attach like `!scam-add`. Reports match/no-match plus closest pHash distance and best ORB keypoint count. No action taken. |

---

## Database

### `scam_images`
```js
{
  _id: "<md5>",        // MD5 as _id — two different images named image.png don't collide
  filename: "fake nitro giveaway",
  data: BinData(...),  // full image bytes (needed to rebuild indexes at startup)
  md5: "<md5>"         // duplicated as a field so prefix-regex remove/rename works
}
```
Early versions keyed on filename — two different images both named `image.png` overwrote each other. MD5 `_id` fixed that.

### `scam_detection_locks`
```js
{ _id: "<author_id>:<image_md5>", ts: ISODate(...) }  // TTL-indexed, 60s
```

### `scam_purge_sessions`
```js
{
  _id: ObjectId(...),
  guild_id: 123, author_id: 456,
  image_md5: "<md5>", image_size: 12345,
  skip_message_id: 789,      // the already-deleted flagged message
  cutoff: ISODate(...),      // persisted lookback window (reused on resume)
  channels: [1, 2, 3],       // immutable target list captured at session start
  completed: [1, 2],         // cursor: channel ids already processed
  created_at: ISODate(...)
}
```
Crash-safety record for the cross-channel purge (see **Crash-Safe Purge** above). Written before any deletes, its `completed` cursor grows per channel, and it is deleted once the purge finishes. Leftover docs are resumed once at cold boot by `scam_purge_reconcile_task`. **No TTL** — an unfinished session must persist until it is resolved.

---

## Dependencies
`opencv-python-headless`, `numpy`, `aiohttp` (in requirements.txt). Headless OpenCV — no GUI libs needed on the host.

## Bot Permissions Required
Manage Messages (delete), Moderate Members (timeouts), Read Message History (cross-channel purge), Send Messages + Attach Files in the mod-logs channel. Bot's role must be above targets or timeout calls 403 (error 50013).
