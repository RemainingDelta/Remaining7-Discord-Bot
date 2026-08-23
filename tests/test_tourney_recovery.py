"""Tests for the missed-!c sweep in features/tourney/tourney_recovery.py (#469).

Derived from #469's second acceptance criterion, with the behaviour chosen on the
ticket: a !c that landed while the bot was down should actually close the ticket,
and must do so exactly once.

The most important test here is test_closed_categories_are_never_swept. Both
increment_staff_closure and update_tourney_queue are raw $inc, and the !close
callback runs them before close_ticket_via_command does its own category check, so
restricting the sweep to the open categories is the only thing preventing a
double credit and a double queue decrement.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from features.config import (
    PRE_TOURNEY_CATEGORY_ID,
    PRE_TOURNEY_CLOSED_CATEGORY_ID,
    TOURNEY_CATEGORY_ID,
    TOURNEY_CLOSED_CATEGORY_ID,
    TOURNEY_STAFF_ROLES,
)
from features.tourney.tourney_recovery import (
    is_missed_close_message,
    is_settling_message,
    sweep_missed_closes,
)

WINDOW = datetime.datetime(2026, 8, 22, 22, 0, 0, tzinfo=datetime.timezone.utc)


def _msg(content, *, is_bot=False, staff=True):
    """A history message. Channel history is walked newest-first, so lists of these
    are written newest-first too."""
    message = MagicMock(spec=discord.Message)
    message.content = content

    if is_bot:
        message.author = MagicMock()
        message.author.bot = True
        return message

    author = MagicMock(spec=discord.Member)
    author.bot = False
    role = MagicMock()
    role.id = TOURNEY_STAFF_ROLES[0] if staff else -1
    author.roles = [role]
    message.author = author
    return message


# --- which messages count as a missed close ---


def test_bare_close_aliases_match():
    assert is_missed_close_message(_msg("!c"))
    assert is_missed_close_message(_msg("!close"))


def test_matching_is_case_insensitive():
    assert is_missed_close_message(_msg("!C"))
    assert is_missed_close_message(_msg("!Close"))


def test_surrounding_whitespace_still_matches():
    assert is_missed_close_message(_msg("  !c  "))


def test_trailing_text_still_matches():
    """discord.py ignores extra arguments by default, so `!c done` is a real close
    today and has to be treated as one here."""
    assert is_missed_close_message(_msg("!c all done"))


def test_commands_that_merely_start_with_c_do_not_match():
    for content in ("!cancel", "!closed", "!clear", "!ch"):
        assert not is_missed_close_message(_msg(content)), content


def test_the_other_ticket_commands_do_not_match():
    """Only !c/!close were approved for replay. !delete is destructive and !reopen
    was deliberately left out."""
    for content in ("!delete", "!del", "!reopen"):
        assert not is_missed_close_message(_msg(content)), content


def test_plain_chatter_does_not_match():
    for content in ("can someone close this", "c", "!", ""):
        assert not is_missed_close_message(_msg(content)), content


def test_the_bots_own_messages_are_ignored():
    assert not is_missed_close_message(_msg("!c", is_bot=True))


# --- which messages settle a ticket, making an earlier !c stale ---


def test_reopen_settles_a_ticket():
    assert is_settling_message(_msg("!reopen"))


def test_the_bots_close_confirmation_settles_a_ticket():
    assert is_settling_message(
        _msg("Ticket closed by SomeStaff and moved to Closed", is_bot=True)
    )


def test_ordinary_messages_do_not_settle_a_ticket():
    for content in ("!c", "gg", "!close", "reopen"):
        assert not is_settling_message(_msg(content)), content


def test_a_member_quoting_the_confirmation_does_not_settle_a_ticket():
    """Only the bot's own confirmation counts, or anyone could block a replay."""
    assert not is_settling_message(_msg("Ticket closed by me and moved to Closed"))


# --- the sweep ---


class _FakeHistory:
    """Stands in for TextChannel.history, recording how it was called."""

    def __init__(self, messages):
        self._messages = messages
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return _FakeHistoryIterator(self._messages)


class _FakeHistoryIterator:
    def __init__(self, messages):
        self._iterator = iter(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration from None


def _channel(name, messages, *, raises=False):
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = name
    if raises:
        channel.history = MagicMock(side_effect=RuntimeError("history unavailable"))
    else:
        channel.history = _FakeHistory(messages)
    return channel


def _category(channels):
    category = MagicMock(spec=discord.CategoryChannel)
    category.text_channels = channels
    return category


def _bot(categories, *, resolves_to="close"):
    bot = MagicMock(spec=commands.Bot)
    bot.get_channel = MagicMock(side_effect=categories.get)

    ctx = MagicMock(spec=commands.Context)
    ctx.valid = True
    ctx.command = MagicMock()
    ctx.command.qualified_name = resolves_to
    bot.get_context = AsyncMock(return_value=ctx)
    bot.invoke = AsyncMock()
    return bot


async def test_missed_close_in_an_open_ticket_is_replayed():
    channel = _channel("ticket-4", [_msg("!c")])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 1
    bot.invoke.assert_awaited_once()


async def test_pre_tourney_tickets_are_swept_too():
    channel = _channel("ticket-1", [_msg("!close")])
    bot = _bot({PRE_TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 1


async def test_closed_categories_are_never_swept():
    """A ticket that was already closed has moved to a closed category. Replaying
    into it would double-credit the staff member and double-decrement the queue."""
    channel = _channel("ticket-9", [_msg("!c")])
    bot = _bot(
        {
            TOURNEY_CLOSED_CATEGORY_ID: _category([channel]),
            PRE_TOURNEY_CLOSED_CATEGORY_ID: _category([channel]),
        }
    )

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()

    asked = [call.args[0] for call in bot.get_channel.call_args_list]
    assert TOURNEY_CLOSED_CATEGORY_ID not in asked
    assert PRE_TOURNEY_CLOSED_CATEGORY_ID not in asked


async def test_only_one_close_is_replayed_per_channel():
    """Two !c in the same gap is still one close."""
    channel = _channel("ticket-2", [_msg("!c"), _msg("!c")])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 1
    bot.invoke.assert_awaited_once()


async def test_a_reopen_after_the_close_prevents_the_replay():
    """!reopen puts a closed ticket back in a scanned category, leaving the old !c
    looking unprocessed. Re-closing it would undo a deliberate reopen."""
    channel = _channel("ticket-10", [_msg("!reopen"), _msg("!c")])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()


async def test_a_close_after_the_reopen_is_still_replayed():
    """The other ordering: reopened, then closed again, then the bot died."""
    channel = _channel("ticket-11", [_msg("!c"), _msg("!reopen")])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 1


async def test_a_completed_close_prevents_the_replay():
    """The bot's confirmation means the close already ran to completion."""
    channel = _channel(
        "ticket-12",
        [_msg("Ticket closed by Staff and moved to Closed", is_bot=True), _msg("!c")],
    )
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()


async def test_a_non_staff_close_is_not_replayed():
    """close_command bumps the closure count and the queue before checking
    permissions, so a non-staff !c must never reach it."""
    channel = _channel("ticket-13", [_msg("!c", staff=False)])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()


async def test_a_channel_with_no_missed_close_is_left_alone():
    channel = _channel("ticket-3", [_msg("gg"), _msg("!stats")])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()


async def test_history_is_bounded_to_the_downtime_window():
    channel = _channel("ticket-5", [])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])})

    await sweep_missed_closes(bot, WINDOW, sleep_between=0)

    assert channel.history.kwargs["after"] == WINDOW
    assert channel.history.kwargs["oldest_first"] is False


async def test_one_unreadable_channel_does_not_abort_the_sweep():
    """Same failure mode as the shared try/except in main.py: one error must not
    skip everything after it."""
    bot = _bot(
        {
            TOURNEY_CATEGORY_ID: _category(
                [
                    _channel("ticket-6", [], raises=True),
                    _channel("ticket-7", [_msg("!c")]),
                ]
            )
        }
    )

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 1


async def test_a_message_resolving_to_another_command_is_not_invoked():
    channel = _channel("ticket-8", [_msg("!c")])
    bot = _bot({TOURNEY_CATEGORY_ID: _category([channel])}, resolves_to="delete")

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()


async def test_a_missing_category_is_skipped():
    bot = _bot({})

    assert await sweep_missed_closes(bot, WINDOW, sleep_between=0) == 0
    bot.invoke.assert_not_awaited()
