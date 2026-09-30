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
async def test_on_message_sends_choice_view_on_valid_mention(mock_bot):
    from features.github_tickets import ChoiceView, GitHubTickets

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
    assert isinstance(call_kwargs["view"], ChoiceView)
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


# --- context collection (from the right-clicked message, #575) ---


@pytest.mark.asyncio
async def test_context_from_embed_only_error_post():
    from features.github_tickets import context_from_message

    referenced = _referenced(embeds=[_error_embed()], attachments=[_text_attachment()])
    ctx = await context_from_message(referenced)

    assert "event on_message" in ctx.text
    assert ctx.logs == ("Traceback...\nBoom",)
    assert ctx.attachment_names == ()
    assert ctx.jump_url == "https://discord.com/channels/1/2/3"


@pytest.mark.asyncio
async def test_context_from_a_plain_user_message():
    from features.github_tickets import context_from_message

    ctx = await context_from_message(_referenced(content="it broke"))
    assert ctx.text == "it broke"
    assert ctx.logs == ()


@pytest.mark.asyncio
async def test_images_are_recorded_by_name_only():
    """Discord CDN urls expire, so the filename is all that is worth keeping."""
    from features.github_tickets import context_from_message

    referenced = _referenced(content="see attached", attachments=[_image_attachment()])
    ctx = await context_from_message(referenced)

    assert ctx.attachment_names == ("screenshot.png",)
    assert ctx.logs == ()


@pytest.mark.asyncio
async def test_an_oversized_log_is_not_inlined():
    from features.github_tickets import MAX_INLINE_LOG_BYTES, context_from_message

    huge = _text_attachment(size=MAX_INLINE_LOG_BYTES + 1)
    ctx = await context_from_message(_referenced(attachments=[huge]))
    assert ctx.logs == ()


# --- body composition ---


def test_logs_are_inlined_verbatim_in_a_collapsible_block():
    """Gemini paraphrases anything routed through it, so the log is appended after."""
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("line one\nline two",), attachment_names=(), jump_url="J"
    )
    body = append_context("### Screenshots/Logs\nAttach artifacts.\n", ctx)

    assert "<details>" in body
    assert "line one\nline two" in body


def test_logs_are_attached_for_a_non_bug_ticket_too():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("stack",), attachment_names=(), jump_url="J"
    )
    body = append_context("### Overview\nA nicer button.\n", ctx)

    assert "stack" in body
    assert "<details>" in body


def test_the_original_message_text_is_attached_verbatim():
    from features.github_tickets import ReferencedContext, append_context

    report = "When I /buy the shop freezes\nand my tokens vanish"
    ctx = ReferencedContext(text=report, logs=(), attachment_names=(), jump_url="J")
    body = append_context(_gemini_body(), ctx)

    assert report in body
    assert body.index(report) < body.index("### Branch")


def test_logs_section_is_inserted_before_branch_when_template_lacks_it():
    """Enhancement/feature templates have no Screenshots/Logs heading."""
    from features.github_tickets import (
        ENHANCEMENT_TEMPLATE,
        ReferencedContext,
        append_context,
    )

    ctx = ReferencedContext(
        text="the report", logs=(), attachment_names=(), jump_url="J"
    )
    body = append_context(ENHANCEMENT_TEMPLATE, ctx)

    assert "### Screenshots/Logs" in body
    assert body.index("the report") < body.index("### Branch")
    assert body.index("### Screenshots/Logs") < body.index("### Branch")


def test_empty_sections_are_omitted():
    """No 'Screenshots/Logs: none', no empty image list."""
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(text="", logs=(), attachment_names=(), jump_url="J")
    body = append_context("### Overview\nfoo\n", ctx)

    assert "<details>" not in body
    assert "Images" not in body
    assert "J" in body  # the jump link always points at a real message


def test_jump_url_is_included_as_a_permanent_pointer():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=(), attachment_names=("a.png",), jump_url="https://d/1/2/3"
    )
    body = append_context("### Overview\nfoo\n", ctx)

    assert "https://d/1/2/3" in body
    assert "a.png" in body


# --- template cleanup ---


def test_bug_template_has_no_if_applicable_marker():
    """The marker is guidance about filling the section in, not part of the heading."""
    from features.github_tickets import BUG_TEMPLATE

    assert "### Screenshots/Logs" in BUG_TEMPLATE
    assert "if applicable" not in BUG_TEMPLATE.lower()


@pytest.mark.asyncio
async def test_on_message_reply_does_not_read_the_replied_to_message(mock_bot):
    """Without Message Content Intent the replied-to message is empty (#575)."""
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
    assert view.raw_text == "happens in DMs"
    assert view.context is None
    message.channel.fetch_message.assert_not_awaited()
    referenced.attachments[0].read.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_bare_mention_reply_gives_the_usage_hint(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = _reply_to(_referenced(content="it broke"), notes=f"<@{mock_bot.user.id}>")
    message.author = MagicMock(spec=discord.Member)
    message.author.bot = False
    message.author.id = TICKET_CREATOR_ID
    message.reply = AsyncMock()

    await cog.on_message(message)

    assert "view" not in message.reply.call_args[1]
    assert "Apps → GitHub Issue" in message.reply.call_args[0][0]


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
    body = append_context(_gemini_body(), ctx)

    assert body.index("stack trace here") < body.index("### Branch"), (
        "artifacts must sit in the Screenshots/Logs section, not below the branch"
    )


def test_an_empty_logs_section_is_removed_entirely():
    """AC: no 'Screenshots/Logs: None' left in the created ticket."""
    from features.github_tickets import append_context

    body = append_context(_gemini_body(logs_section="None"), None)

    assert "### Screenshots/Logs" not in body
    assert "None" not in body
    assert "### Branch" in body  # the rest of the template survives


def test_a_non_bug_ticket_keeps_the_logs_section():
    from features.github_tickets import ReferencedContext, append_context

    ctx = ReferencedContext(
        text="x", logs=("stack",), attachment_names=(), jump_url="J"
    )
    body = append_context(_gemini_body(), ctx)

    assert "stack" in body
    assert "J" in body


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
        context_from_message,
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
    ctx = await context_from_message(referenced)

    assert len(ctx.logs) == 2, "the budget is across attachments, not per attachment"
    assert ctx.attachment_names == ("c.log",), "the skipped log is still named"


@pytest.mark.asyncio
async def test_a_pdf_is_not_reported_as_an_image():
    from features.github_tickets import context_from_message

    pdf = _image_attachment("report.pdf")
    pdf.content_type = "application/pdf"
    ctx = await context_from_message(_referenced(attachments=[pdf]))

    assert ctx.attachment_names == ("report.pdf",)
    assert ctx.logs == ()


# --- "Create GitHub Issue" message command (#575) ---


def _creator_interaction(user_id=TICKET_CREATOR_ID):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=MagicMock())
    return interaction


@pytest.mark.asyncio
async def test_create_issue_menu_denies_anyone_but_the_ticket_creator(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    interaction = _creator_interaction(user_id=999999999)

    await cog.create_issue_from_message(interaction, _referenced(content="bug"))

    interaction.response.send_modal.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs["ephemeral"] is False


@pytest.mark.asyncio
async def test_create_issue_menu_opens_a_modal_with_one_optional_field(mock_bot):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    interaction = _creator_interaction()

    await cog.create_issue_from_message(interaction, _referenced(content="bug"))

    modal = interaction.response.send_modal.call_args.args[0]
    assert isinstance(modal, discord.ui.Modal)
    fields = [c for c in modal.children if isinstance(c, discord.ui.TextInput)]
    assert len(fields) == 1
    assert fields[0].required is False
    assert fields[0].style == discord.TextStyle.paragraph


async def _submit(modal, notes):
    from features.github_tickets import IssueNotesModal

    assert isinstance(modal, IssueNotesModal)
    modal.notes._value = notes
    interaction = _creator_interaction()
    await modal.on_submit(interaction)
    return interaction


@pytest.mark.asyncio
async def test_submitting_the_modal_offers_the_choice_with_message_and_notes():
    from features.github_tickets import ChoiceView, IssueNotesModal

    report = _referenced(embeds=[_error_embed()], attachments=[_text_attachment()])
    interaction = await _submit(IssueNotesModal(report), "happens in DMs")

    kwargs = interaction.followup.send.call_args.kwargs
    view = kwargs["view"]
    assert isinstance(view, ChoiceView)
    assert kwargs["ephemeral"] is False
    assert "event on_message" in view.raw_text
    assert "happens in DMs" in view.raw_text
    assert view.context.logs == ("Traceback...\nBoom",)
    assert view.author_id == TICKET_CREATOR_ID


@pytest.mark.asyncio
async def test_submitting_the_modal_defers_publicly():
    from features.github_tickets import IssueNotesModal

    interaction = await _submit(IssueNotesModal(_referenced(content="it broke")), "")

    interaction.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)


@pytest.mark.asyncio
async def test_submitting_the_modal_with_no_notes_still_works():
    from features.github_tickets import IssueNotesModal

    interaction = await _submit(IssueNotesModal(_referenced(content="it broke")), "")

    assert interaction.followup.send.call_args.kwargs["view"].raw_text == "it broke"


@pytest.mark.asyncio
async def test_submitting_on_an_empty_message_with_no_notes_is_refused():
    from features.github_tickets import IssueNotesModal

    interaction = await _submit(IssueNotesModal(_referenced()), "  ")

    kwargs = interaction.followup.send.call_args.kwargs
    assert "view" not in kwargs
    assert kwargs["ephemeral"] is False


@pytest.mark.asyncio
async def test_cancel_does_not_call_gemini_or_github():
    from features.github_tickets import ChoiceView

    view = ChoiceView("desc", TICKET_CREATOR_ID)
    interaction = _creator_interaction()
    with (
        patch("features.github_tickets.call_gemini", new=AsyncMock()) as gemini,
        patch("features.github_tickets.create_github_issue", new=AsyncMock()) as gh,
    ):
        await view.cancel.callback(interaction)

    gemini.assert_not_awaited()
    gh.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_the_invoker_can_press_the_choice_buttons():
    from features.github_tickets import ChoiceView

    view = ChoiceView("desc", TICKET_CREATOR_ID)
    assert await view.interaction_check(_creator_interaction()) is True
    assert await view.interaction_check(_creator_interaction(999999999)) is False


@pytest.mark.asyncio
async def test_create_attaches_the_original_message_to_a_feature_ticket():
    from features.github_tickets import FEATURE_TEMPLATE, ChoiceView, ReferencedContext

    ctx = ReferencedContext(
        text="please add dark mode", logs=(), attachment_names=(), jump_url="J"
    )
    view = ChoiceView("please add dark mode", TICKET_CREATOR_ID, ctx)
    interaction = _creator_interaction()
    ticket = {"type": "feature", "title": "Dark mode", "body": FEATURE_TEMPLATE}
    with (
        patch(
            "features.github_tickets.call_gemini", new=AsyncMock(return_value=ticket)
        ),
        patch(
            "features.github_tickets.create_github_issue",
            new=AsyncMock(return_value={"number": 900, "html_url": "u"}),
        ),
        patch("features.github_tickets.update_github_issue", new=AsyncMock()) as update,
    ):
        await view.create.callback(interaction)

    body = update.call_args.args[1]
    assert "please add dark mode" in body
    assert body.index("please add dark mode") < body.index("### Branch")
    assert "900-Feature" in body


@pytest.mark.asyncio
async def test_cog_load_registers_the_create_issue_message_command(mock_bot):
    from discord import app_commands

    from features.github_tickets import GitHubTickets

    mock_bot.tree = MagicMock()
    cog = GitHubTickets(mock_bot)

    await cog.cog_load()

    menu = mock_bot.tree.add_command.call_args.args[0]
    assert isinstance(menu, app_commands.ContextMenu)
    assert menu.name == "GitHub Issue"
    assert menu.type is discord.AppCommandType.message
    assert menu.default_permissions is not None, "hidden from regular members"


@pytest.mark.asyncio
async def test_cog_unload_removes_the_create_issue_message_command(mock_bot):
    from features.github_tickets import GitHubTickets

    mock_bot.tree = MagicMock()
    cog = GitHubTickets(mock_bot)

    await cog.cog_unload()

    mock_bot.tree.remove_command.assert_called_once_with(
        "GitHub Issue", type=discord.AppCommandType.message
    )


# --- Editing existing issues (#252) ---

ISSUE_URL = "https://github.com/RemainingDelta/Remaining7-Discord-Bot/issues/540"


def _issue(number=540, state="open", labels=("Bug",), title="Bug: shop refund crash"):
    return {
        "number": number,
        "title": title,
        "body": "### Overview\nRefunds crash the shop.",
        "state": state,
        "labels": list(labels),
        "html_url": ISSUE_URL.replace("540", str(number)),
    }


REPO_LABELS = ["Bug", "Enhancement", "Feature", "High Priority", "Medium Priority"]

WRITE_HELPERS = (
    "add_issue_comment",
    "add_issue_labels",
    "remove_issue_label",
    "set_issue_state",
    "create_github_issue",
    "update_github_issue",
)


def _patch_writes():
    """Patch every GitHub write so a test can assert none (or which) ran."""
    return {
        name: patch(f"features.github_tickets.{name}", new=AsyncMock())
        for name in WRITE_HELPERS
    }


class _Writes:
    def __init__(self):
        self._patches = _patch_writes()
        self.mocks = {}

    def __enter__(self):
        self.mocks = {name: p.start() for name, p in self._patches.items()}
        return self

    def __exit__(self, *exc):
        for p in self._patches.values():
            p.stop()

    def assert_none(self):
        for name, mock in self.mocks.items():
            assert not mock.await_count, f"{name} was called"


def _last_content(interaction):
    """The text the bot most recently put on its message."""
    calls = interaction.edit_original_response.call_args_list
    if calls:
        return calls[-1].kwargs.get("content", "")
    return interaction.response.edit_message.call_args.kwargs.get("content", "")


def _last_view(interaction):
    calls = interaction.edit_original_response.call_args_list
    return calls[-1].kwargs.get("view") if calls else None


async def _press_edit(raw_text, issue=None, changes=(), context=None, fetch=None):
    """Press Edit on a ChoiceView with the GitHub reads and Gemini mocked."""
    from features.github_tickets import ChoiceView

    view = ChoiceView(raw_text, TICKET_CREATOR_ID, context)
    interaction = _creator_interaction()
    fetch = fetch or AsyncMock(return_value=issue or _issue())
    with (
        patch("features.github_tickets.fetch_issue", new=fetch),
        patch(
            "features.github_tickets.fetch_repo_labels",
            new=AsyncMock(return_value=REPO_LABELS),
        ),
        patch(
            "features.github_tickets.call_gemini_edit",
            new=AsyncMock(return_value=list(changes)),
        ) as gemini,
        _Writes() as writes,
    ):
        await view.edit.callback(interaction)
    return interaction, gemini, fetch, writes


# issue references


def test_a_hash_number_is_an_issue_reference():
    from features.github_tickets import extract_issue_refs

    assert extract_issue_refs("close #540, it's fixed") == [540]


def test_an_issue_url_is_an_issue_reference():
    from features.github_tickets import extract_issue_refs

    assert extract_issue_refs(f"see {ISSUE_URL} again") == [540]


def test_references_keep_their_order_without_duplicates():
    from features.github_tickets import extract_issue_refs

    assert extract_issue_refs("#12 is a dupe of #540, see #12") == [12, 540]


def test_a_discord_channel_mention_is_not_an_issue_reference():
    from features.github_tickets import extract_issue_refs

    assert extract_issue_refs("broken in <#1234567890123>") == []


def test_text_without_a_number_has_no_references():
    from features.github_tickets import extract_issue_refs

    assert extract_issue_refs("the shop is broken") == []


# the choice


@pytest.mark.asyncio
async def test_a_mention_calls_neither_gemini_nor_github_before_a_button_is_pressed(
    mock_bot,
):
    from features.github_tickets import GitHubTickets

    cog = GitHubTickets(mock_bot)
    message = MagicMock()
    message.author.bot = False
    message.author.id = TICKET_CREATOR_ID
    message.content = f"<@{mock_bot.user.id}> close #540"
    message.reply = AsyncMock()
    with (
        patch("features.github_tickets.call_gemini", new=AsyncMock()) as create_ai,
        patch("features.github_tickets.call_gemini_edit", new=AsyncMock()) as edit_ai,
        patch("features.github_tickets.fetch_issue", new=AsyncMock()) as fetch,
    ):
        await cog.on_message(message)

    create_ai.assert_not_awaited()
    edit_ai.assert_not_awaited()
    fetch.assert_not_awaited()


def test_the_choice_offers_create_edit_and_cancel():
    from features.github_tickets import ChoiceView

    view = ChoiceView("desc", TICKET_CREATOR_ID)
    labels = [item.label for item in view.children]
    assert labels == ["Create new issue", "Edit existing issue", "Cancel"]


# edit: finding the issue


@pytest.mark.asyncio
async def test_edit_without_an_issue_number_is_refused_before_any_call():
    interaction, gemini, fetch, writes = await _press_edit("tweak the shop")

    assert "issue number" in _last_content(interaction)
    fetch.assert_not_awaited()
    gemini.assert_not_awaited()
    writes.assert_none()


@pytest.mark.asyncio
async def test_edit_targets_the_first_issue_number():
    changes = [{"action": "comment", "body": "dupe"}]
    interaction, gemini, fetch, _ = await _press_edit(
        "mark #540 as a duplicate of #12", changes=changes
    )

    assert fetch.await_args_list[0].args == (540,)
    assert gemini.await_args.args[1]["number"] == 540


@pytest.mark.asyncio
async def test_edit_passes_the_other_numbers_as_references():
    changes = [{"action": "comment", "body": "dupe"}]
    fetch = AsyncMock(side_effect=lambda n: _issue(number=n, title=f"Issue {n}"))
    _, gemini, _, _ = await _press_edit(
        "mark #540 as a duplicate of #12", changes=changes, fetch=fetch
    )

    references = gemini.await_args.args[3]
    assert [ref["number"] for ref in references] == [12]


@pytest.mark.asyncio
async def test_edit_on_a_missing_issue_says_so_and_skips_gemini():
    from features.github_tickets import IssueLookupError

    fetch = AsyncMock(side_effect=IssueLookupError("Issue #999 does not exist."))
    interaction, gemini, _, writes = await _press_edit("close #999", fetch=fetch)

    assert "#999 does not exist" in _last_content(interaction)
    gemini.assert_not_awaited()
    writes.assert_none()


# edit: the preview


@pytest.mark.asyncio
async def test_edit_previews_the_issue_and_every_change_before_writing():
    from features.github_tickets import EditPreviewView

    changes = [
        {"action": "comment", "body": "Fixed in v2.3"},
        {"action": "add_labels", "labels": ["High Priority"]},
        {"action": "close", "state_reason": "completed"},
    ]
    interaction, _, _, writes = await _press_edit("close #540", changes=changes)

    content = _last_content(interaction)
    assert "#540" in content
    assert "Bug: shop refund crash" in content
    assert "open" in content
    assert "Fixed in v2.3" in content
    assert "High Priority" in content
    assert "completed" in content
    assert isinstance(_last_view(interaction), EditPreviewView)
    writes.assert_none()


@pytest.mark.asyncio
async def test_edit_with_nothing_valid_to_change_says_so_without_a_preview():
    changes = [{"action": "close", "state_reason": "completed"}]
    interaction, _, _, writes = await _press_edit(
        "close #540", issue=_issue(state="closed"), changes=changes
    )

    assert "Nothing to change" in _last_content(interaction)
    assert _last_view(interaction) is None
    writes.assert_none()


def _preview(changes, issue=None, context=None):
    from features.github_tickets import EditPreviewView

    return EditPreviewView(issue or _issue(), changes, TICKET_CREATOR_ID, context)


@pytest.mark.asyncio
async def test_cancelling_the_preview_changes_nothing():
    view = _preview([{"action": "comment", "body": "x"}])
    with _Writes() as writes:
        await view.cancel.callback(_creator_interaction())
    writes.assert_none()


@pytest.mark.asyncio
async def test_only_the_invoker_can_press_the_preview_buttons():
    view = _preview([{"action": "comment", "body": "x"}])
    assert await view.interaction_check(_creator_interaction()) is True
    assert await view.interaction_check(_creator_interaction(999999999)) is False


# edit: applying


@pytest.mark.asyncio
async def test_applying_calls_exactly_the_previewed_endpoints():
    view = _preview(
        [
            {"action": "comment", "body": "Fixed in v2.3"},
            {"action": "add_labels", "labels": ["High Priority"]},
            {"action": "close", "state_reason": "completed"},
        ]
    )
    interaction = _creator_interaction()
    with _Writes() as writes:
        await view.apply.callback(interaction)

    m = writes.mocks
    m["add_issue_comment"].assert_awaited_once_with(540, "Fixed in v2.3")
    m["add_issue_labels"].assert_awaited_once_with(540, ["High Priority"])
    m["set_issue_state"].assert_awaited_once_with(540, "closed", "completed")
    m["remove_issue_label"].assert_not_awaited()
    m["create_github_issue"].assert_not_awaited()
    m["update_github_issue"].assert_not_awaited()


@pytest.mark.asyncio
async def test_applying_removes_each_label_and_can_reopen():
    view = _preview(
        [
            {"action": "remove_labels", "labels": ["Bug", "High Priority"]},
            {"action": "reopen"},
        ],
        issue=_issue(state="closed", labels=("Bug", "High Priority")),
    )
    with _Writes() as writes:
        await view.apply.callback(_creator_interaction())

    removed = [c.args for c in writes.mocks["remove_issue_label"].await_args_list]
    assert removed == [(540, "Bug"), (540, "High Priority")]
    writes.mocks["set_issue_state"].assert_awaited_once_with(540, "open", "reopened")


@pytest.mark.asyncio
async def test_applying_confirms_with_the_issue_link():
    view = _preview([{"action": "comment", "body": "x"}])
    interaction = _creator_interaction()
    with _Writes():
        await view.apply.callback(interaction)

    content = _last_content(interaction)
    assert "Updated #540" in content
    assert ISSUE_URL in content


@pytest.mark.asyncio
async def test_a_github_failure_while_applying_says_update_not_create():
    view = _preview([{"action": "comment", "body": "x"}])
    interaction = _creator_interaction()
    with _Writes() as writes:
        writes.mocks["add_issue_comment"].side_effect = RuntimeError(
            "GitHub API returned status 500: boom"
        )
        await view.apply.callback(interaction)

    content = _last_content(interaction)
    assert "update" in content.lower()
    assert "create" not in content.lower()


def _log_context():
    from features.github_tickets import ReferencedContext

    return ReferencedContext(
        text="AttributeError: boom",
        logs=("Traceback...\nBoom",),
        attachment_names=(),
        jump_url="https://discord.com/channels/1/2/3",
    )


@pytest.mark.asyncio
async def test_a_right_click_edit_puts_the_verbatim_log_in_the_comment():
    view = _preview(
        [{"action": "comment", "body": "Happened again"}], context=_log_context()
    )
    with _Writes() as writes:
        await view.apply.callback(_creator_interaction())

    body = writes.mocks["add_issue_comment"].await_args.args[1]
    assert "Happened again" in body
    assert "Traceback...\nBoom" in body
    assert "https://discord.com/channels/1/2/3" in body


@pytest.mark.asyncio
async def test_a_right_click_edit_without_a_comment_still_attaches_the_message():
    changes = [{"action": "add_labels", "labels": ["High Priority"]}]
    interaction, _, _, _ = await _press_edit(
        "this is #540 again", changes=changes, context=_log_context()
    )
    view = _last_view(interaction)
    with _Writes() as writes:
        await view.apply.callback(_creator_interaction())

    body = writes.mocks["add_issue_comment"].await_args.args[1]
    assert "Traceback...\nBoom" in body


# validation of what Gemini proposes


def _validate(changes, issue=None):
    from features.github_tickets import validate_changes

    return validate_changes(changes, issue or _issue(), REPO_LABELS)


def test_labels_that_do_not_exist_in_the_repo_are_dropped():
    result = _validate(
        [{"action": "add_labels", "labels": ["Urgent", "High Priority"]}]
    )
    assert result == [{"action": "add_labels", "labels": ["High Priority"]}]


def test_label_names_are_matched_case_insensitively():
    result = _validate([{"action": "add_labels", "labels": ["high priority"]}])
    assert result == [{"action": "add_labels", "labels": ["High Priority"]}]


def test_adding_a_label_the_issue_already_has_is_dropped():
    assert _validate([{"action": "add_labels", "labels": ["Bug"]}]) == []


def test_removing_a_label_the_issue_does_not_have_is_dropped():
    assert _validate([{"action": "remove_labels", "labels": ["Feature"]}]) == []


def test_closing_a_closed_issue_is_dropped():
    change = [{"action": "close", "state_reason": "completed"}]
    assert _validate(change, _issue(state="closed")) == []


def test_reopening_an_open_issue_is_dropped():
    assert _validate([{"action": "reopen"}]) == []


def test_closing_an_open_issue_is_kept():
    change = [{"action": "close", "state_reason": "not_planned"}]
    assert _validate(change) == change


def test_an_invalid_close_reason_becomes_completed():
    result = _validate([{"action": "close", "state_reason": "whatever"}])
    assert result == [{"action": "close", "state_reason": "completed"}]


def test_an_unknown_action_is_dropped():
    assert _validate([{"action": "rewrite_body", "body": "new"}]) == []


def test_an_empty_comment_is_dropped():
    assert _validate([{"action": "comment", "body": "   "}]) == []


# create with references


@pytest.mark.asyncio
async def test_create_reads_a_referenced_issue_without_modifying_it():
    from features.github_tickets import ENHANCEMENT_TEMPLATE, ChoiceView

    view = ChoiceView(
        "new enhancement that bumps the version like #512", TICKET_CREATOR_ID
    )
    interaction = _creator_interaction()
    ticket = {"type": "enhancement", "title": "Bump", "body": ENHANCEMENT_TEMPLATE}
    reference = _issue(number=512, title="Enhancement: bump to v1.14")
    with (
        patch(
            "features.github_tickets.fetch_issue", new=AsyncMock(return_value=reference)
        ) as fetch,
        patch(
            "features.github_tickets.call_gemini", new=AsyncMock(return_value=ticket)
        ) as gemini,
        _Writes() as writes,
    ):
        writes.mocks["create_github_issue"].return_value = {
            "number": 900,
            "html_url": "u",
        }
        await view.create.callback(interaction)

    fetch.assert_awaited_once_with(512)
    assert gemini.await_args.args[1] == [reference]
    updated = [c.args[0] for c in writes.mocks["update_github_issue"].await_args_list]
    assert updated == [900]
    for name in ("add_issue_comment", "add_issue_labels", "set_issue_state"):
        writes.mocks[name].assert_not_awaited()


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_the_create_prompt_includes_referenced_issues(mock_client):
    from features.github_tickets import call_gemini

    reply = {"type": "bug", "title": "Bug: x", "body": "### Overview\nx"}
    gemini_response = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(reply)}]}}]
    }
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    await call_gemini("like #512", [_issue(number=512, title="Enhancement: bump")])

    session = await mock_client.return_value.__aenter__()
    prompt = session.post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "#512" in prompt
    assert "Enhancement: bump" in prompt


# GitHub reads


@pytest.mark.asyncio
@patch("features.github_tickets.GITHUB_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_fetch_issue_returns_label_names(mock_client):
    from features.github_tickets import fetch_issue

    data = {
        "number": 540,
        "title": "t",
        "body": None,
        "state": "open",
        "labels": [{"name": "Bug"}],
        "html_url": ISSUE_URL,
    }
    session = _mock_session(_mock_aiohttp_response(200, json_data=data))
    inner = await session.__aenter__()
    inner.get = inner.post
    mock_client.return_value = session

    issue = await fetch_issue(540)
    assert issue["labels"] == ["Bug"]
    assert issue["body"] == ""


@pytest.mark.asyncio
@patch("features.github_tickets.GITHUB_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_fetch_issue_on_404_raises_a_lookup_error(mock_client):
    from features.github_tickets import IssueLookupError, fetch_issue

    session = _mock_session(_mock_aiohttp_response(404, json_data={}))
    inner = await session.__aenter__()
    inner.get = inner.post
    mock_client.return_value = session

    with pytest.raises(IssueLookupError, match="#999"):
        await fetch_issue(999)


@pytest.mark.asyncio
@patch("features.github_tickets.GITHUB_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_fetch_issue_on_a_pull_request_raises_a_lookup_error(mock_client):
    from features.github_tickets import IssueLookupError, fetch_issue

    data = {"number": 587, "title": "PR", "state": "closed", "labels": []}
    data["pull_request"] = {"url": "x"}
    session = _mock_session(_mock_aiohttp_response(200, json_data=data))
    inner = await session.__aenter__()
    inner.get = inner.post
    mock_client.return_value = session

    with pytest.raises(IssueLookupError, match="pull request"):
        await fetch_issue(587)


# the edit prompt's reply


@pytest.mark.asyncio
@patch("features.github_tickets.GEMINI_TOKEN", "fake-token")
@patch("features.github_tickets.aiohttp.ClientSession")
async def test_an_edit_reply_without_a_changes_list_raises(mock_client):
    from features.github_tickets import call_gemini_edit

    gemini_response = {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"x": 1})}]}}]
    }
    mock_client.return_value = _mock_session(
        _mock_aiohttp_response(200, json_data=gemini_response)
    )

    with pytest.raises(RuntimeError, match="Gemini"):
        await call_gemini_edit("close #540", _issue(), REPO_LABELS, [])
