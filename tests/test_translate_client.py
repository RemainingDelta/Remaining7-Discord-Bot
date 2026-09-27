"""Tests for features/translate_client.py (#573).

Google's free endpoint returns HTTP 429 under load, which deep-translator
surfaces as TooManyRequests. The shared client throttles, caches, retries,
and falls back to MyMemory so users stop seeing the raw library error.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from deep_translator.constants import MY_MEMORY_LANGUAGES_TO_CODES
from deep_translator.exceptions import RequestError, TooManyRequests

from features import translate_client
from features.translation import LANG_MAP

RAW_LIBRARY_TEXT = "too many requests"


@pytest.fixture(autouse=True)
def fast_client(monkeypatch):
    """No real waiting, and a clean cache and throttle for every test."""
    monkeypatch.setattr(translate_client, "MIN_INTERVAL", 0)
    monkeypatch.setattr(translate_client, "RETRY_DELAYS", (0, 0))
    translate_client.clear_cache()
    yield
    translate_client.clear_cache()


def google_returning(*outcomes):
    """Patch GoogleTranslator so successive translate() calls yield `outcomes`.

    An exception instance in `outcomes` is raised instead of returned.
    """
    translator = MagicMock()
    translator.translate = MagicMock(side_effect=list(outcomes))
    return patch.object(
        translate_client, "GoogleTranslator", MagicMock(return_value=translator)
    ), translator


def mymemory_returning(*outcomes):
    translator = MagicMock()
    translator.translate = MagicMock(side_effect=list(outcomes))
    cls = MagicMock(return_value=translator)
    return patch.object(translate_client, "MyMemoryTranslator", cls), translator, cls


# --- Happy path and cache ---


async def test_google_success_returns_translation():
    google_patch, google = google_returning("hello")
    mm_patch, mymemory, _ = mymemory_returning()
    with google_patch, mm_patch:
        result = await translate_client.translate("hola", source="es", target="en")
    assert result == "hello"
    mymemory.translate.assert_not_called()


async def test_repeat_request_is_served_from_cache():
    google_patch, google = google_returning("hello", "SHOULD NOT BE USED")
    with google_patch:
        first = await translate_client.translate("hola", source="es", target="en")
        second = await translate_client.translate("hola", source="es", target="en")
    assert first == second == "hello"
    assert google.translate.call_count == 1


async def test_same_text_different_target_is_not_cached_together():
    google_patch, google = google_returning("hola", "bonjour")
    with google_patch:
        es = await translate_client.translate("hello", source="en", target="es")
        fr = await translate_client.translate("hello", source="en", target="fr")
    assert (es, fr) == ("hola", "bonjour")
    assert google.translate.call_count == 2


async def test_cache_evicts_oldest_entry_past_capacity(monkeypatch):
    monkeypatch.setattr(translate_client, "CACHE_SIZE", 2)
    google_patch, google = google_returning("a", "b", "c", "a-again")
    with google_patch:
        await translate_client.translate("1", source="es", target="en")
        await translate_client.translate("2", source="es", target="en")
        await translate_client.translate("3", source="es", target="en")
        again = await translate_client.translate("1", source="es", target="en")
    assert again == "a-again"
    assert google.translate.call_count == 4


# --- Retry on 429 ---


async def test_429_then_success_is_retried():
    google_patch, google = google_returning(TooManyRequests(), "hello")
    mm_patch, mymemory, _ = mymemory_returning()
    with google_patch, mm_patch:
        result = await translate_client.translate("hola", source="es", target="en")
    assert result == "hello"
    assert google.translate.call_count == 2
    mymemory.translate.assert_not_called()


async def test_success_on_last_retry_does_not_fall_back():
    attempts = 1 + len(translate_client.RETRY_DELAYS)
    outcomes = [TooManyRequests()] * (attempts - 1) + ["hello"]
    google_patch, google = google_returning(*outcomes)
    mm_patch, mymemory, _ = mymemory_returning()
    with google_patch, mm_patch:
        result = await translate_client.translate("hola", source="es", target="en")
    assert result == "hello"
    assert google.translate.call_count == attempts
    mymemory.translate.assert_not_called()


async def test_retry_waits_between_attempts(monkeypatch):
    monkeypatch.setattr(translate_client, "RETRY_DELAYS", (1, 2))
    sleep = AsyncMock()
    monkeypatch.setattr(translate_client.asyncio, "sleep", sleep)
    google_patch, _ = google_returning(TooManyRequests(), TooManyRequests(), "hello")
    with google_patch:
        await translate_client.translate("hola", source="es", target="en")
    waits = [c.args[0] for c in sleep.await_args_list if c.args and c.args[0] > 0]
    assert waits == [1, 2]


# --- Fallback to MyMemory ---


async def test_persistent_429_falls_back_to_mymemory():
    attempts = 1 + len(translate_client.RETRY_DELAYS)
    google_patch, google = google_returning(*[TooManyRequests()] * attempts)
    mm_patch, mymemory, _ = mymemory_returning("hello")
    with google_patch, mm_patch:
        result = await translate_client.translate("hola", source="es", target="en")
    assert result == "hello"
    assert google.translate.call_count == attempts


async def test_google_request_error_falls_back_without_retrying():
    google_patch, google = google_returning(RequestError(), "SHOULD NOT BE USED")
    mm_patch, _, _ = mymemory_returning("hello")
    with google_patch, mm_patch:
        result = await translate_client.translate("hola", source="es", target="en")
    assert result == "hello"
    assert google.translate.call_count == 1


async def test_fallback_uses_mymemory_language_codes():
    google_patch, _ = google_returning(RequestError())
    mm_patch, _, cls = mymemory_returning("你好")
    with google_patch, mm_patch:
        await translate_client.translate("hello", source="en", target="zh-cn")
    kwargs = cls.call_args.kwargs
    valid = set(MY_MEMORY_LANGUAGES_TO_CODES.values())
    assert kwargs["source"] in valid and kwargs["source"].startswith("en")
    assert kwargs["target"] == "zh-CN"


async def test_fallback_detects_language_when_source_is_auto():
    google_patch, _ = google_returning(RequestError())
    mm_patch, _, cls = mymemory_returning("hello")
    with (
        google_patch,
        mm_patch,
        patch.object(translate_client, "detect", return_value="es"),
    ):
        await translate_client.translate("hola amigos", source="auto", target="en")
    assert cls.call_args.kwargs["source"].startswith("es-")


def test_every_supported_language_has_a_mymemory_code():
    """Otherwise the fallback silently cannot help for that language."""
    valid = set(MY_MEMORY_LANGUAGES_TO_CODES.values())
    unmapped = [
        code
        for code in LANG_MAP
        if translate_client.to_mymemory_code(code) not in valid
    ]
    assert unmapped == []


async def test_both_providers_failing_raises_translation_unavailable():
    attempts = 1 + len(translate_client.RETRY_DELAYS)
    google_patch, _ = google_returning(*[TooManyRequests()] * attempts)
    mm_patch, _, _ = mymemory_returning(TooManyRequests())
    with google_patch, mm_patch:
        with pytest.raises(translate_client.TranslationUnavailable):
            await translate_client.translate("hola", source="es", target="en")


async def test_failure_is_not_cached():
    attempts = 1 + len(translate_client.RETRY_DELAYS)
    google_patch, google = google_returning(*[TooManyRequests()] * attempts, "hello")
    mm_patch, _, _ = mymemory_returning(RequestError())
    with google_patch, mm_patch:
        with pytest.raises(translate_client.TranslationUnavailable):
            await translate_client.translate("hola", source="es", target="en")
        result = await translate_client.translate("hola", source="es", target="en")
    assert result == "hello"


# --- Throttle ---


async def test_concurrent_calls_are_spaced_by_min_interval(monkeypatch):
    import asyncio

    interval = 0.05
    monkeypatch.setattr(translate_client, "MIN_INTERVAL", interval)
    call_times = []

    def fake_translate(text):
        call_times.append(time.monotonic())
        return text.upper()

    translator = MagicMock()
    translator.translate = MagicMock(side_effect=fake_translate)
    with patch.object(
        translate_client, "GoogleTranslator", MagicMock(return_value=translator)
    ):
        await asyncio.gather(
            *(
                translate_client.translate(t, source="es", target="en")
                for t in ("a", "b", "c", "d")
            )
        )

    gaps = [b - a for a, b in zip(call_times, call_times[1:])]
    assert len(gaps) == 3
    # small tolerance for timer resolution
    assert all(gap >= interval - 0.005 for gap in gaps), gaps


# --- Callers ---


def _prefix_ctx(text="hola amigos"):
    original = MagicMock()
    original.content = text
    ctx = MagicMock()
    ctx.message.reference.message_id = 42
    ctx.channel.fetch_message = AsyncMock(return_value=original)
    ctx.reply = AsyncMock()
    ctx.author.display_name = "TestUser"
    return ctx


def _sent_text(mock_send):
    call = mock_send.await_args
    return (
        " ".join(str(a) for a in call.args) + " " + str(call.kwargs.get("content", ""))
    )


async def test_prefix_translate_shows_friendly_message_when_unavailable():
    from features.translation import Translation

    cog = Translation(MagicMock())
    ctx = _prefix_ctx()
    with (
        patch("features.translation.detect", return_value="es"),
        patch.object(
            translate_client,
            "translate",
            AsyncMock(side_effect=translate_client.TranslationUnavailable()),
        ),
    ):
        await cog.translate_prefix.callback(cog, ctx, None)

    ctx.reply.assert_awaited_once()
    text = _sent_text(ctx.reply)
    assert RAW_LIBRARY_TEXT not in text.lower()
    assert "busy" in text.lower()


async def test_slash_translate_shows_friendly_message_when_unavailable(
    mock_interaction,
):
    from features.translation import Translation

    cog = Translation(MagicMock())
    with patch.object(
        translate_client,
        "translate",
        AsyncMock(side_effect=translate_client.TranslationUnavailable()),
    ):
        await cog.translate_slash.callback(cog, mock_interaction, "es", "hello")

    mock_interaction.followup.send.assert_awaited_once()
    text = _sent_text(mock_interaction.followup.send)
    assert RAW_LIBRARY_TEXT not in text.lower()
    assert "busy" in text.lower()


async def test_prefix_translate_goes_through_shared_client():
    from features.translation import Translation

    cog = Translation(MagicMock())
    ctx = _prefix_ctx()
    client = AsyncMock(return_value="hello friends")
    with (
        patch("features.translation.detect", return_value="es"),
        patch.object(translate_client, "translate", client),
    ):
        await cog.translate_prefix.callback(cog, ctx, None)

    client.assert_awaited_once()
    embed = ctx.reply.await_args.kwargs["embed"]
    assert any("hello friends" in f.value for f in embed.fields)


async def test_ticket_translation_returns_none_when_unavailable():
    from features.tourney import tourney_utils

    with (
        patch.object(tourney_utils, "detect", return_value="es"),
        patch.object(
            translate_client,
            "translate",
            AsyncMock(side_effect=translate_client.TranslationUnavailable()),
        ),
    ):
        assert await tourney_utils._get_translation("hola amigos") is None


async def test_ticket_translation_goes_through_shared_client():
    from features.tourney import tourney_utils

    client = AsyncMock(return_value="hello friends")
    with (
        patch.object(tourney_utils, "detect", return_value="es"),
        patch.object(translate_client, "translate", client),
    ):
        assert await tourney_utils._get_translation("hola amigos") == "hello friends"
    client.assert_awaited_once()
