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

## `!sticky <message>` Command

Requires the **Administrator** permission or the **Event Staff** role (`EVENT_STAFF_ROLE_ID`).

1. Stores content + any attachment URL in MongoDB (`sticky` collection, keyed by `channel_id`)
2. Posts the sticky message immediately and saves its message ID
3. If a sticky already exists in the channel, the old one is deleted first

### MongoDB Document
```json
{
  "_id": "channel_id",
  "content": "Welcome! Please read #rules.",
  "attachment_url": "https://cdn.discordapp.com/...",
  "message_id": "987654321"
}
```

---

## `!unsticky` Command

Requires the **Administrator** permission or the **Event Staff** role (`EVENT_STAFF_ROLE_ID`).

1. Fetches the current sticky for the channel from MongoDB
2. Deletes the sticky message from Discord by `message_id`
3. Removes the document from the `sticky` collection
4. Cancels any pending debounce task for the channel

---

## Attachment Preservation

When setting a sticky with an attachment, the URL is stored. On each repost, the URL is sent as a separate message component or as `content` alongside the text. Note: Discord CDN URLs can expire — long-running stickies with attachments may eventually break if the attachment URL expires.

---

## Source File
`features/sticky.py`
