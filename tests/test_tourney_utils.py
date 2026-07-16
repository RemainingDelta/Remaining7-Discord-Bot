"""Tests for in-memory ticket tracking functions in features/tourney/tourney_utils.py."""

import pytest
import features.tourney.tourney_utils as tu


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all module-level state before each test."""
    tu._ticket_counter = 1
    tu._pre_tourney_ticket_counter = 1
    tu._user_open_tickets.clear()
    tu._user_last_ticket_open_time.clear()


# --- get_next_ticket_number ---


def test_ticket_number_starts_at_1():
    assert tu.get_next_ticket_number() == 1


def test_ticket_number_increments():
    assert tu.get_next_ticket_number() == 1
    assert tu.get_next_ticket_number() == 2
    assert tu.get_next_ticket_number() == 3


def test_ticket_counter_wraps_after_999():
    tu._ticket_counter = 999
    assert tu.get_next_ticket_number() == 999
    assert tu._ticket_counter == 1  # wrapped back


def test_reset_ticket_counter_sets_to_1():
    tu._ticket_counter = 42
    tu.reset_ticket_counter()
    assert tu._ticket_counter == 1


def test_reset_then_increment_from_1():
    tu._ticket_counter = 50
    tu.reset_ticket_counter()
    assert tu.get_next_ticket_number() == 1


# --- get_next_pre_tourney_ticket_number ---


def test_pre_tourney_ticket_number_starts_at_1():
    assert tu.get_next_pre_tourney_ticket_number() == 1


def test_pre_tourney_ticket_number_increments():
    assert tu.get_next_pre_tourney_ticket_number() == 1
    assert tu.get_next_pre_tourney_ticket_number() == 2


def test_pre_tourney_counter_wraps_after_999():
    tu._pre_tourney_ticket_counter = 999
    assert tu.get_next_pre_tourney_ticket_number() == 999
    assert tu._pre_tourney_ticket_counter == 1


def test_pre_tourney_and_main_counters_are_independent():
    tu.get_next_ticket_number()
    tu.get_next_ticket_number()
    assert tu.get_next_pre_tourney_ticket_number() == 1  # unaffected


# --- _get_open_ticket_count ---


def test_open_ticket_count_zero_for_unknown_user():
    assert tu._get_open_ticket_count(99999) == 0


def test_open_ticket_count_after_register():
    tu._register_ticket_for_user(111, 1001)
    assert tu._get_open_ticket_count(111) == 1


def test_open_ticket_count_multiple_tickets():
    tu._register_ticket_for_user(111, 1001)
    tu._register_ticket_for_user(111, 1002)
    assert tu._get_open_ticket_count(111) == 2


# --- _register_ticket_for_user ---


def test_register_adds_to_set():
    tu._register_ticket_for_user(222, 2001)
    assert 2001 in tu._user_open_tickets[222]


def test_register_same_channel_twice_no_duplicate():
    tu._register_ticket_for_user(222, 2001)
    tu._register_ticket_for_user(222, 2001)
    assert tu._get_open_ticket_count(222) == 1


def test_register_records_timestamp():
    tu._register_ticket_for_user(333, 3001)
    assert 333 in tu._user_last_ticket_open_time


# --- _unregister_ticket_for_user ---


def test_unregister_removes_channel():
    tu._register_ticket_for_user(444, 4001)
    tu._unregister_ticket_for_user(444, 4001)
    assert tu._get_open_ticket_count(444) == 0


def test_unregister_cleans_up_empty_set():
    tu._register_ticket_for_user(555, 5001)
    tu._unregister_ticket_for_user(555, 5001)
    assert 555 not in tu._user_open_tickets


def test_unregister_only_removes_target_channel():
    tu._register_ticket_for_user(666, 6001)
    tu._register_ticket_for_user(666, 6002)
    tu._unregister_ticket_for_user(666, 6001)
    assert tu._get_open_ticket_count(666) == 1
    assert 6002 in tu._user_open_tickets[666]


def test_unregister_nonexistent_user_does_not_raise():
    tu._unregister_ticket_for_user(777, 7001)  # user never registered


def test_unregister_nonexistent_channel_does_not_raise():
    tu._register_ticket_for_user(888, 8001)
    tu._unregister_ticket_for_user(888, 9999)  # channel not in set
    assert tu._get_open_ticket_count(888) == 1


# --- _filter_image_attachments ---


class _FakeAttachment:
    def __init__(self, content_type):
        self.content_type = content_type


def test_filter_image_attachments_none_input():
    assert tu._filter_image_attachments(None) == []


def test_filter_image_attachments_empty_list():
    assert tu._filter_image_attachments([]) == []


def test_filter_image_attachments_keeps_images():
    png = _FakeAttachment("image/png")
    jpeg = _FakeAttachment("image/jpeg")
    assert tu._filter_image_attachments([png, jpeg]) == [png, jpeg]


def test_filter_image_attachments_drops_non_images():
    png = _FakeAttachment("image/png")
    video = _FakeAttachment("video/mp4")
    text = _FakeAttachment("text/plain")
    assert tu._filter_image_attachments([png, video, text]) == [png]


def test_filter_image_attachments_drops_missing_content_type():
    unknown = _FakeAttachment(None)
    assert tu._filter_image_attachments([unknown]) == []
