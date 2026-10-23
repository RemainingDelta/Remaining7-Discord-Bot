"""Tests for features/brawl_stars_client.py, derived from the acceptance criteria in #614."""

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from features import brawl_stars_client as bs

TOKEN = "test-token-abc123"


class _FakeResponse:
    def __init__(self, status, json_data):
        self.status = status
        self._json = json_data

    async def json(self, content_type=None):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Records every GET and replies with the queued (status, json) pairs in order.

    A queued exception is raised instead of returning a response.
    """

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        reply = self._replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return _FakeResponse(*reply)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BRAWL_STARS_TOKEN", TOKEN)
    monkeypatch.delenv("BRAWL_STARS_API_URL", raising=False)


@pytest.fixture
def no_sleep():
    with patch("features.brawl_stars_client.asyncio.sleep", new=AsyncMock()) as m:
        yield m


def _use(session):
    return patch("features.brawl_stars_client._get_session", return_value=session)


# --- Tag normalization ---


@pytest.mark.parametrize("raw", ["#abc", "abc", " ABC ", "#ABC"])
def test_normalize_tag_accepts_every_input_format(raw):
    assert bs.normalize_tag(raw) == "#ABC"


def test_normalize_tag_replaces_letter_o_with_zero():
    assert bs.normalize_tag("#o2Lo") == "#02L0"


def test_normalize_tag_rejects_empty_tag():
    with pytest.raises(ValueError):
        bs.normalize_tag(" # ")


# --- get_club / get_player ---


@pytest.mark.parametrize("raw", ["#abc", "abc", " ABC "])
async def test_get_club_returns_club_for_any_tag_format(env, raw):
    club = {"tag": "#ABC", "name": "7 Dwarves", "members": []}
    session = _FakeSession((200, club))
    with _use(session):
        result = await bs.get_club(raw)
    assert result == club
    assert session.calls[0]["url"] == "https://api.brawlstars.com/v1/clubs/%23ABC"


@pytest.mark.parametrize("raw", ["#abc", "abc", " ABC "])
async def test_get_player_returns_player_for_any_tag_format(env, raw):
    player = {"tag": "#ABC", "rankedRank": 4, "rankedRankName": "SILVER I"}
    session = _FakeSession((200, player))
    with _use(session):
        result = await bs.get_player(raw)
    assert result == player
    assert session.calls[0]["url"] == "https://api.brawlstars.com/v1/players/%23ABC"


async def test_request_sends_bearer_token(env):
    session = _FakeSession((200, {}))
    with _use(session):
        await bs.get_club("ABC")
    assert session.calls[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


# --- Rankings ---


async def test_global_club_rankings_returns_items(env):
    items = [{"tag": "#ABC", "rank": 11}]
    session = _FakeSession((200, {"items": items, "paging": {}}))
    with _use(session):
        result = await bs.get_global_club_rankings()
    assert result == items
    assert (
        session.calls[0]["url"] == "https://api.brawlstars.com/v1/rankings/global/clubs"
    )


async def test_country_club_rankings_uses_country_code(env):
    items = [{"tag": "#ABC", "rank": 3}]
    session = _FakeSession((200, {"items": items, "paging": {}}))
    with _use(session):
        result = await bs.get_country_club_rankings("us")
    assert result == items
    assert session.calls[0]["url"] == "https://api.brawlstars.com/v1/rankings/US/clubs"


# --- Error types ---


async def test_404_raises_not_found(env):
    session = _FakeSession((404, {"reason": "notFound", "message": "Not found"}))
    with _use(session), pytest.raises(bs.NotFoundError):
        await bs.get_club("ABC")


async def test_403_raises_access_denied_with_reason(env):
    body = {"reason": "accessDenied.invalidIp", "message": "Invalid authorization"}
    session = _FakeSession((403, body))
    with _use(session), pytest.raises(bs.AccessDeniedError) as exc:
        await bs.get_club("ABC")
    assert exc.value.reason == "accessDenied.invalidIp"


async def test_5xx_raises_api_unavailable(env):
    session = _FakeSession((503, {"reason": "inMaintenance"}))
    with _use(session), pytest.raises(bs.ApiUnavailableError):
        await bs.get_club("ABC")


async def test_timeout_raises_api_unavailable(env):
    session = _FakeSession(asyncio.TimeoutError())
    with _use(session), pytest.raises(bs.ApiUnavailableError):
        await bs.get_club("ABC")


async def test_connection_error_raises_api_unavailable(env):
    session = _FakeSession(aiohttp.ClientConnectionError("boom"))
    with _use(session), pytest.raises(bs.ApiUnavailableError):
        await bs.get_club("ABC")


def test_error_types_are_distinct():
    errors = [bs.NotFoundError, bs.AccessDeniedError, bs.ApiUnavailableError]
    for a in errors:
        for b in errors:
            if a is not b:
                assert not issubclass(a, b)
        assert issubclass(a, bs.BrawlStarsError)


# --- 429 retry ---


async def test_429_is_retried_then_succeeds(env, no_sleep):
    session = _FakeSession((429, {"reason": "throttled"}), (200, {"tag": "#ABC"}))
    with _use(session):
        result = await bs.get_club("ABC")
    assert result == {"tag": "#ABC"}
    assert len(session.calls) == 2
    no_sleep.assert_awaited_once_with(bs.RETRY_DELAYS[0])


async def test_429_gives_up_after_all_retries(env, no_sleep):
    attempts = 1 + len(bs.RETRY_DELAYS)
    session = _FakeSession(*[(429, {"reason": "throttled"})] * attempts)
    with _use(session), pytest.raises(bs.ApiUnavailableError):
        await bs.get_club("ABC")
    assert len(session.calls) == attempts
    assert [c.args[0] for c in no_sleep.await_args_list] == list(bs.RETRY_DELAYS)


# --- Configuration ---


async def test_base_url_env_var_changes_host(env, monkeypatch):
    monkeypatch.setenv("BRAWL_STARS_API_URL", "https://bsproxy.royaleapi.dev/v1/")
    session = _FakeSession((200, {}))
    with _use(session):
        await bs.get_club("ABC")
    assert session.calls[0]["url"] == "https://bsproxy.royaleapi.dev/v1/clubs/%23ABC"


async def test_missing_token_raises_without_calling_api(monkeypatch):
    monkeypatch.delenv("BRAWL_STARS_TOKEN", raising=False)
    session = _FakeSession()
    with _use(session), pytest.raises(bs.BrawlStarsError):
        await bs.get_club("ABC")
    assert session.calls == []


# --- Token never leaks ---


@pytest.mark.parametrize(
    "reply",
    [
        (403, {"reason": "accessDenied", "message": "Invalid authorization"}),
        (404, {"reason": "notFound"}),
        (500, {"reason": "unknown"}),
    ],
)
async def test_errors_do_not_contain_token(env, reply, capsys):
    session = _FakeSession(reply)
    with _use(session), pytest.raises(bs.BrawlStarsError) as exc:
        await bs.get_club("ABC")
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(exc.value)
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


# --- Session lifecycle ---


async def test_close_closes_shared_session():
    session = AsyncMock()
    session.closed = False
    bs._session = session
    await bs.close()
    session.close.assert_awaited_once()
    assert bs._session is None
