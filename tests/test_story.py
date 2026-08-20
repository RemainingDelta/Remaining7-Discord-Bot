"""Tests for validate_story_word in features/story.py."""

import pytest

from database.mongo import parse_banned_words
from features.story import (
    chunk_story_words,
    display_story_units,
    normalize_for_match,
    render_story_words,
    validate_story_word,
)

DEFAULT_BANNED_CHARS = ["_"]


# --- Accepted words ---


@pytest.mark.parametrize(
    "content,expected",
    [
        ("dragon", "dragon"),
        (" castle ", "castle"),
        ("Well-being", "Well-being"),  # hyphen is allowed by default
        ("don't", "don't"),
        ("Café", "Café"),  # original casing preserved
    ],
)
def test_accepted_words(content, expected):
    word, reason = validate_story_word(content, [], DEFAULT_BANNED_CHARS)
    assert word == expected
    assert reason is None


# --- Rejected: empty / whitespace ---


@pytest.mark.parametrize("content", ["", "   ", "\t", "\n"])
def test_rejected_empty(content):
    word, reason = validate_story_word(content, [], DEFAULT_BANNED_CHARS)
    assert word is None
    assert reason == "empty"


# --- Rejected: more than one word ---


@pytest.mark.parametrize("content", ["two words", "a b c", "hello world "])
def test_rejected_multiword(content):
    word, reason = validate_story_word(content, [], DEFAULT_BANNED_CHARS)
    assert word is None
    assert reason == "multiword"


# --- Rejected: banned character (default underscore blocks smuggling) ---


@pytest.mark.parametrize(
    "content",
    ["I_am_a_noob", "under_score", "_leading", "trailing_"],
)
def test_rejected_default_underscore(content):
    word, reason = validate_story_word(content, [], DEFAULT_BANNED_CHARS)
    assert word is None
    assert reason == "banned_char"


def test_rejected_banned_char_case_insensitive():
    word, reason = validate_story_word("aXe", [], ["x"])
    assert word is None
    assert reason == "banned_char"


# --- Rejected: emojis (Unicode and Discord custom) ---


@pytest.mark.parametrize(
    "content",
    [
        "😀",
        "hello😀",
        "🎉party",
        "⭐",
        "⌚",
        "🇺🇸",  # regional-indicator flag
        "<:pepe:123456789>",  # Discord custom emoji
        "<a:dance:987654321>",  # animated custom emoji
        "word<:x:1>",
    ],
)
def test_rejected_emoji(content):
    word, reason = validate_story_word(content, [], DEFAULT_BANNED_CHARS)
    assert word is None
    assert reason == "emoji"


# --- Rejected: banned word (case-insensitive) ---


@pytest.mark.parametrize("content", ["badword", "BadWord", "BADWORD"])
def test_rejected_banned_word(content):
    word, reason = validate_story_word(content, ["badword"], DEFAULT_BANNED_CHARS)
    assert word is None
    assert reason == "banned_word"


# --- Banned word: leet / stretched-repeat normalization ---


@pytest.mark.parametrize(
    "content",
    ["b4dword", "b@dword", "badwooooord", "b4dw0rd", "baaadword"],
)
def test_rejected_banned_word_variants(content):
    word, reason = validate_story_word(content, ["badword"], [])
    assert word is None
    assert reason == "banned_word"


def test_normalize_preserves_double_letters():
    # "as" must not collapse into a banned "ass".
    word, reason = validate_story_word("as", ["ass"], [])
    assert word == "as"
    assert reason is None
    assert normalize_for_match("as") == "as"
    assert normalize_for_match("ass") == "ass"


def test_normalize_collapses_stretch_and_leet():
    assert normalize_for_match("shiiiit") == "shit"
    assert normalize_for_match("f4ggot") == "faggot"


# --- Default banned-words list parsing (fetched remotely, seeded to DB) ---


def test_parse_banned_words_cleans_and_dedupes():
    text = "Fuck\n\n  Shit  \n# comment\nfuck\nbitch\n"
    assert parse_banned_words(text) == ["fuck", "shit", "bitch"]


def test_parse_banned_words_empty():
    assert parse_banned_words("\n\n   \n") == []


def test_parsed_default_words_block_via_validator():
    # A fetched list, once parsed, blocks profanity through the validator
    # (including leet variants via normalization).
    banned = parse_banned_words("fuck\nshit\nfaggot")
    for content in ("fuck", "sh1t", "f4ggot"):
        word, reason = validate_story_word(content, banned, [])
        assert word is None
        assert reason == "banned_word"


def test_empty_banlists_allow_underscore():
    # With no banned chars configured, underscore is permitted.
    word, reason = validate_story_word("under_score", [], [])
    assert word == "under_score"
    assert reason is None


# --- render_story_words (display casing) ---


def test_render_lowercases_and_caps_first_word():
    assert render_story_words(["Once", "Upon", "A", "TIME"]) == [
        "Once",
        "upon",
        "a",
        "time",
    ]


def test_render_caps_after_sentence_end():
    # "time." ends a sentence, so the next word is capitalized.
    assert render_story_words(["the", "END.", "a", "new", "day"]) == [
        "The",
        "end.",
        "A",
        "new",
        "day",
    ]


@pytest.mark.parametrize("ender", ["end.", "what?", "wow!"])
def test_render_various_sentence_enders(ender):
    out = render_story_words(["hi", ender, "next"])
    assert out[2] == "Next"


def test_render_ignores_trailing_quote_for_sentence_detection():
    # A trailing quote after the period still counts as a sentence end.
    assert render_story_words(['done."', "then"]) == ['Done."', "Then"]


def test_render_caps_first_alpha_past_leading_punctuation():
    assert render_story_words(['"hello']) == ['"Hello']


def test_render_empty():
    assert render_story_words([]) == []


# --- display_story_units (casing + punctuation gluing) ---


def test_display_glues_standalone_period():
    words = ["Hi", "my", "name", "is", "noob", ".", "But"]
    assert " ".join(display_story_units(words)) == "Hi my name is noob. But"


@pytest.mark.parametrize(
    "punct,expected_tail",
    [(",", "Noob,"), ("!", "Noob!"), ("?", "Noob?"), (";", "Noob;"), (")", "Noob)")],
)
def test_display_glues_various_punctuation(punct, expected_tail):
    # "noob" is the first word, so it's capitalized as the sentence start.
    units = display_story_units(["noob", punct])
    assert units == [expected_tail]


def test_display_period_still_capitalizes_next_sentence():
    # The glued period ends the sentence, so the following word is capitalized.
    assert display_story_units(["cat", ".", "dog"]) == ["Cat.", "Dog"]


def test_display_leading_punctuation_token_does_not_start_story():
    # A leading standalone punctuation has nothing to attach to; kept as-is.
    assert display_story_units([".", "hi"]) == [".", "Hi"]


# --- chunk_story_words ---


def test_chunk_story_words_single_chunk():
    assert chunk_story_words(["Once", "upon", "a", "time"]) == ["Once upon a time"]


def test_chunk_story_words_empty():
    assert chunk_story_words([]) == []


def test_chunk_story_words_splits_on_limit_without_breaking_words():
    words = ["aaaa", "bbbb", "cccc"]  # each 4 chars
    chunks = chunk_story_words(words, limit=9)  # fits two words ("aaaa bbbb" = 9)
    assert chunks == ["aaaa bbbb", "cccc"]
    assert all(len(c) <= 9 for c in chunks)
    # No word is split and reassembly preserves order.
    assert " ".join(chunks) == " ".join(words)
