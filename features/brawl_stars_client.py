"""Shared client for the official Brawl Stars API (#614).

Every club tracking feature goes through this module so requests share one
HTTP session, tags are normalized the same way everywhere, and callers can
tell a missing club, a rejected key, and an API outage apart.

The key is IP-allowlisted, so an AccessDeniedError with reason
"accessDenied.invalidIp" means the host's IP changed and the key must be
recreated. The base URL can point at a proxy (e.g. RoyaleAPI) instead.

Callers should reference functions through the module so tests can patch them.
"""

import asyncio
import os

import aiohttp

DEFAULT_BASE_URL = "https://api.brawlstars.com/v1"
TIMEOUT = aiohttp.ClientTimeout(total=10)
# Wait before each retry after a 429. Total attempts = 1 + len(RETRY_DELAYS).
RETRY_DELAYS = (1, 2, 4)

_session: aiohttp.ClientSession | None = None


class BrawlStarsError(Exception):
    """Base class for every error raised by this client."""

    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


class NotFoundError(BrawlStarsError):
    """The club or player does not exist (HTTP 404)."""


class AccessDeniedError(BrawlStarsError):
    """The key was rejected (HTTP 403), e.g. reason 'accessDenied.invalidIp'."""


class ApiUnavailableError(BrawlStarsError):
    """The API is down, timed out, or kept rate limiting us."""


def normalize_tag(tag: str) -> str:
    """Return a tag as '#ABC123': uppercase, trimmed, '#'-prefixed, O replaced by 0."""
    cleaned = tag.strip().upper().lstrip("#").strip().replace("O", "0")
    if not cleaned:
        raise ValueError("Tag is empty")
    return f"#{cleaned}"


def _encode_tag(tag: str) -> str:
    return "%23" + normalize_tag(tag)[1:]


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=TIMEOUT)
    return _session


async def close() -> None:
    """Close the shared session (call from the owning cog's cog_unload)."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def _request(path: str):
    token = os.getenv("BRAWL_STARS_TOKEN")
    if not token:
        raise BrawlStarsError("BRAWL_STARS_TOKEN is not set")
    base_url = os.getenv("BRAWL_STARS_API_URL") or DEFAULT_BASE_URL
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            async with _get_session().get(
                url, headers=headers, timeout=TIMEOUT
            ) as resp:
                status = resp.status
                data = await resp.json(content_type=None)
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            raise ApiUnavailableError(
                f"Request to {path} failed: {type(e).__name__}"
            ) from e

        if status == 200:
            return data

        reason = data.get("reason") if isinstance(data, dict) else None
        if status == 429 and attempt < len(RETRY_DELAYS):
            await asyncio.sleep(RETRY_DELAYS[attempt])
            continue
        if status == 404:
            raise NotFoundError(f"{path} not found", reason)
        if status == 403:
            raise AccessDeniedError(f"Access denied for {path} ({reason})", reason)
        raise ApiUnavailableError(f"{path} returned HTTP {status} ({reason})", reason)


async def get_club(tag: str) -> dict:
    return await _request(f"/clubs/{_encode_tag(tag)}")


async def get_player(tag: str) -> dict:
    return await _request(f"/players/{_encode_tag(tag)}")


async def get_global_club_rankings() -> list[dict]:
    """Top 200 clubs worldwide."""
    return (await _request("/rankings/global/clubs"))["items"]


async def get_country_club_rankings(country_code: str) -> list[dict]:
    """Top 200 clubs in one country, e.g. 'US'."""
    return (await _request(f"/rankings/{country_code.strip().upper()}/clubs"))["items"]
