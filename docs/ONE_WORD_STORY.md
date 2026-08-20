# Collaborative Story

## Overview
Members build one story in the designated story channel by adding **one word per message**, but only while the story is **active**. Staff open a story with `/story-start` and close it with `/story-end` or `/story-reset`. While active, the bot validates every message (multi-word messages, emojis, banned words, banned characters, and two words in a row from the same user are deleted with a short-lived warning) and reacts to each accepted word with a ✅. While inactive, the bot ignores the channel entirely — so if a contribution gets no ✅, the story isn't running. The story and moderation lists are persisted in MongoDB so progress and config survive bot restarts.

This feature replaces the previous third-party "one-word story" bot. It is modeled on the Counting game (`features/counting.py`).

---

## `on_message` Listener

The story cog hooks `on_message` and runs only in `STORY_CHANNEL_ID`:

1. **Ignore bots / DMs / other channels**: Skip if `message.author.bot`, no guild, or the channel isn't the story channel.
2. **Check active**: If the story isn't `active` → return silently (no delete, no reaction). This is what makes a missing ✅ mean "no story running".
3. **Check double-turn**: If `message.author.id == last_user_id` → delete and warn that the same user can't add two words in a row.
4. **Validate the word** via `validate_story_word()` (a Discord/Mongo-free helper), in order:
   - Reject empty messages.
   - Reject if the message contains whitespace (must be a single word).
   - Reject if the word contains an emoji — Unicode emoji or a Discord custom emoji (`<:name:id>`).
   - Reject if any character is on the banned-character list (compared case-insensitively). `_` is banned by default so users can't smuggle multi-word entries like `I_am_a_noob`.
   - Reject if the lowercased word is on the banned-word list.
5. **Accept**: Append the word (stored exactly as typed) to the story, set `last_user_id` via `append_story_word()`, and add a ✅ reaction to the message.

Words are stored raw, but **displayed** (in `/story-see` and `/story-end`) through `display_story_units()`, which:
- lowercases every word and capitalizes only the first letter of each sentence — the first word, and any word following one that ended with `.`, `!`, or `?` (trailing quotes/brackets are ignored). So `Name`/`NAME` both render as `name` mid-sentence, and `Name` at a sentence start; and
- glues a punctuation-leading token onto the previous word with no space, so a standalone `.` contribution renders as `noob.` rather than `noob .` (attach set: `. , ; : ! ? ) ] }`).

State and ban lists are read from MongoDB on each message — the channel is low-traffic so this doesn't cause performance issues.

---

## Persistence

Live state is a single document in the `story` collection:

```json
{
  "_id": "state",
  "words": ["Once", "upon", "a", "time"],
  "last_user_id": 123456789,
  "active": true
}
```

`active` gates the listener: contributions are only accepted (and reacted to) when it's `true`. `/story-start` sets it `true`; `/story-end` and `/story-reset` set it `false`. A fresh install with no state document is treated as inactive.

On `/story-start`, `/story-end`, or `/story-reset`, the current state (if it has any words) is copied into the `story_archive` collection with an `archived_at` timestamp, then the live document is cleared.

Moderation lists live in `story_config`, one document per list (`_id = "banned_words"` / `"banned_chars"`), each with an `items` array. When the `banned_chars` document is absent, the code defaults to `["_"]`. The `banned_words` document has no in-repo default — it's populated from a remote list on first run (see `/story-banword` below).

---

## Commands

### `/story-see`
Ephemeral. Shows the current story in an embed (or a prompt to add the first word), with a footer showing the word count and whether the story is `active` or `closed`. Usable only in the story channel. Long stories are truncated to the most recent ~4096 characters (the embed description limit).

### `/story-start` (Staff)
Archives the current story, clears it, **marks the story active**, and posts an opening announcement in the channel to kick off a fresh story.

### `/story-reset` (Staff)
Archives and clears the current story silently (no announcement) and **marks it inactive**.

### `/story-end` (Staff)
Publishes the finished story to the channel as an embed (split across multiple embeds if it exceeds the 4096-character description limit), then archives it, clears it, and **marks it inactive**. Use this to formally wrap up a story so the completed text stays visible in the channel; `/story-reset` only archives silently.

### `/story-banword add|remove|list <word>` (Staff)
Manages the banned-word list. Words are stored lowercased. **No word list is committed to this repo.** Instead, on first cog load (`seed_default_banned_words()`), the bot fetches the [LDNOOBW](https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words) public profanity list from `STORY_BANNED_WORDS_URL` and caches it into the `banned_words` document in Mongo. This runs once — it's a no-op if the document already exists (so staff edits are never clobbered) and if the fetch fails the list simply stays unseeded until the next restart. Staff can extend or override it live via `/story-banword`.

Matching is lenient: contributions are normalized before comparison — lowercased, common leet substitutions folded (`4→a`, `$→s`, `3→e`, …), non-letters dropped, and runs of 3+ identical letters collapsed. So `f4ggot` and `shiiiit` are caught, while normal double letters are preserved so innocent words like `as` never collapse into `ass`. It still matches whole words only, not substrings.

### `/story-banchar add|remove|list <character>` (Staff)
Manages the banned-character list. `add` requires exactly one character.

Staff = roles in `STORY_MOD_ROLES` (Moderator, Admin, Founder).

---

## Error Responses

| Situation | Bot action |
|-----------|-----------|
| No story active | Ignore silently (no delete, no reaction) |
| Empty message | Delete + reply that no word was found |
| More than one word (contains whitespace) | Delete + reply "one word at a time" |
| Contains an emoji (Unicode or custom) | Delete + reply that emojis aren't allowed |
| Contains a banned character | Delete + reply that a character isn't allowed |
| Word on the banned list | Delete + reply that the word is banned |
| Same user adding two words in a row | Delete + reply warning about double-turns |

The bot requires `Manage Messages` to delete messages and `Add Reactions` to react with ✅ on accepted words.

---

## Notes
- The story channel is added to `PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS`, so contributions earn no passive tokens or quest credit (prevents farming).
- Banned-word matching is whole-word on the normalized form — it folds leet-speak and stretched repeats, but does not catch substrings (a banned `ass` won't flag `assassin`).

---

## Source File
`features/story.py`
