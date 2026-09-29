# Translation

## Overview
The translation system wraps Google Translate (via `deep-translator`) and `langdetect`. It exposes a "Translate" message command and a slash command for manual translations. It is also used internally by `tourney_utils.py` to auto-translate ticket issue descriptions. Every caller goes through one shared client, `features/translate_client.py`.

---

## Shared Client (`features/translate_client.py`)

`deep-translator`'s `GoogleTranslator` calls Google's free web endpoint. When Google decides the bot is calling too often it answers HTTP 429, which the library raises as `TooManyRequests` ("Server Error: You made too many requests to the server..."). The "5 requests per second and 200k per day" figures in that message are hardcoded in the library. In practice the 429s come from Google throttling the host's IP, not from the bot's own volume (#573).

`await translate_client.translate(text, source="auto", target="en")` handles this:

1. **Cache.** Results are kept in an in-memory LRU cache (`CACHE_SIZE = 256`) keyed by `(source, target, text)`, so translating the same message twice makes one request. Failures are never cached. The cache is cleared on restart.
2. **Throttle.** All provider calls, from every feature, share one lock and are spaced at least `MIN_INTERVAL = 0.25` seconds apart (4 requests/second, under Google's 5).
3. **Retry.** On a 429 from Google the call is retried after 1s, then 2s (`RETRY_DELAYS`), so 3 Google attempts in total. Other Google errors are not retried.
4. **Fallback.** If Google still fails, the text is sent to MyMemory (`MyMemoryTranslator`, free, no API key). MyMemory needs explicit `xx-YY` codes, so `to_mymemory_code()` maps ours (`es` -> `es-ES`, `zh-cn` -> `zh-CN`, `en` -> `en-GB`, `no` -> `nb-NO`), and an `auto` source is resolved with `langdetect` first. MyMemory's anonymous quota is about 5,000 characters per day and 500 characters per request.
5. **Unavailable.** If MyMemory also fails, `TranslationUnavailable` is raised.

The blocking provider calls run in a thread pool via `asyncio.to_thread`.

---

## Internal Helper (Used by Tickets)

```python
async def _get_translation(text: str) -> str | None:
    try:
        detected = await asyncio.to_thread(detect, text)
        if detected == "en":
            return None
        return await translate_client.translate(text, source="auto", target="en")
    except Exception:
        return None
```

Returns `None` if the text is already English or if detection/translation fails, so the ticket opens without a translation field.

---

## Message Command: "Translate"

Right-click any message, then **Apps → Translate** (on mobile, long-press the message → Apps):

1. Reads the target message's content from the interaction (no reply or command text needed)
2. Replies with an ephemeral error if the message has no text (image-only or embed-only)
3. Calls `langdetect.detect()` to identify the source language
4. Translates to English through the shared client; if every provider is unavailable, replies with an ephemeral "busy" message
5. Posts a response embed with:
   - Title: `🌐 Translated from {detected_lang}`
   - Field: Original message (quoted)
   - Field: English translation (bold)
6. Attaches a **Wrong language?** button (replaces `!t <language>`). Only the requester can press it. It opens a modal where they type the message's real language as a name or code (`hindi` or `hi`, matched by `get_language_code()`); the bot re-translates with that as the source and edits the result, adding a "Manual Language Override" author line. An unknown language is rejected ephemerally. The button stops working after 15 minutes or a bot restart.

The context menu is registered on the command tree in `cog_load` and removed in `cog_unload`, since discord.py does not allow context menus to be declared as cog methods.

---

## Slash Command: `/translate <language> <phrase>`

Translates a phrase from English to a specified language. The `language` parameter supports the full language name (e.g. `Spanish`, `Japanese`) or common abbreviations. Returns an embed with the translated phrase.

---

## Supported Languages (55 total)

Afrikaans, Arabic, Bengali, Bulgarian, Catalan, Chinese (Simplified), Chinese (Traditional), Croatian, Czech, Danish, Dutch, English, Estonian, Finnish, French, Galician, German, Greek, Gujarati, Hebrew, Hindi, Hungarian, Indonesian, Italian, Japanese, Kannada, Korean, Latvian, Lithuanian, Macedonian, Malay, Malayalam, Marathi, Norwegian, Persian, Polish, Portuguese, Punjabi, Romanian, Russian, Serbian, Slovak, Slovenian, Spanish, Swedish, Tamil, Telugu, Thai, Turkish, Ukrainian, Urdu, Vietnamese, Welsh, and more.

---

## Notes
- `deep-translator` uses Google Translate under the hood, with no API key. Google rate limits it per IP; see the shared client section for how the bot copes
- If both providers fail, the Translate message command and `/translate` respond (ephemeral) with "⚠️ The translation service is busy right now. Please try again in a minute." instead of the raw library error. Other unexpected errors still show their error text
- `langdetect` is non-deterministic for short strings (it can misdetect very short text); this is a known limitation
- `translate_client.py` imports nothing from the bot, so both the cog and `tourney_utils.py` can import it without import cycles

---

## Source Files
- `features/translation.py` (commands)
- `features/translate_client.py` (shared client: throttle, cache, retry, fallback)
