from unittest.mock import MagicMock

import discord

from features import event_tickets


class TestSanitizeUsername:
    def test_lowercases(self):
        assert (
            event_tickets._sanitize_username("ShivenAjwaliya", 42) == "shivenajwaliya"
        )

    def test_spaces_become_hyphens(self):
        assert event_tickets._sanitize_username("Cool Name", 42) == "cool-name"

    def test_strips_invalid_chars(self):
        assert event_tickets._sanitize_username("Cool_Name!!", 42) == "coolname"

    def test_strips_emoji_and_unicode(self):
        assert event_tickets._sanitize_username("😀foo", 42) == "foo"

    def test_collapses_and_trims_hyphens(self):
        assert event_tickets._sanitize_username("  a   b  ", 42) == "a-b"

    def test_empty_falls_back_to_user_id(self):
        assert event_tickets._sanitize_username("!!!", 42) == "42"

    def test_all_whitespace_falls_back_to_user_id(self):
        assert event_tickets._sanitize_username("   ", 7) == "7"

    def test_truncates_long_names(self):
        result = event_tickets._sanitize_username("a" * 200, 42)
        assert len(result) <= event_tickets._MAX_USERNAME_LEN


class TestExtractOpenerId:
    def test_valid_topic(self):
        assert event_tickets._extract_opener_id("event-opener:12345") == 12345

    def test_valid_topic_with_extra_parts(self):
        assert event_tickets._extract_opener_id("event-opener:999|foo:bar") == 999

    def test_missing_key(self):
        assert event_tickets._extract_opener_id("type:something") is None

    def test_none_topic(self):
        assert event_tickets._extract_opener_id(None) is None

    def test_empty_topic(self):
        assert event_tickets._extract_opener_id("") is None

    def test_non_numeric_value(self):
        assert event_tickets._extract_opener_id("event-opener:abc") is None


class TestTicketNameHelpers:
    def test_active_name_from_bare(self):
        assert event_tickets._active_name("event-foo") == "「❗」event-foo"

    def test_closed_name_from_bare(self):
        assert event_tickets._closed_name("event-foo") == "「👍」event-foo"

    def test_active_from_closed(self):
        assert event_tickets._active_name("「👍」event-foo") == "「❗」event-foo"

    def test_closed_from_active(self):
        assert event_tickets._closed_name("「❗」event-foo") == "「👍」event-foo"

    def test_round_trip(self):
        name = "event-shivenajwaliya"
        closed = event_tickets._closed_name(name)
        reopened = event_tickets._active_name(closed)
        assert reopened == event_tickets._active_name(name)


class TestIsEventTicketChannel:
    def _channel(self, category_id):
        channel = MagicMock(spec=discord.TextChannel)
        channel.category_id = category_id
        return channel

    def test_matches_configured_category(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 555)
        assert event_tickets.is_event_ticket_channel(self._channel(555)) is True

    def test_rejects_wrong_category(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 555)
        assert event_tickets.is_event_ticket_channel(self._channel(999)) is False

    def test_rejects_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 0)
        assert event_tickets.is_event_ticket_channel(self._channel(0)) is False

    def test_rejects_non_text_channel(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_TICKET_CATEGORY_ID", 555)
        assert event_tickets.is_event_ticket_channel(None) is False


class TestFindExistingTicket:
    def _category(self, *channels):
        category = MagicMock(spec=discord.CategoryChannel)
        category.channels = list(channels)
        return category

    def _ticket(self, name, topic):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = name
        channel.topic = topic
        return channel

    def test_open_ticket_blocks(self):
        ticket = self._ticket("「❗」event-foo", "event-opener:123")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is ticket

    def test_closed_ticket_does_not_block(self):
        """A closed ticket stays in the category, but must not lock the user out."""
        ticket = self._ticket("「👍」event-foo", "event-opener:123")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_id_prefix_does_not_collide(self):
        """User 123 must not match user 1234's ticket."""
        ticket = self._ticket("「❗」event-other", "event-opener:1234")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_other_user_ticket_ignored(self):
        ticket = self._ticket("「❗」event-other", "event-opener:999")
        category = self._category(ticket)
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_channel_without_topic_ignored(self):
        category = self._category(self._ticket("「❗」event-foo", None))
        assert event_tickets._find_existing_ticket(category, 123) is None

    def test_empty_category(self):
        assert event_tickets._find_existing_ticket(self._category(), 123) is None

    def test_finds_open_ticket_alongside_closed_one(self):
        closed = self._ticket("「👍」event-foo", "event-opener:123")
        open_ticket = self._ticket("「❗」event-foo", "event-opener:123")
        category = self._category(closed, open_ticket)
        assert event_tickets._find_existing_ticket(category, 123) is open_ticket


class TestEventStaffRoleIds:
    def test_includes_configured_role(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 12345)
        assert event_tickets._event_staff_role_ids() == {12345}

    def test_excludes_zero(self, monkeypatch):
        monkeypatch.setattr(event_tickets, "EVENT_STAFF_ROLE_ID", 0)
        assert event_tickets._event_staff_role_ids() == set()
