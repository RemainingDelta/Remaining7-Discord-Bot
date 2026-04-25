"""Tests for features/github_tickets.py — Gemini, GitHub API, and on_message listener."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from features.config import TICKET_CREATOR_ID


# --- Helpers to build mock aiohttp responses ---


def _mock_aiohttp_response(status, json_data=None, text_data=None):
    """Create a mock aiohttp response with the given status and data."""
    resp = AsyncMock()
    resp.status = status
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    if text_data is not None:
        resp.text = AsyncMock(return_value=text_data)
    else:
        resp.text = AsyncMock(return_value=json.dumps(json_data or {}))
    return resp


def _mock_session(response):
    """Create a mock aiohttp.ClientSession that returns the given response."""
    session = AsyncMock()
    session.post = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=response))
    )
    session.patch = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=response))
    )
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# --- call_gemini tests ---


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_call_gemini_success(mock_client):
    from features.github_tickets import call_gemini

    gemini_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "type": "bug",
                                    "title": "Bug: Leaderboard shows wrong user",
                                    "body": "Bug: Leaderboard shows wrong user\n\n### Overview\nThe leaderboard is broken.",
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    result = await call_gemini("the leaderboard is broken")
    assert result["type"] == "bug"
    assert "title" in result
    assert "body" in result


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_call_gemini_non_200_raises(mock_client):
    from features.github_tickets import call_gemini

    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(429, text_data="rate limited")
    )

    with pytest.raises(RuntimeError, match="Gemini API returned status 429"):
        await call_gemini("test")


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_call_gemini_invalid_json_raises(mock_client):
    from features.github_tickets import call_gemini

    gemini_response = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    with pytest.raises(RuntimeError, match="Gemini returned invalid JSON"):
        await call_gemini("test")


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_call_gemini_missing_key_raises(mock_client):
    from features.github_tickets import call_gemini

    gemini_response = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps({"type": "bug", "title": "test"})}]
                }
            }
        ]
    }
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    with pytest.raises(RuntimeError, match="missing required key: 'body'"):
        await call_gemini("test")


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_call_gemini_strips_markdown_fences(mock_client):
    from features.github_tickets import call_gemini

    raw_json = json.dumps(
        {
            "type": "feature",
            "title": "Feature: Add counting game",
            "body": "Feature: Add counting game\n\n### Overview\nA counting game.",
        }
    )
    wrapped = f"```json\n{raw_json}\n```"
    gemini_response = {"candidates": [{"content": {"parts": [{"text": wrapped}]}}]}
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    result = await call_gemini("add a counting game")
    assert result["type"] == "feature"


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_call_gemini_invalid_type_raises(mock_client):
    from features.github_tickets import call_gemini

    gemini_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {"type": "task", "title": "test", "body": "test"}
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    with pytest.raises(RuntimeError, match="invalid type: 'task'"):
        await call_gemini("test")


@pytest.mark.asyncio
async def test_call_gemini_no_token_raises():
    from features.github_tickets import call_gemini

    with patch("features.github_tickets.GEMINI_TOKEN", ""):
        with pytest.raises(RuntimeError, match="GEMINI_TOKEN"):
            await call_gemini("test")


# --- create_github_issue tests ---


@pytest.mark.asyncio
@patch("features.github_tickets.GITHUB_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_create_github_issue_success(mock_client):
    from features.github_tickets import create_github_issue

    github_response = {
        "number": 42,
        "html_url": "https://github.com/RemainingDelta/Remaining7-Discord-Bot/issues/42",
    }
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(201, json_data=github_response)
    )

    result = await create_github_issue("Test title", "Test body", "Bug")
    assert result["number"] == 42
    assert "html_url" in result


@pytest.mark.asyncio
@patch("features.github_tickets.GITHUB_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_create_github_issue_non_201_raises(mock_client):
    from features.github_tickets import create_github_issue

    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(422, text_data="Validation Failed")
    )

    with pytest.raises(RuntimeError, match="GitHub API returned status 422"):
        await create_github_issue("Test", "Body", "Bug")


@pytest.mark.asyncio
async def test_create_github_issue_no_token_raises():
    from features.github_tickets import create_github_issue

    with patch("features.github_tickets.GITHUB_TOKEN", ""):
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
            await create_github_issue("Test", "Body", "Bug")


# --- on_message listener tests ---


@pytest.mark.asyncio
async def test_on_message_ignores_bot(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = MagicMock()
    message.author.bot = True
    message.reply = AsyncMock()

    await cog.on_message(message)
    message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_no_mention(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = MagicMock()
    message.author.bot = False
    message.content = "hello world"
    message.reply = AsyncMock()

    await cog.on_message(message)
    message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_unauthorized_user(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = MagicMock()
    message.author.bot = False
    message.author.id = 999999999  # Not TICKET_CREATOR_ID
    message.content = f"<@{mock_bot.user.id}> fix the leaderboard"
    message.reply = AsyncMock()

    await cog.on_message(message)
    message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_usage_hint_on_empty_mention(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = MagicMock()
    message.author.bot = False
    message.author.id = TICKET_CREATOR_ID
    message.content = f"<@{mock_bot.user.id}>"
    message.reply = AsyncMock()

    await cog.on_message(message)
    message.reply.assert_called_once()
    call_args = message.reply.call_args
    assert "bug, enhancement, or feature" in call_args[0][
        0
    ] or "bug, enhancement, or feature" in str(call_args)


@pytest.mark.asyncio
async def test_on_message_sends_confirm_view_on_valid_mention(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = MagicMock()
    message.author.bot = False
    message.author.id = TICKET_CREATOR_ID
    message.content = f"<@{mock_bot.user.id}> the leaderboard is broken"
    message.reply = AsyncMock()

    await cog.on_message(message)
    message.reply.assert_called_once()
    call_kwargs = message.reply.call_args[1]
    assert "view" in call_kwargs
    assert call_kwargs["mention_author"] is True
