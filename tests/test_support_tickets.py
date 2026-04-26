"""Tests for pure functions in features/support_tickets.py."""

from features.support_tickets import (
    _extract_opener_id,
    _strip_status_prefix,
    _active_ticket_name,
    _closed_ticket_name,
)


# --- _extract_opener_id ---


def test_extract_opener_id_simple():
    assert _extract_opener_id("support-opener:123456789") == 123456789


def test_extract_opener_id_with_type_prefix():
    assert _extract_opener_id("type:issues|support-opener:987654321") == 987654321


def test_extract_opener_id_opener_first():
    assert _extract_opener_id("support-opener:111|type:server_support") == 111


def test_extract_opener_id_none_topic():
    assert _extract_opener_id(None) is None


def test_extract_opener_id_empty_string():
    assert _extract_opener_id("") is None


def test_extract_opener_id_key_missing():
    assert _extract_opener_id("type:issues|other:stuff") is None


def test_extract_opener_id_non_numeric_value():
    assert _extract_opener_id("support-opener:notanumber") is None


# --- _strip_status_prefix ---


def test_strip_active_prefix():
    assert _strip_status_prefix("「❗」ticket-001") == "ticket-001"


def test_strip_closed_prefix():
    assert _strip_status_prefix("「👍」ticket-001") == "ticket-001"


def test_strip_no_prefix():
    assert _strip_status_prefix("ticket-001") == "ticket-001"


def test_strip_custom_prefix():
    assert _strip_status_prefix("「🔒」ticket-042") == "ticket-042"


def test_strip_preserves_channel_name_with_numbers():
    assert _strip_status_prefix("「❗」ticket-123") == "ticket-123"


# --- _active_ticket_name ---


def test_active_ticket_name_from_closed():
    assert _active_ticket_name("「👍」ticket-001") == "「❗」ticket-001"


def test_active_ticket_name_no_prefix():
    assert _active_ticket_name("ticket-001") == "「❗」ticket-001"


def test_active_ticket_name_already_active_is_idempotent():
    # Applying active to an already-active name strips and re-applies
    assert _active_ticket_name("「❗」ticket-001") == "「❗」ticket-001"


# --- _closed_ticket_name ---


def test_closed_ticket_name_from_active():
    assert _closed_ticket_name("「❗」ticket-001") == "「👍」ticket-001"


def test_closed_ticket_name_no_prefix():
    assert _closed_ticket_name("ticket-001") == "「👍」ticket-001"


def test_closed_ticket_name_already_closed_is_idempotent():
    assert _closed_ticket_name("「👍」ticket-001") == "「👍」ticket-001"


def test_active_and_closed_are_inverses():
    original = "ticket-042"
    assert _strip_status_prefix(_active_ticket_name(original)) == original
    assert _strip_status_prefix(_closed_ticket_name(original)) == original
