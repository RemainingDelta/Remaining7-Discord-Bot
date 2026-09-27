# Translation

## Overview
The translation system wraps Google Translate (via `deep-translator`) and `langdetect`. It exposes a "Translate" message command and a slash command for manual translations. It is also used internally by `tourney_utils.py` to auto-translate ticket issue descriptions.

---

## Internal Helper (Used by Tickets)

```python
async def _get_translation(text: str) -> str | None:
    detected = await asyncio.to_thread(detect, text)
    if detected == "en":
        return None
    translated = await asyncio.to_thread(
        GoogleTranslator(source="auto", target="en").translate, text
    )
    return translated
```

Both `detect()` and `translate()` are blocking calls run in a thread pool via `asyncio.to_thread` to avoid blocking the event loop. Returns `None` if the text is already English or if detection/translation fails.

---

## Message Command: "Translate"

Right-click any message, then **Apps → Translate** (on mobile, long-press the message → Apps):

1. Reads the target message's content from the interaction (no reply or command text needed)
2. Replies with an ephemeral error if the message has no text (image-only or embed-only)
3. Calls `langdetect.detect()` to identify the source language
4. Translates to English
5. Posts a response embed with:
   - Title: `🌐 Translated from {detected_lang}`
   - Field: Original message (quoted)
   - Field: English translation (bold)

The context menu is registered on the command tree in `cog_load` and removed in `cog_unload`, since discord.py does not allow context menus to be declared as cog methods.

---

## Slash Command: `/translate <language> <phrase>`

Translates a phrase from English to a specified language. The `language` parameter supports the full language name (e.g. `Spanish`, `Japanese`) or common abbreviations. Returns an embed with the translated phrase.

---

## Supported Languages (55 total)

Afrikaans, Arabic, Bengali, Bulgarian, Catalan, Chinese (Simplified), Chinese (Traditional), Croatian, Czech, Danish, Dutch, English, Estonian, Finnish, French, Galician, German, Greek, Gujarati, Hebrew, Hindi, Hungarian, Indonesian, Italian, Japanese, Kannada, Korean, Latvian, Lithuanian, Macedonian, Malay, Malayalam, Marathi, Norwegian, Persian, Polish, Portuguese, Punjabi, Romanian, Russian, Serbian, Slovak, Slovenian, Spanish, Swedish, Tamil, Telugu, Thai, Turkish, Ukrainian, Urdu, Vietnamese, Welsh, and more.

---

## Notes
- `deep-translator` uses Google Translate under the hood — no API key required for standard usage, but it's subject to rate limits on high volume
- `langdetect` is non-deterministic for short strings (it can misdetect very short text); this is a known limitation
- The translation cog is loaded separately from `tourney_utils.py` — the internal `_get_translation` helper in `tourney_utils.py` is a self-contained copy to avoid cross-module import cycles

---

## Source File
`features/translation.py`
