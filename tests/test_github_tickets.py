"""Tests for features/github_tickets.py — Gemini, GitHub API, and on_message listener."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
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
    message.reference = None  # not a reply

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
    message.reference = None  # not a reply

    await cog.on_message(message)
    message.reply.assert_called_once()
    call_kwargs = message.reply.call_args[1]
    assert "view" in call_kwargs
    assert call_kwargs["mention_author"] is True


# --- Replied-to message context (#522) ---


def _text_attachment(filename="error.txt", body=b"Traceback...\nBoom", size=None):
    att = MagicMock(spec=discord.Attachment)
    att.filename = filename
    att.size = len(body) if size is None else size
    att.content_type = "text/plain"
    att.read = AsyncMock(return_value=body)
    return att


def _image_attachment(filename="screenshot.png"):
    att = MagicMock(spec=discord.Attachment)
    att.filename = filename
    att.size = 2048
    att.content_type = "image/png"
    att.read = AsyncMock(return_value=b"\x89PNG")
    return att


def _referenced(content="", embeds=(), attachments=()):
    ref = MagicMock(spec=discord.Message)
    ref.content = content
    ref.embeds = list(embeds)
    ref.attachments = list(attachments)
    ref.jump_url = "https://discord.com/channels/1/2/3"
    return ref


def _reply_to(referenced, notes="the bot keeps dying"):
    message = MagicMock(spec=discord.Message)
    message.content = notes
    message.reference = MagicMock(spec=discord.MessageReference)
    message.reference.resolved = referenced
    message.reference.message_id = 3
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.fetch_message = AsyncMock(return_value=referenced)
    return message


def _error_embed():
    embed = discord.Embed(title="🟠 Error")
    embed.add_field(name="Source", value="`event on_message`", inline=False)
    embed.add_field(
        name="What happened",
        value="The bot used something that does not exist.",
        inline=False,
    )
    embed.add_field(name="Error", value="```AttributeError: boom```", inline=False)
    return embed


# --- embed flattening ---


def test_embed_only_message_yields_its_field_text():
    """An embed-only bot post has empty content, so the embed is the whole payload."""
    from features.github_tickets import embed_to_text

    text = embed_to_text(_error_embed())
    assert "event on_message" in text
    assert "does not exist" in text
    assert "AttributeError: boom" in text


# --- context collection ---


@pytest.mark.asyncio
async def test_context_from_embed_only_error_post():
    from features.github_tickets import collect_referenced_context

    referenced = _referenced(embeds=[_error_embed()], attachments=[_text_attachment()])
    ctx = await collect_referenced_context(_reply_to(referenced))

    assert "event on_message" in ctx.text
    assert ctx.logs == ("Traceback...\nBoom",)
    assert ctx.attachment_names == ()
    assert ctx.jump_url == "https://discord.com/channels/1/2/3"


@pytest.mark.asyncio
async def test_context_from_a_plain_user_message():
    from features.github_tickets import collect_referenced_context

    ctx = await collect_referenced_context(_reply_to(_referenced(content="it broke")))
    assert ctx.text == "it broke"
    assert ctx.logs == ()


@pytest.mark.asyncio
async def test_images_are_recorded_by_name_only():
    """Discord CDN urls expire, so the filename is all that is worth keeping."""
    from features.github_tickets import collect_referenced_context

    referenced = _referenced(content="see attached", attachments=[_image_attachment()])
    ctx = await collect_referenced_context(_reply_to(referenced))

    assert ctx.attachment_names == ("screenshot.png",)
    assert ctx.logs == ()


@pytest.mark.asyncio
async def test_no_reference_yields_no_context():
    from features.github_tickets import collect_referenced_context

    message = MagicMock(spec=discord.Message)
    message.reference = None
    assert await collect_referenced_context(message) is None


@pytest.mark.asyncio
async def test_unresolved_reference_falls_back_to_fetch():
    from features.github_tickets import collect_referenced_context

    referenced = _referenced(content="fetched")
    message = _reply_to(referenced)
    message.reference.resolved = None

    ctx = await collect_referenced_context(message)
    assert ctx.text == "fetched"
    message.channel.fetch_message.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_a_deleted_referenced_message_is_not_fatal():
    from features.github_tickets import collect_referenced_context

    message = _reply_to(_referenced())
    message.reference.resolved = None
    message.channel.fetch_message = AsyncMock(
        side_effect=discord.NotFound(MagicMock(status=404), "gone")
    )
    assert await collect_referenced_context(message) is None


@pytest.mark.asyncio
async def test_an_oversized_log_is_not_inlined():
    from features.github_tickets import MAX_INLINE_LOG_BYTES, collect_referenced_context

    huge = _text_attachment(size=MAX_INLINE_LOG_BYTES + 1)
    ctx = await collect_referenced_context(_reply_to(_referenced(attachments=[huge])))
    assert ctx.logs == ()


# --- body composition ---


def test_logs_are_inlined_verbatim_in_a_collapsible_block():
    """Gemini paraphrases anything routed through it, so the log is appended after."""
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("line one\nline two",), attachment_names=(), jump_url="J"
    )
    body = append_context("### Screenshots/Logs\nAttach artifacts.\n", ctx, "bug")

    assert "<details>" in body
    assert "line one\nline two" in body


def test_logs_are_omitted_for_a_non_bug_ticket():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("stack",), attachment_names=(), jump_url="J"
    )
    body = append_context("### Overview\nA nicer button.\n", ctx, "enhancement")

    assert "stack" not in body
    assert "<details>" not in body


def test_empty_sections_are_omitted():
    """No 'Screenshots/Logs: none', no empty image list."""
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(text="x", logs=(), attachment_names=(), jump_url="J")
    body = append_context("### Overview\nfoo\n", ctx, "bug")

    assert "<details>" not in body
    assert "Images" not in body
    assert "J" in body  # the jump link always points at a real message


def test_jump_url_is_included_as_a_permanent_pointer():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=(), attachment_names=("a.png",), jump_url="https://d/1/2/3"
    )
    body = append_context("### Overview\nfoo\n", ctx, "bug")

    assert "https://d/1/2/3" in body
    assert "a.png" in body


# --- template cleanup ---


def test_bug_template_has_no_if_applicable_marker():
    """The marker is guidance about filling the section in, not part of the heading."""
    from features.github_tickets import BUG_TEMPLATE

    assert "### Screenshots/Logs" in BUG_TEMPLATE
    assert "if applicable" not in BUG_TEMPLATE.lower()


@pytest.mark.asyncio
async def test_on_message_reply_passes_context_to_the_confirm_view(mock_bot):
    """Replying to an error post pulls its embed and log into the ticket."""
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    referenced = _referenced(embeds=[_error_embed()], attachments=[_text_attachment()])
    message = _reply_to(referenced, notes=f"<@{mock_bot.user.id}> happens in DMs")
    message.author = MagicMock(spec=discord.Member)
    message.author.bot = False
    message.author.id = TICKET_CREATOR_ID
    message.reply = AsyncMock()

    await cog.on_message(message)

    view = message.reply.call_args[1]["view"]
    assert view.context.logs == ("Traceback...\nBoom",)
    assert "event on_message" in view.raw_text
    assert "happens in DMs" in view.raw_text


@pytest.mark.asyncio
async def test_on_message_reply_with_no_notes_still_works(mock_bot):
    """A bare mention on a reply is enough; the referenced message is the content."""
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = _reply_to(_referenced(content="it broke"), notes=f"<@{mock_bot.user.id}>")
    message.author = MagicMock(spec=discord.Member)
    message.author.bot = False
    message.author.id = TICKET_CREATOR_ID
    message.reply = AsyncMock()

    await cog.on_message(message)

    assert "view" in message.reply.call_args[1]
    assert message.reply.call_args[1]["view"].raw_text == "it broke"


# --- composed body, derived from the ticket criteria not the helpers (#522) ---


def _gemini_body(
    logs_section="Attach screenshots, error logs, or any relevant artifacts.",
):
    """A body shaped like what Gemini actually returns from BUG_TEMPLATE."""
    from features.github_tickets import BUG_TEMPLATE

    return BUG_TEMPLATE.replace(
        "Attach screenshots, error logs, or any relevant artifacts.", logs_section
    )


def test_artifacts_land_under_screenshots_logs_not_after_the_branch_block():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("stack trace here",), attachment_names=(), jump_url="J"
    )
    body = append_context(_gemini_body(), ctx, "bug")

    assert body.index("stack trace here") < body.index("### Branch"), (
        "artifacts must sit in the Screenshots/Logs section, not below the branch"
    )


def test_an_empty_logs_section_is_removed_entirely():
    """AC: no 'Screenshots/Logs: None' left in the created ticket."""
    from features.github_tickets import append_context

    body = append_context(_gemini_body(logs_section="None"), None, "bug")

    assert "### Screenshots/Logs" not in body
    assert "None" not in body
    assert "### Branch" in body  # the rest of the template survives


def test_a_non_bug_ticket_drops_the_logs_section_too():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("stack",), attachment_names=(), jump_url="J"
    )
    body = append_context(_gemini_body(), ctx, "enhancement")

    assert "stack" not in body
    assert "J" in body  # the jump link still points at the source


def test_total_log_budget_is_under_the_github_body_limit():
    from features.github_tickets import GITHUB_BODY_LIMIT, MAX_TOTAL_LOG_BYTES

    assert MAX_TOTAL_LOG_BYTES < GITHUB_BODY_LIMIT, (
        "a log that passes the cap would make the issue update fail with a 422"
    )


@pytest.mark.asyncio
async def test_logs_stop_being_inlined_once_the_total_budget_is_spent():
    from features.github_tickets import (
        MAX_INLINE_LOG_BYTES,
        MAX_TOTAL_LOG_BYTES,
        collect_referenced_context,
    )

    # Each file is inside the per-file cap; together they exceed the total, so
    # the third must be left out rather than inlined.
    body = b"x" * (MAX_INLINE_LOG_BYTES - 5_000)
    assert len(body) * 3 > MAX_TOTAL_LOG_BYTES
    referenced = _referenced(
        attachments=[
            _text_attachment("a.log", body),
            _text_attachment("b.log", body),
            _text_attachment("c.log", body),
        ]
    )
    ctx = await collect_referenced_context(_reply_to(referenced))

    assert len(ctx.logs) == 2, "the budget is across attachments, not per attachment"
    assert ctx.attachment_names == ("c.log",), "the skipped log is still named"


@pytest.mark.asyncio
async def test_a_pdf_is_not_reported_as_an_image():
    from features.github_tickets import collect_referenced_context

    pdf = _image_attachment("report.pdf")
    pdf.content_type = "application/pdf"
    ctx = await collect_referenced_context(_reply_to(_referenced(attachments=[pdf])))

    assert ctx.attachment_names == ("report.pdf",)
    assert ctx.logs == ()
