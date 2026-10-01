# Sticky Messages

## Overview
A sticky message is a bot-managed message that always stays at the bottom of a channel. When any member sends a message, the bot deletes the previous sticky and reposts it. A 1.5-second debounce prevents rapid repostings when messages come in quickly. One sticky per channel, persisted in MongoDB.

---

## How the Repost Works

The `on_message` listener fires whenever a non-bot, non-sticky message is sent in a channel with an active sticky:

1. Reads the sticky for `channel.id` from MongoDB (or in-memory cache)
2. Starts a 1.5-second debounce timer (`asyncio.sleep(1.5)`) — if another message arrives within that window, the first timer is cancelled and a new one starts
3. After the debounce:
   - Fetches and deletes the previous sticky message by ID (`message_id` stored in DB)
   - Reposts the sticky content as a new message (with any attached image/file)
   - Saves the new message ID back to MongoDB

This means the sticky is never truly pinned — it's just repeatedly reposted to the bottom. The `message_id` is the key field that allows the bot to find and delete the old one.

---

## Debounce Implementation

A per-channel debounce task dict tracks pending repost tasks:

```python
_pending_repost: dict[int, asyncio.Task] = {}

async def on_message(message):
    if channel.id not in sticky_data:
        return
    # Cancel any pending repost
    task = _pending_repost.get(channel.id)
    if task and not task.done():
        task.cancel()
    # Schedule new repost after 1.5s
    _pending_repost[channel.id] = asyncio.create_task(
        _do_repost(channel, sticky_data[channel.id])
    )
```

---

## "Set Sticky" Message Command

Right-click the message to stick, then **Apps → Set Sticky**. Requires the **Administrator** permission or the **Event Staff** role (`EVENT_STAFF_ROLE_ID`). All responses are ephemeral.

1. Reads the target message's text and downloads its attachments (the interaction is deferred first, since large files can outlast the 3-second response window)
2. Rejects the message if it has neither text nor attachments
3. If a sticky already exists in the channel, the old bot message is deleted first
4. Posts the sticky immediately and stores it in MongoDB with the new message ID

The context menu is registered on the command tree in `cog_load` and removed in `cog_unload`, since discord.py does not allow context menus to be declared as cog methods.

### MongoDB Document (`sticky_messages`)
```json
{
  "_id": "channel_id",
  "content": "Welcome! Please read #rules.",
  "attachments": [{"filename": "banner.png", "data": "<bytes>"}],
  "bot_message_id": 987654321
}
```

---

## `/unsticky` Command

Requires the **Administrator** permission or the **Event Staff** role (`EVENT_STAFF_ROLE_ID`).

1. Fetches the current sticky for the channel from MongoDB
2. Deletes the sticky message from Discord by `bot_message_id`
3. Removes the document from the `sticky_messages` collection
4. Cancels any pending debounce task for the channel

---

## Attachment Preservation

Attachments are downloaded when the sticky is set and stored as bytes in the document, so reposts never depend on Discord CDN URLs (which expire).

---

## Source File
`features/sticky.py`
