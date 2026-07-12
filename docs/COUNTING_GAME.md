# Counting Game

## Overview
Members count sequentially in the designated counting channel. The bot validates every message: wrong numbers and consecutive counts from the same user are deleted. The current count and last contributor are persisted in MongoDB so progress survives bot restarts.

---

## `on_message` Listener

The counting cog hooks `on_message` and runs only in `COUNTING_CHANNEL_ID`:

1. **Ignore bots**: Skip if `message.author.bot`
2. **Parse number**: Attempt `int(message.content.strip())`. If not a valid integer → delete the message
3. **Check sequence**: If `parsed != current_count + 1` → delete and send an error message indicating the correct next number
4. **Check double-count**: If `message.author.id == last_user_id` → delete and warn that the same user cannot count twice in a row
5. **Accept**: Increment `current_count`, update `last_user_id`, write both to MongoDB via `update_counting_state()`

State reads/writes hit MongoDB on every valid count — the channel is low-traffic so this doesn't cause performance issues.

---

## Persistence

State is stored in a single MongoDB document in the `counting_state` collection:

```json
{
  "_id": "state",
  "count": 142,
  "last_user_id": "123456789"
}
```

On bot startup, the cog loads this document into memory. On each valid count, it writes the new values. If the document doesn't exist (first run), it's upserted with `count=0`.

---

## `/set-count <number>` (Staff)

Directly sets the current count:
1. Updates the in-memory count
2. Writes to MongoDB
3. Posts a confirmation message in the counting channel

Used to manually correct the count after a bot restart gap or to reset after a mistake.

---

## Error Responses

| Situation | Bot action |
|-----------|-----------|
| Non-integer message | Delete silently (or with a brief message) |
| Wrong number | Delete + reply with the correct next number |
| Same user counting twice | Delete + reply warning about double-counting |

The bot requires `Manage Messages` permission to delete messages.

---

## Source File
`features/counting.py`
