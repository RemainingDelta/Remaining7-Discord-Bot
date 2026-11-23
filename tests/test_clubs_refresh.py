"""Tests for the club refresh, ranked update, and country scan in features/clubs.py (#616)."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from features import brawl_stars_client as bs


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _member(tag, role="member", trophies=100_000):
    return {"tag": tag, "name": f"P{tag}", "role": role, "trophies": trophies}


def _api_club(tag, members=None, **extra):
    club = {
        "tag": tag,
        "name": f"Club {tag}",
        "trophies": 3_000_000,
        "requiredTrophies": 100_000,
        "members": members if members is not None else [_member("#M1")],
    }
    club.update(extra)
    return club


def _tracked(tag, country=None, snapshot=None):
    return {
        "_id": tag,
        "name": f"Club {tag}",
        "country_code": country,
        "snapshot": snapshot,
        "fetched_at": None,
        "failing_since": None,
    }


@pytest.fixture
def db():
    with (
        patch(
            "features.clubs.list_tracked_clubs", new=AsyncMock(return_value=[])
        ) as list_,
        patch("features.clubs.save_club_refresh", new=AsyncMock()) as save,
        patch("features.clubs.mark_club_failing", new=AsyncMock()) as failing,
        patch("features.clubs.save_club_ranked", new=AsyncMock()) as ranked,
        patch("features.clubs.save_club_countries", new=AsyncMock()) as countries,
        patch(
            "features.clubs.get_setting", new=AsyncMock(return_value=None)
        ) as get_setting,
        patch("features.clubs.set_setting", new=AsyncMock()) as set_setting,
    ):
        yield MagicMock(
            list=list_,
            save=save,
            failing=failing,
            ranked=ranked,
            countries=countries,
            get_setting=get_setting,
            set_setting=set_setting,
        )


@pytest.fixture
def api():
    clubs = {}
    country_lists = {}
    global_list = []

    async def get_club(tag):
        value = clubs[tag]
        if isinstance(value, Exception):
            raise value
        return value

    async def get_country(code):
        value = country_lists.get(code, [])
        if isinstance(value, Exception):
            raise value
        return value

    clock = [0.0]

    async def advance(seconds):
        clock[0] += seconds

    async def get_global():
        if isinstance(global_list, Exception):
            raise global_list
        return global_list

    with (
        patch(
            "features.brawl_stars_client.get_club", new=AsyncMock(side_effect=get_club)
        ) as gc,
        patch(
            "features.brawl_stars_client.get_country_club_rankings",
            new=AsyncMock(side_effect=get_country),
        ) as gcc,
        patch(
            "features.brawl_stars_client.get_global_club_rankings",
            new=AsyncMock(side_effect=get_global),
        ) as ggc,
        patch("features.brawl_stars_client.get_player", new=AsyncMock()) as gp,
        patch("features.clubs.COUNTRY_CODES", ("US", "IN")),
        # A fake clock: pausing moves it forward, requests take no time unless a
        # test advances it.
        patch("features.clubs._monotonic", new=lambda: clock[0]),
        patch("features.clubs._pause", new=AsyncMock(side_effect=advance)) as sleep,
    ):
        yield MagicMock(
            clubs=clubs,
            country_lists=country_lists,
            global_list=global_list,
            get_club=gc,
            get_country=gcc,
            get_global=ggc,
            get_player=gp,
            clock=clock,
            sleep=sleep,
        )


@pytest.fixture
def cog(mock_bot):
    from features.clubs import ClubTracking

    c = ClubTracking(mock_bot)
    c.on_refresh_complete = AsyncMock()
    return c


def _saved(db):
    """tag -> snapshot from every save_club_refresh call."""
    return {call.args[0]: call.args[2] for call in db.save.await_args_list}


# --- build_snapshot ---


def test_snapshot_counts_roles_and_trophy_range():
    from features.clubs import build_snapshot

    members = [
        _member("#A", "president", 250_000),
        _member("#B", "vicePresident", 180_000),
        _member("#C", "vicePresident", 170_000),
        _member("#D", "senior", 120_000),
        _member("#E", "member", 98_700),
    ]
    snap = build_snapshot(_api_club("#X", members), country_rank=3, global_rank=11)
    assert snap["president"] == "P#A"
    assert snap["vice_presidents"] == 2
    assert snap["seniors"] == 1
    assert snap["member_count"] == 5
    assert snap["min_member_trophies"] == 98_700
    assert snap["max_member_trophies"] == 250_000
    assert snap["trophies"] == 3_000_000
    assert snap["required_trophies"] == 100_000
    assert snap["country_rank"] == 3 and snap["global_rank"] == 11


def test_snapshot_with_no_members_has_no_range_or_president():
    from features.clubs import build_snapshot

    snap = build_snapshot(_api_club("#X", members=[]), None, None)
    assert snap["member_count"] == 0
    assert snap["president"] is None
    assert snap["min_member_trophies"] is None and snap["max_member_trophies"] is None


def test_snapshot_does_not_store_member_names_or_tags():
    from features.clubs import build_snapshot

    snap = build_snapshot(_api_club("#X", [_member("#SECRET", "senior")]), None, None)
    assert "#SECRET" not in repr(snap)
    assert "members" not in snap


# --- refresh_clubs ---


async def test_refresh_saves_snapshot_with_ranks(cog, db, api):
    db.list.return_value = [_tracked("#IN1", "US"), _tracked("#OUT", "US")]
    api.clubs.update({"#IN1": _api_club("#IN1"), "#OUT": _api_club("#OUT")})
    api.country_lists["US"] = [{"tag": "#IN1", "rank": 3}]
    api.global_list.append({"tag": "#IN1", "rank": 11})
    await cog.refresh_clubs()
    saved = _saved(db)
    assert saved["#IN1"]["country_rank"] == 3 and saved["#IN1"]["global_rank"] == 11
    assert (
        saved["#OUT"]["country_rank"] is None and saved["#OUT"]["global_rank"] is None
    )


async def test_refresh_keeps_name_in_sync(cog, db, api):
    db.list.return_value = [_tracked("#A")]
    api.clubs["#A"] = _api_club("#A", name="Renamed Club")
    await cog.refresh_clubs()
    assert db.save.await_args.args[1] == "Renamed Club"


async def test_one_failed_club_is_flagged_and_others_still_save(cog, db, api):
    db.list.return_value = [_tracked("#A"), _tracked("#BAD"), _tracked("#C")]
    api.clubs.update(
        {
            "#A": _api_club("#A"),
            "#BAD": bs.ApiUnavailableError("down"),
            "#C": _api_club("#C"),
        }
    )
    await cog.refresh_clubs()
    assert set(_saved(db)) == {"#A", "#C"}
    db.failing.assert_awaited_once_with("#BAD")


async def test_not_found_club_is_flagged_not_removed(cog, db, api):
    db.list.return_value = [_tracked("#GONE")]
    api.clubs["#GONE"] = bs.NotFoundError("gone")
    await cog.refresh_clubs()
    db.failing.assert_awaited_once_with("#GONE")
    db.save.assert_not_awaited()


async def test_refresh_request_count(cog, db, api):
    db.list.return_value = [
        _tracked("#A", "US"),
        _tracked("#B", "US"),
        _tracked("#C", "IN"),
        _tracked("#D", None),
    ]
    api.clubs.update({t: _api_club(t) for t in ("#A", "#B", "#C", "#D")})
    await cog.refresh_clubs()
    assert api.get_club.await_count == 4
    assert api.get_global.await_count == 1
    assert sorted(c.args[0] for c in api.get_country.await_args_list) == ["IN", "US"]


async def test_failed_country_list_keeps_previous_rank(cog, db, api):
    previous = {"country_rank": 7, "global_rank": None}
    db.list.return_value = [
        _tracked("#A", "US", snapshot=previous),
        _tracked("#B", "IN"),
    ]
    api.clubs.update({"#A": _api_club("#A"), "#B": _api_club("#B")})
    api.country_lists["US"] = bs.ApiUnavailableError("down")
    api.country_lists["IN"] = [{"tag": "#B", "rank": 2}]
    await cog.refresh_clubs()
    saved = _saved(db)
    assert saved["#A"]["country_rank"] == 7
    assert saved["#B"]["country_rank"] == 2


async def test_failed_global_list_keeps_previous_global_rank(cog, db, api):
    db.list.return_value = [_tracked("#A", None, snapshot={"global_rank": 11})]
    api.clubs["#A"] = _api_club("#A")

    async def boom():
        raise bs.ApiUnavailableError("down")

    api.get_global.side_effect = boom
    await cog.refresh_clubs()
    assert _saved(db)["#A"]["global_rank"] == 11


async def test_refresh_calls_completion_hook_once(cog, db, api):
    db.list.return_value = [_tracked("#A")]
    api.clubs["#A"] = _api_club("#A")
    await cog.refresh_clubs()
    cog.on_refresh_complete.assert_awaited_once()


async def test_request_refresh_waits_for_running_refresh(cog, db, api):
    running = 0
    peak = 0

    async def slow_list():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0)  # yield so the other refreshes can try the lock
        running -= 1
        return []

    db.list.side_effect = slow_list
    await asyncio.gather(
        cog.refresh_clubs(), cog.request_refresh(), cog.request_refresh()
    )
    assert peak == 1
    assert db.list.await_count == 3


# --- build_ranked ---


def _player(rank, name):
    return {"rankedRank": rank, "rankedRankName": name}


def test_build_ranked_min_max_and_tiers():
    from features.clubs import build_ranked

    ranked = build_ranked(
        [
            _player(4, "SILVER I"),
            _player(17, "LEGENDARY II"),
            _player(5, "SILVER II"),
            _player(10, "DIAMOND I"),
        ]
    )
    assert (ranked["min_rank"], ranked["min_rank_name"]) == (4, "SILVER I")
    assert (ranked["max_rank"], ranked["max_rank_name"]) == (17, "LEGENDARY II")
    assert ranked["tier_counts"] == {"SILVER": 2, "LEGENDARY": 1, "DIAMOND": 1}
    assert ranked["players_counted"] == 4


def test_build_ranked_skips_players_without_rank():
    from features.clubs import build_ranked

    ranked = build_ranked([_player(4, "SILVER I"), {"name": "no ranked data"}])
    assert ranked["players_counted"] == 1


def test_build_ranked_empty_is_none():
    from features.clubs import build_ranked

    assert build_ranked([]) is None
    assert build_ranked([{"name": "x"}]) is None


# --- Ranked update ---


async def test_ranked_update_skips_failed_player_and_saves_aggregate(cog, db, api):
    from features.clubs import RANKED_SPREAD_SECONDS

    db.list.return_value = [_tracked("#A")]
    api.clubs["#A"] = _api_club("#A", [_member("#P1"), _member("#P2"), _member("#P3")])

    async def get_player(tag):
        if tag == "#P2":
            raise bs.ApiUnavailableError("down")
        return _player(
            4 if tag == "#P1" else 10, "SILVER I" if tag == "#P1" else "DIAMOND I"
        )

    api.get_player.side_effect = get_player
    await cog.run_ranked_update()
    tag, ranked = db.ranked.await_args.args
    assert tag == "#A"
    assert ranked["players_counted"] == 2
    assert ranked["tier_counts"] == {"SILVER": 1, "DIAMOND": 1}
    total_sleep = sum(c.args[0] for c in api.sleep.await_args_list)
    assert total_sleep == pytest.approx(RANKED_SPREAD_SECONDS, rel=0.01)


async def test_ranked_update_counts_request_time_toward_spacing(cog, db, api):
    from features.clubs import RANKED_SPREAD_SECONDS

    members = [_member(f"#P{i}") for i in range(4)]
    db.list.return_value = [_tracked("#A")]
    api.clubs["#A"] = _api_club("#A", members)
    spacing = RANKED_SPREAD_SECONDS / len(members)

    async def slow_player(tag):
        api.clock[0] += spacing  # each request uses its whole slot
        return _player(4, "SILVER I")

    api.get_player.side_effect = slow_player
    await cog.run_ranked_update()
    total_sleep = sum(c.args[0] for c in api.sleep.await_args_list)
    assert total_sleep == pytest.approx(0, abs=1e-6)
    assert api.clock[0] == pytest.approx(RANKED_SPREAD_SECONDS)


async def test_ranked_update_skips_failed_club(cog, db, api):
    db.list.return_value = [_tracked("#A"), _tracked("#BAD")]
    api.clubs.update({"#A": _api_club("#A"), "#BAD": bs.ApiUnavailableError("down")})
    api.get_player.return_value = _player(4, "SILVER I")
    await cog.run_ranked_update()
    assert [c.args[0] for c in db.ranked.await_args_list] == ["#A"]


# --- Country scan ---


async def test_country_scan_sets_found_country_and_none_otherwise(cog, db, api):
    db.list.return_value = [_tracked("#US1"), _tracked("#IN1"), _tracked("#NONE")]
    api.country_lists.update(
        {"US": [{"tag": "#US1", "rank": 3}], "IN": [{"tag": "#IN1", "rank": 34}]}
    )
    assert await cog.run_country_scan_if_due() is True
    assert db.countries.await_args.args[0] == {
        "#US1": "US",
        "#IN1": "IN",
        "#NONE": None,
    }
    db.set_setting.assert_awaited_once()
    assert db.set_setting.await_args.args[0] == "club_country_scan_at"


async def test_country_scan_skips_when_last_scan_under_a_day(cog, db, api):
    db.get_setting.return_value = (_utcnow() - timedelta(hours=23)).isoformat()
    assert await cog.run_country_scan_if_due() is False
    api.get_country.assert_not_awaited()
    db.countries.assert_not_awaited()


async def test_country_scan_runs_when_last_scan_over_a_day(cog, db, api):
    db.get_setting.return_value = (_utcnow() - timedelta(hours=25)).isoformat()
    db.list.return_value = [_tracked("#A")]
    assert await cog.run_country_scan_if_due() is True
    assert sorted(c.args[0] for c in api.get_country.await_args_list) == ["IN", "US"]


async def test_country_scan_failed_list_keeps_previous_country(cog, db, api):
    db.list.return_value = [_tracked("#US1", "US"), _tracked("#X", "IN")]
    api.country_lists.update({"US": bs.ApiUnavailableError("down"), "IN": []})
    await cog.run_country_scan_if_due()
    assert db.countries.await_args.args[0] == {"#US1": "US", "#X": None}


async def test_country_scan_skips_countries_the_rankings_do_not_cover(cog, db, api):
    # A 404 means the rankings don't cover that country: it is not a failure,
    # so a club last seen there is cleared instead of kept.
    db.list.return_value = [_tracked("#IN1", "US"), _tracked("#OLD", "US")]
    api.country_lists.update(
        {"US": bs.NotFoundError("no such country"), "IN": [{"tag": "#IN1", "rank": 5}]}
    )
    assert await cog.run_country_scan_if_due() is True
    assert db.countries.await_args.args[0] == {"#IN1": "IN", "#OLD": None}


async def test_country_scan_changes_nothing_when_every_country_fails(cog, db, api):
    db.list.return_value = [_tracked("#US1", "US")]
    api.country_lists.update(
        {
            "US": bs.ApiUnavailableError("down"),
            "IN": bs.AccessDeniedError("ip", "accessDenied.invalidIp"),
        }
    )
    assert await cog.run_country_scan_if_due() is False
    db.countries.assert_not_awaited()
    db.set_setting.assert_not_awaited()


# --- Loops are not started by constructing the cog ---


def test_constructing_cog_does_not_start_loops(cog):
    assert not cog.club_refresh_loop.is_running()
    assert not cog.ranked_loop.is_running()
    assert not cog.country_scan_loop.is_running()


# --- Mongo helpers ---


def _fake_db():
    fake = MagicMock()
    fake.tracked_clubs.update_one = AsyncMock()
    fake.tracked_clubs.bulk_write = AsyncMock()
    return fake


async def test_save_club_refresh_clears_failure_flag():
    import database.mongo as mongo

    fake = _fake_db()
    with patch.object(mongo, "db", fake):
        await mongo.save_club_refresh("#A", "Club A", {"trophies": 1})
    query, update = fake.tracked_clubs.update_one.await_args.args
    assert query == {"_id": "#A"}
    assert update["$set"]["failing_since"] is None
    assert update["$set"]["snapshot"] == {"trophies": 1}
    assert update["$set"]["fetched_at"] is not None


async def test_mark_club_failing_only_sets_first_failure():
    import database.mongo as mongo

    fake = _fake_db()
    with patch.object(mongo, "db", fake):
        await mongo.mark_club_failing("#A")
    query, update = fake.tracked_clubs.update_one.await_args.args
    assert query == {"_id": "#A", "failing_since": None}
    assert set(update["$set"]) == {"failing_since"}


async def test_save_club_countries_writes_each_club():
    import database.mongo as mongo

    fake = _fake_db()
    with patch.object(mongo, "db", fake):
        await mongo.save_club_countries({"#A": "US", "#B": None})
    ops = fake.tracked_clubs.bulk_write.await_args.args[0]
    assert [(op._filter, op._doc) for op in ops] == [
        ({"_id": "#A"}, {"$set": {"country_code": "US"}}),
        ({"_id": "#B"}, {"$set": {"country_code": None}}),
    ]


async def test_country_scan_loop_refreshes_after_a_scan(cog):
    cog.run_country_scan_if_due = AsyncMock(return_value=True)
    cog.refresh_clubs = AsyncMock()
    await cog.country_scan_loop.coro(cog)
    cog.refresh_clubs.assert_awaited_once()


async def test_country_scan_loop_skips_refresh_when_not_due(cog):
    cog.run_country_scan_if_due = AsyncMock(return_value=False)
    cog.refresh_clubs = AsyncMock()
    await cog.country_scan_loop.coro(cog)
    cog.refresh_clubs.assert_not_awaited()


def test_country_codes_are_unique_two_letter_codes():
    from features.clubs import COUNTRY_CODES

    assert 240 <= len(COUNTRY_CODES) <= 252
    assert len(set(COUNTRY_CODES)) == len(COUNTRY_CODES)
    assert all(len(c) == 2 and c.isalpha() and c.isupper() for c in COUNTRY_CODES)
    assert {"US", "IN", "BR", "DE", "PH"} <= set(COUNTRY_CODES)


# --- Name cleaning ---


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("<c4>Toxic灵</c>", "Toxic灵"),
        ("<c2>Sp</c><c5>5der</c>", "Sp5der"),
        ("𝓛𝓲𝓪𝓻𝓼🥀", "Liars🥀"),
        ("𝒮𝓊𝓅𝑒𝓇", "Super"),
        ("R7|Cordite💙王嘉尔", "R7|Cordite💙王嘉尔"),
        ("  7 Dwarves ", "7 Dwarves"),
    ],
)
def test_clean_name(raw, clean):
    from features.clubs import clean_name

    assert clean_name(raw) == clean


def test_clean_name_never_returns_blank():
    from features.clubs import clean_name

    assert clean_name("<c4></c>") == "<c4></c>"
    assert clean_name(None) is None


async def test_refresh_saves_clean_club_and_president_names(cog, db, api):
    db.list.return_value = [_tracked("#A")]
    api.clubs["#A"] = _api_club(
        "#A", [_member("#P", "president")], name="<c4>𝓛𝓲𝓪𝓻𝓼</c>"
    )
    api.clubs["#A"]["members"][0]["name"] = "𝒮𝓊𝓅𝑒𝓇"
    await cog.refresh_clubs()
    tag, name, snapshot = db.save.await_args.args
    assert name == "Liars"
    assert snapshot["president"] == "Super"
