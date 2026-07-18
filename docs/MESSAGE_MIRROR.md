# Message Mirror

## Overview
Lets moderators repost any message via webhook so it renders with the original author's username and avatar. A moderator pastes a Discord message link in a channel; the bot fetches the linked message and mirrors it in that channel through a temporary webhook. The moderator's link message is left in place. General utility — usable for booster shoutouts or any repost need.

---

## Trigger Conditions

The `on_message` listener mirrors only when **all** of these hold:

1. Author is not a bot and the message is in a guild
2. Author has the **Moderator role** (`MODERATOR_ROLE_ID`) — non-moderators are unaffected
3. The message content is **exactly one** Discord message link (surrounding whitespace allowed). A link inside a sentence does not trigger, so conversational messages containing links are never mirrored
4. The channel supports webhooks (threads and voice channels are skipped)

Accepted link formats: `discord.com`, `ptb.discord.com`, `canary.discord.com`, `discordapp.com` — all matching `/channels/<guild_id>/<channel_id>/<message_id>`.

---

## Mirror Flow

1. `_parse_message_link()` extracts `(guild_id, channel_id, message_id)`
2. The linked message is fetched via `bot.get_channel()` (falling back to `fetch_channel()`) then `channel.fetch_message()`. If the message can't be fetched (deleted, no access), the listener silently does nothing
3. `_strip_mentions()` removes all user (`<@id>`, `<@!id>`) and role (`<@&id>`) mention tokens from the content. Channel mentions (`<#id>`) are kept since they don't ping. Leftover doubled spaces are collapsed; leading indentation (code blocks) is preserved
4. Attachment URLs are appended on separate lines so images re-embed; content is truncated to the 2000-char webhook limit. If the source has no content and no attachments, nothing is posted
5. A webhook named `R7 Message Mirror` is created in the channel, sends with `username=source.author.display_name` and `avatar_url=source.author.display_avatar.url`, then is **deleted** (channels cap at 15 webhooks)
6. The webhook send also passes `allowed_mentions=AllowedMentions.none()` as a second layer against pings

---

## Permissions Required (bot)

- **Manage Webhooks** in the target channel (create/delete the webhook)

Failures on any Discord call are swallowed (`HTTPException`) — the feature degrades silently rather than erroring in chat.

---

## Source File
`features/message_mirror.py` — tests in `tests/test_message_mirror.py`
