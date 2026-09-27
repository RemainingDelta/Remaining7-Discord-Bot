"""Tests for pure functions in features/tourney/matcherino.py."""

import features.tourney.matcherino as matcherino
from features.tourney.matcherino import (
    _normalize_for_compare,
    _team_name_matches,
    clear_bracket_teams_cache,
)


# --- _normalize_for_compare ---


def test_normalize_empty_string():
    assert _normalize_for_compare("") == ""


def test_normalize_none():
    assert _normalize_for_compare(None) == ""


def test_normalize_non_string():
    assert _normalize_for_compare(123) == ""


def test_normalize_strips_and_lowercases():
    assert _normalize_for_compare("  Fire Boys  ") == "fire boys"


def test_normalize_collapses_inner_whitespace():
    assert _normalize_for_compare("Fire  Boys") == "fire boys"


def test_normalize_already_clean():
    assert _normalize_for_compare("alpha") == "alpha"


# --- _team_name_matches ---


def test_exact_match_returns_true():
    matches, ratio, name = _team_name_matches("Fire Boys", "Fire Boys", "Team Blue")
    assert matches is True
    assert ratio == 1.0
    assert name == "Fire Boys"


def test_minor_typo_passes_threshold():
    # "FireBoys" vs "Fire Boys" — one word vs two
    matches, ratio, _ = _team_name_matches("FireBoys", "Fire Boys", "Team Blue")
    assert matches is True


def test_clearly_different_teams_no_match():
    matches, ratio, _ = _team_name_matches("Xyz Random", "Alpha Squad", "Beta Force")
    assert matches is False


def test_empty_topic_always_matches():
    # No topic team name to check → skip mismatch
    matches, ratio, name = _team_name_matches("", "Alpha", "Beta")
    assert matches is True
    assert name is None


def test_both_tbd_skips_check():
    matches, ratio, name = _team_name_matches("Any Team", "tbd", "bye")
    assert matches is True
    assert name is None


def test_picks_best_matching_team():
    # topic team is closer to team_b
    matches, ratio, name = _team_name_matches("Team Blue", "Alpha Squad", "Team Blue")
    assert matches is True
    assert name == "Team Blue"


def test_tbd_slot_not_chosen_as_match():
    # team_a is tbd, so team_b should be evaluated
    matches, ratio, name = _team_name_matches("Fire Boys", "tbd", "Fire Boys")
    assert matches is True
    assert name == "Fire Boys"


# --- clear_bracket_teams_cache ---


def test_clear_bracket_teams_cache_empties_dict():
    matcherino._bracket_teams_cache["12345"] = [{"name": "Team A", "entrant_id": 1}]
    clear_bracket_teams_cache()
    assert len(matcherino._bracket_teams_cache) == 0


def test_clear_bracket_teams_cache_idempotent():
    clear_bracket_teams_cache()
    clear_bracket_teams_cache()  # calling twice should not raise
    assert len(matcherino._bracket_teams_cache) == 0


# =========================================================================
#  Prize pool / tournament name parsing (issue #443)
#
#  The bug: total_prize was initialised to 0.0 and the name scrape shared a
#  single bare-except try block with the prize scrape, so a failure to read
#  the amount was indistinguishable from a genuinely $0 prizepool and was
#  published as "$0.00" with no error and no log line.
#
#  Contract under test: the parsers return None for "could not read it" and
#  a float (possibly 0.0) for "read it successfully".
# =========================================================================

from bs4 import BeautifulSoup  # noqa: E402

from features.tourney.matcherino import (  # noqa: E402
    _parse_prize_pool,
    _parse_tournament_name,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


PAGE_WITH_AMOUNT = """
<div class="title mr-08">Remaining 7 Weekly #42</div>
<div class="prize-pool-amt"><span>$1,250.00</span></div>
"""

PAGE_ZERO_AMOUNT = """
<div class="title mr-08">Free Entry Cup</div>
<div class="prize-pool-amt"><span>$0.00</span></div>
"""

PAGE_NO_PRIZE_DIV = """
<div class="title mr-08">Remaining 7 Weekly #42</div>
"""

PAGE_NO_SPAN = """
<div class="title mr-08">Remaining 7 Weekly #42</div>
<div class="prize-pool-amt"></div>
"""

PAGE_UNPARSEABLE = """
<div class="title mr-08">Remaining 7 Weekly #42</div>
<div class="prize-pool-amt"><span>TBD</span></div>
"""


# --- _parse_prize_pool ---


def test_prize_pool_reads_real_amount():
    assert _parse_prize_pool(_soup(PAGE_WITH_AMOUNT)) == 1250.0


def test_prize_pool_zero_is_a_real_value_not_a_failure():
    # A genuinely free tourney must parse as 0.0, NOT None -- it should still post.
    assert _parse_prize_pool(_soup(PAGE_ZERO_AMOUNT)) == 0.0


def test_prize_pool_missing_div_returns_none():
    # This is the silent case that caused #443: no exception, nothing logged.
    assert _parse_prize_pool(_soup(PAGE_NO_PRIZE_DIV)) is None


def test_prize_pool_missing_span_returns_none():
    assert _parse_prize_pool(_soup(PAGE_NO_SPAN)) is None


def test_prize_pool_unparseable_text_returns_none():
    assert _parse_prize_pool(_soup(PAGE_UNPARSEABLE)) is None


def test_prize_pool_strips_currency_and_separators():
    assert (
        _parse_prize_pool(
            _soup('<div class="prize-pool-amt"><span>$12,345.67</span></div>')
        )
        == 12345.67
    )


def test_prize_pool_handles_whitespace():
    assert (
        _parse_prize_pool(
            _soup('<div class="prize-pool-amt"><span>  $500  </span></div>')
        )
        == 500.0
    )


# --- _parse_tournament_name ---


def test_name_parsed_from_primary_selector():
    assert _parse_tournament_name(_soup(PAGE_WITH_AMOUNT)) == "Remaining 7 Weekly #42"


def test_name_falls_back_to_title_container():
    html = '<div class="title-container">Fallback Cup</div>'
    assert _parse_tournament_name(_soup(html)) == "Fallback Cup"


def test_name_returns_none_when_absent():
    assert _parse_tournament_name(_soup("<div>nothing here</div>")) is None


def test_name_survives_a_missing_prize_pool():
    # The whole point of splitting the try blocks: a prize failure must not
    # cost us the name, and vice versa.
    soup = _soup(PAGE_NO_PRIZE_DIV)
    assert _parse_tournament_name(soup) == "Remaining 7 Weekly #42"
    assert _parse_prize_pool(soup) is None


# =========================================================================
#  #560: Matcherino's redesign moved the prize pool. Fixtures below are
#  trimmed from the live page for tournament 221477 ($145.50). The tw:
#  utility classes are kept as-is so the parser is proven not to rely on them.
# =========================================================================

PRIZE_SECTION_HTML = """
<section class="tw:bg-panel tw:border tw:border-border tw:rounded-xl" id="prize-pool">
  <div class="tw:flex tw:items-end tw:justify-between tw:px-[22px] tw:py-[18px]">
    <span class="tw:text-lg tw:font-bold tw:!text-white">Prize Pool</span>
    <div class="tw:flex tw:flex-col tw:items-end">
      <span class="tw:text-[26px] tw:font-extrabold tw:bg-clip-text">{amount}</span>
      <span class="tw:text-xs tw:text-muted-foreground">Current Total</span>
    </div>
  </div>
  <div class="tw:p-[22px] tw:space-y-6"></div>
</section>
"""

PRIZE_CARD_HTML = """
<div class="prize-pool-card tw:relative">
  <div class="tw:flex tw:items-center tw:gap-2 tw:mb-3">
    <span class="tw:font-semibold tw:text-sm">Prize Pool</span>
  </div>
  <div class="tw:space-y-4">
    <div><div class="tw:text-[34px] tw:font-extrabold">{amount}</div></div>
    <button class="contribute-btn tw:w-full">Contribute to Prize Pool</button>
  </div>
</div>
"""


def _section(amount: str) -> str:
    return PRIZE_SECTION_HTML.replace("{amount}", amount)


def _card(amount: str) -> str:
    return PRIZE_CARD_HTML.replace("{amount}", amount)


# --- _parse_prize_pool: new markup (#560) ---


def test_prize_pool_reads_new_prize_pool_section():
    assert _parse_prize_pool(_soup(_section("$145.50"))) == 145.50


def test_prize_pool_reads_new_sidebar_card():
    assert _parse_prize_pool(_soup(_card("$145.50"))) == 145.50


def test_prize_pool_new_markup_zero_is_a_real_value():
    assert _parse_prize_pool(_soup(_section("$0.00"))) == 0.0


def test_prize_pool_new_markup_strips_thousands_separator():
    assert _parse_prize_pool(_soup(_section("$1,250.00"))) == 1250.0


def test_prize_pool_new_markup_whole_dollars():
    assert _parse_prize_pool(_soup(_card("$500"))) == 500.0


def test_prize_pool_new_section_with_no_amount_returns_none():
    # Only the labels are present ("Prize Pool", "Current Total"); neither may
    # be mistaken for the amount.
    assert _parse_prize_pool(_soup(_section(""))) is None


def test_prize_pool_new_card_with_no_amount_returns_none():
    # The "Contribute to Prize Pool" button text must not be read as the amount.
    assert _parse_prize_pool(_soup(_card(""))) is None


def test_prize_pool_new_markup_unparseable_returns_none():
    assert _parse_prize_pool(_soup(_section("TBD"))) is None


def test_prize_pool_full_page_with_both_locations():
    page = f"<main>{_section('$145.50')}</main><aside>{_card('$145.50')}</aside>"
    assert _parse_prize_pool(_soup(page)) == 145.50


def test_prize_pool_ignores_unrelated_dollar_amounts():
    # A dollar figure elsewhere on the page (e.g. a contribution list) must
    # not be picked up when the prize pool itself is unreadable.
    page = '<section id="contributions"><span>$25.00</span></section>' + _section("")
    assert _parse_prize_pool(_soup(page)) is None


# --- _parse_tournament_name: fallbacks for the redesigned page (#560) ---


def test_name_falls_back_to_og_title():
    html = (
        '<head><meta property="og:title" content="Remaining 7 Weekly #99"></head>'
        + _section("$145.50")
    )
    assert _parse_tournament_name(_soup(html)) == "Remaining 7 Weekly #99"


def test_name_falls_back_to_title_tag_and_strips_site_suffix():
    html = "<head><title>Remaining 7 Weekly #99 | Matcherino</title></head>"
    assert _parse_tournament_name(_soup(html)) == "Remaining 7 Weekly #99"


def test_name_title_tag_that_is_only_the_site_name_is_ignored():
    html = "<head><title>Matcherino</title></head>"
    assert _parse_tournament_name(_soup(html)) is None


def test_name_legacy_selector_wins_over_og_title():
    html = (
        '<head><meta property="og:title" content="Generic"></head>'
        '<div class="title mr-08">Remaining 7 Weekly #42</div>'
    )
    assert _parse_tournament_name(_soup(html)) == "Remaining 7 Weekly #42"
