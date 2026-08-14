"""Tests for pure functions in features/tourney/tourney_reports.py and
the date/URL regex patterns introduced on branch 312-Feature."""

import datetime
import re


from features.tourney.tourney_reports import (
    _month_range,
    _parse_tourney_date,
    _prev_month,
)

# Regex patterns copied from tourney_commands.py (starttourney auto-detect)
DATE_REGEX = re.compile(r"•\s*\**\s*Date:\**\s*(.+)", re.IGNORECASE)
MATCHERINO_URL_REGEX = re.compile(r"matcherino\.com/supercell/tournaments/(\d+)")

# Regex pattern from _run_monthly_report staff parsing
STAFF_LINE_REGEX = re.compile(r"<@(\d+)>: (\d+) tickets")


# ---------------------------------------------------------------------------
# _prev_month
# ---------------------------------------------------------------------------


def test_prev_month_normal():
    assert _prev_month(2026, 6) == (2026, 5)


def test_prev_month_january_rolls_back_to_december():
    assert _prev_month(2026, 1) == (2025, 12)


def test_prev_month_december():
    assert _prev_month(2026, 12) == (2026, 11)


def test_prev_month_february():
    assert _prev_month(2026, 2) == (2026, 1)


# ---------------------------------------------------------------------------
# _month_range
# ---------------------------------------------------------------------------


def test_month_range_normal():
    start, end = _month_range(2026, 6)
    assert start == datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
    assert end == datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)


def test_month_range_december_rolls_to_next_year():
    start, end = _month_range(2026, 12)
    assert start == datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc)
    assert end == datetime.datetime(2027, 1, 1, tzinfo=datetime.timezone.utc)


def test_month_range_january():
    start, end = _month_range(2026, 1)
    assert start == datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    assert end == datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)


def test_month_range_start_is_utc_aware():
    start, end = _month_range(2026, 3)
    assert start.tzinfo == datetime.timezone.utc
    assert end.tzinfo == datetime.timezone.utc


def test_month_range_date_falls_inside():
    start, end = _month_range(2026, 6)
    test_date = datetime.datetime(2026, 6, 19, tzinfo=datetime.timezone.utc)
    assert start <= test_date < end


def test_month_range_date_falls_outside():
    start, end = _month_range(2026, 6)
    test_date = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
    assert not (start <= test_date < end)


# ---------------------------------------------------------------------------
# _parse_tourney_date
# ---------------------------------------------------------------------------


def test_parse_standard_format():
    result = _parse_tourney_date("June 19, 2026")
    assert result is not None
    assert result.month == 6
    assert result.day == 19
    assert result.year == 2026


def test_parse_with_ordinal_st():
    result = _parse_tourney_date("June 1st, 2026")
    assert result is not None
    assert result.day == 1


def test_parse_with_ordinal_nd():
    result = _parse_tourney_date("June 2nd, 2026")
    assert result is not None
    assert result.day == 2


def test_parse_with_ordinal_rd():
    result = _parse_tourney_date("June 3rd, 2026")
    assert result is not None
    assert result.day == 3


def test_parse_with_ordinal_th():
    result = _parse_tourney_date("June 4th, 2026")
    assert result is not None
    assert result.day == 4


def test_parse_returns_none_for_invalid():
    assert _parse_tourney_date("not a date") is None


def test_parse_returns_none_for_empty():
    assert _parse_tourney_date("") is None


def test_parse_returns_none_for_wrong_format():
    assert _parse_tourney_date("19/06/2026") is None


def test_parse_result_is_utc_aware():
    result = _parse_tourney_date("June 19, 2026")
    assert result.tzinfo == datetime.timezone.utc


def test_parse_strips_leading_whitespace():
    result = _parse_tourney_date("  June 19, 2026")
    assert result is not None
    assert result.day == 19


# ---------------------------------------------------------------------------
# Date regex (schedule announcement parsing)
# ---------------------------------------------------------------------------


def test_date_regex_plain_format():
    content = "• Date: June 19, 2026"
    m = DATE_REGEX.search(content)
    assert m is not None
    assert m.group(1).strip() == "June 19, 2026"


def test_date_regex_bold_format():
    content = "• **Date:** June 20, 2026"
    m = DATE_REGEX.search(content)
    assert m is not None
    assert m.group(1).strip() == "June 20, 2026"


def test_date_regex_with_emoji_prefix():
    # Real announcement format: 🗓️ • **Date:** June 20, 2026
    content = "🗓️ • **Date:** June 20, 2026"
    m = DATE_REGEX.search(content)
    assert m is not None
    assert m.group(1).strip() == "June 20, 2026"


def test_date_regex_case_insensitive():
    content = "• date: June 19, 2026"
    m = DATE_REGEX.search(content)
    assert m is not None


def test_date_regex_no_match_without_bullet():
    content = "Date: June 19, 2026"
    m = DATE_REGEX.search(content)
    assert m is None


def test_date_regex_multiline_finds_correct_line():
    content = (
        "Remaining 7 NA Tourney\n"
        "🗓️ • **Date:** June 20, 2026\n"
        "🪜 • **Bracket Size:** 256 Teams\n"
        "✔️ **Register:** https://matcherino.com/supercell/tournaments/208611"
    )
    m = DATE_REGEX.search(content)
    assert m is not None
    assert m.group(1).strip() == "June 20, 2026"


# ---------------------------------------------------------------------------
# Matcherino URL regex (schedule announcement parsing)
# ---------------------------------------------------------------------------


def test_matcherino_url_extracts_id():
    content = "✔️ **Register:** https://matcherino.com/supercell/tournaments/208611"
    m = MATCHERINO_URL_REGEX.search(content)
    assert m is not None
    assert m.group(1) == "208611"


def test_matcherino_url_in_full_announcement():
    content = (
        "Remaining 7 NA Tourney\n"
        "🗓️ • **Date:** June 20, 2026\n"
        "✔️ **Register:** https://matcherino.com/supercell/tournaments/208611\n"
    )
    m = MATCHERINO_URL_REGEX.search(content)
    assert m is not None
    assert m.group(1) == "208611"


# ---------------------------------------------------------------------------
# Monthly report catch-up gating (Item 6 — missed scheduled run)
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from features.tourney import tourney_reports as tr  # noqa: E402


def _prev_month_key():
    now = datetime.datetime.now(datetime.timezone.utc)
    py, pm = _prev_month(now.year, now.month)
    return f"{py:04d}-{pm:02d}"


def _bare_cog():
    # Bypass __init__ so we don't start the scheduled/catch-up loops in a test.
    cog = tr.TourneyReports.__new__(tr.TourneyReports)
    cog.bot = MagicMock()
    return cog


async def test_monthly_report_skips_when_already_recorded(monkeypatch):
    monkeypatch.setattr(tr, "get_setting", AsyncMock(return_value=_prev_month_key()))
    ran = AsyncMock()
    stamp = AsyncMock()
    monkeypatch.setattr(tr, "_run_monthly_report", ran)
    monkeypatch.setattr(tr, "set_setting", stamp)

    await _bare_cog()._maybe_run_monthly_report()

    ran.assert_not_awaited()
    stamp.assert_not_awaited()


async def test_monthly_report_runs_and_stamps_when_new(monkeypatch):
    monkeypatch.setattr(tr, "get_setting", AsyncMock(return_value=None))
    monkeypatch.setattr(tr, "_run_monthly_report", AsyncMock(return_value="ok"))
    stamp = AsyncMock()
    monkeypatch.setattr(tr, "set_setting", stamp)

    await _bare_cog()._maybe_run_monthly_report()

    stamp.assert_awaited_once()
    key, value = stamp.call_args.args
    assert key == tr.LAST_MONTHLY_REPORT_KEY
    assert value == _prev_month_key()


async def test_monthly_report_does_not_stamp_on_error(monkeypatch):
    # A ValueError (e.g. report channel missing) must leave the marker unset so a
    # later firing or the next boot retries — never a silently-lost month.
    monkeypatch.setattr(tr, "get_setting", AsyncMock(return_value=None))
    monkeypatch.setattr(
        tr, "_run_monthly_report", AsyncMock(side_effect=ValueError("no channel"))
    )
    stamp = AsyncMock()
    monkeypatch.setattr(tr, "set_setting", stamp)

    await _bare_cog()._maybe_run_monthly_report()

    stamp.assert_not_awaited()


def test_matcherino_url_no_match_for_wrong_domain():
    content = "https://otherdomain.com/supercell/tournaments/12345"
    m = MATCHERINO_URL_REGEX.search(content)
    assert m is None


def test_matcherino_url_no_match_when_absent():
    content = "No URL in this message"
    m = MATCHERINO_URL_REGEX.search(content)
    assert m is None


# ---------------------------------------------------------------------------
# Staff line regex (_run_monthly_report embed parsing)
# ---------------------------------------------------------------------------


def test_staff_line_parses_gold_medal():
    line = "🥇 <@408419700729708545>: 54 tickets"
    matches = STAFF_LINE_REGEX.findall(line)
    assert len(matches) == 1
    assert matches[0] == ("408419700729708545", "54")


def test_staff_line_parses_numbered_entry():
    # Numbered entries like **4.** <@id>: N tickets
    line = "**4.** <@824311612227715083>: 12 tickets"
    matches = STAFF_LINE_REGEX.findall(line)
    assert len(matches) == 1
    assert matches[0] == ("824311612227715083", "12")


def test_staff_line_parses_multiple_lines():
    block = (
        "🥇 <@111>: 54 tickets\n"
        "🥈 <@222>: 23 tickets\n"
        "🥉 <@333>: 10 tickets\n"
        "**4.** <@444>: 5 tickets\n"
    )
    matches = STAFF_LINE_REGEX.findall(block)
    assert len(matches) == 4
    assert matches[0] == ("111", "54")
    assert matches[3] == ("444", "5")


def test_staff_line_aggregation_across_embeds():
    # Simulate combining two embed staff fields
    embed1 = "🥇 <@111>: 30 tickets\n🥈 <@222>: 20 tickets"
    embed2 = "🥇 <@222>: 15 tickets\n🥈 <@111>: 10 tickets"

    totals: dict[str, int] = {}
    for block in [embed1, embed2]:
        for uid, count in STAFF_LINE_REGEX.findall(block):
            totals[uid] = totals.get(uid, 0) + int(count)

    assert totals["111"] == 40
    assert totals["222"] == 35
