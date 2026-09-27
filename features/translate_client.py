"""Shared translation client used by every feature that translates text (#573).

Google's free endpoint (what deep-translator's GoogleTranslator scrapes)
answers HTTP 429 when it decides we are calling too often, and deep-translator
turns that into TooManyRequests. Every caller goes through `translate()` so
calls are throttled bot-wide, repeats are cached, 429s are retried with
backoff, and MyMemory is used as a fallback when Google keeps refusing.

Callers should reference `translate_client.translate` through the module so
tests can patch it.
"""

import asyncio
import time
from collections import OrderedDict

from deep_translator import GoogleTranslator, MyMemoryTranslator
from deep_translator.constants import MY_MEMORY_LANGUAGES_TO_CODES
from deep_translator.exceptions import LanguageNotSupportedException, TooManyRequests
from langdetect import detect

# Google documents 5 requests/second; stay under it across the whole bot.
MIN_INTERVAL = 0.25
# Wait before each retry after a 429. Total Google attempts = 1 + len(RETRY_DELAYS).
RETRY_DELAYS = (1, 2)
CACHE_SIZE = 256

# Our codes that MyMemory spells differently from its "xx-YY" pattern.
_MYMEMORY_OVERRIDES = {
    "en": "en-GB",
    "no": "nb-NO",
    "tl": "tl-PH",
}
_MYMEMORY_CODES = set(MY_MEMORY_LANGUAGES_TO_CODES.values())

_cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()
_throttle_lock: asyncio.Lock | None = None
_last_call = 0.0


class TranslationUnavailable(Exception):
    """Every provider refused or failed, so no translation could be made."""


def clear_cache() -> None:
    """Reset cache and throttle state (used by tests, which run one loop each)."""
    global _throttle_lock, _last_call
    _cache.clear()
    _throttle_lock = None
    _last_call = 0.0


def to_mymemory_code(code: str) -> str | None:
    """Map a Google-style code (e.g. 'es', 'zh-cn') to MyMemory's 'xx-YY' form."""
    code = code.lower()
    if code in _MYMEMORY_OVERRIDES:
        return _MYMEMORY_OVERRIDES[code]
    for candidate in _MYMEMORY_CODES:
        if candidate.lower() == code:
            return candidate
    preferred = f"{code}-{code.upper()}"
    if preferred in _MYMEMORY_CODES:
        return preferred
    prefixed = sorted(c for c in _MYMEMORY_CODES if c.split("-")[0] == code)
    return prefixed[0] if prefixed else None


async def _throttled(func, *args):
    """Run a blocking provider call in a thread, spaced MIN_INTERVAL apart bot-wide."""
    global _throttle_lock, _last_call
    if _throttle_lock is None:
        _throttle_lock = asyncio.Lock()
    async with _throttle_lock:
        wait = _last_call + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
    return await asyncio.to_thread(func, *args)


async def _translate_google(text: str, source: str, target: str) -> str:
    translator = GoogleTranslator(source=source, target=target)
    for delay in RETRY_DELAYS:
        try:
            return await _throttled(translator.translate, text)
        except TooManyRequests:
            await asyncio.sleep(delay)
    return await _throttled(translator.translate, text)


async def _translate_mymemory(text: str, source: str, target: str) -> str:
    if source == "auto":
        source = await asyncio.to_thread(detect, text)
    mm_source = to_mymemory_code(source)
    mm_target = to_mymemory_code(target)
    if mm_source is None or mm_target is None:
        raise TranslationUnavailable(f"MyMemory does not support {source}->{target}")
    translator = MyMemoryTranslator(source=mm_source, target=mm_target)
    return await _throttled(translator.translate, text)


async def translate(text: str, source: str = "auto", target: str = "en") -> str:
    """Translate `text`, trying Google first and MyMemory if Google fails.

    Raises TranslationUnavailable when both providers fail, and lets
    LanguageNotSupportedException through for a language Google does not know.
    """
    key = (source, target, text)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    try:
        result = await _translate_google(text, source, target)
    except LanguageNotSupportedException:
        # The caller's input is wrong; another provider will not fix that.
        raise
    except Exception:
        try:
            result = await _translate_mymemory(text, source, target)
        except TranslationUnavailable:
            raise
        except Exception as e:
            raise TranslationUnavailable(str(e)) from e

    _cache[key] = result
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result
