"""Tests for the privacy policy content module, command, and startup repost.

Cases derive from #490's acceptance criteria: one source of truth for the policy
text, embeds that fit inside Discord's limits, a public command, a tickets link
that follows the REAL/TEST config split, and a channel kept current on restart.
"""

import ast
import importlib
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from features.config import OTHER_TICKET_CHANNEL_ID
from features.privacy_policy import (
    LAST_UPDATED,
    POLICY_PARTS,
    POLICY_URL,
    PrivacyPolicy,
    build_privacy_embeds,
    repost_privacy_policy,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Discord's documented limits, written out rather than imported from the module
# under test so a wrong constant there cannot make these pass.
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_MESSAGE_TOTAL_LIMIT = 6000

# The headings of the policy as filed in the ticket, in order.
POLICY_HEADINGS = [
    "Who we are",
    "What information we collect",
    "What we do not collect or store",
    "Why we collect this information",
    "Where your information is stored",
    "When information leaves Discord",
    "Opt-out and your choices",
    "Age requirement",
    "Changes to this policy",
    "Contact us",
]

PROD_GUILD_ID = 294192597939912714
PROD_TICKETS_CHANNEL_ID = 1259649295649472602

GUILD_ID = 111111111
CONFIGURED_PRIVACY_CHANNEL_ID = 222222222


def _sections():
    return [section for part in POLICY_PARTS for section in part.sections]


def _rendered(embeds):
    """All user-visible text of an embed sequence, joined."""
    chunks = []
    for embed in embeds:
        chunks.append(embed.title or "")
        chunks.append(embed.description or "")
        chunks.append(embed.footer.text or "" if embed.footer else "")
    return "\n".join(chunks)


class _AsyncIter:
    """Stands in for the async iterator returned by TextChannel.history()."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        async def gen():
            for item in self._items:
                yield item

        return gen()


def _privacy_channel(messages):
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "privacy-policy"
    channel.guild = MagicMock(spec=discord.Guild)
    channel.guild.id = GUILD_ID
    channel.history = MagicMock(return_value=_AsyncIter(messages))
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def privacy_channel_configured(monkeypatch):
    """Stand in for a server that has had its privacy channel set up."""
    import features.privacy_policy as module

    monkeypatch.setattr(module, "PRIVACY_CHANNEL_ID", CONFIGURED_PRIVACY_CHANNEL_ID)


def _message(author):
    message = MagicMock(spec=discord.Message)
    message.author = author
    message.delete = AsyncMock()
    return message


# --- content module ---


def test_policy_sections_match_the_filed_headings_in_order():
    assert [section.heading for section in _sections()] == POLICY_HEADINGS


def test_every_section_has_a_body():
    for section in _sections():
        assert section.body.strip(), f"{section.heading} has no body"


def test_policy_renders_two_or_three_embeds():
    embeds = build_privacy_embeds(GUILD_ID)
    assert 2 <= len(embeds) <= 3


def test_each_embed_description_is_within_discord_limit():
    for embed in build_privacy_embeds(GUILD_ID):
        assert len(embed.description) <= EMBED_DESCRIPTION_LIMIT


def test_embed_sequence_fits_in_one_message():
    total = sum(len(embed) for embed in build_privacy_embeds(GUILD_ID))
    assert total <= EMBED_MESSAGE_TOTAL_LIMIT


def test_every_embed_has_a_title():
    for embed in build_privacy_embeds(GUILD_ID):
        assert embed.title


def test_every_section_body_is_rendered_somewhere():
    rendered = _rendered(build_privacy_embeds(GUILD_ID))
    for section in _sections():
        # The contact section is templated with the tickets link, so compare on
        # its first sentence rather than the whole body.
        opening = section.body.strip().split(".")[0]
        assert opening in rendered, f"{section.heading} is missing from the embeds"


def test_last_embed_carries_the_last_updated_date():
    embeds = build_privacy_embeds(GUILD_ID)
    assert LAST_UPDATED in _rendered([embeds[-1]])


def test_last_updated_matches_the_filed_date():
    assert LAST_UPDATED == "August 28, 2026"


def test_last_embed_mentions_the_tickets_channel():
    last = _rendered([build_privacy_embeds(GUILD_ID)[-1]])
    assert f"<#{OTHER_TICKET_CHANNEL_ID}>" in last
    assert "select Server Support" in last


def test_tickets_mention_is_only_in_the_last_embed():
    embeds = build_privacy_embeds(GUILD_ID)
    for embed in embeds[:-1]:
        assert f"<#{OTHER_TICKET_CHANNEL_ID}>" not in _rendered([embed])


def test_dev_mode_does_not_link_the_production_tickets_channel():
    # The suite runs under BOT_MODE=TEST, so the dev ticket channel is expected.
    assert str(PROD_TICKETS_CHANNEL_ID) not in _rendered(build_privacy_embeds(GUILD_ID))


def test_prod_mode_mentions_the_production_tickets_channel():
    import features.config
    import features.privacy_policy

    os.environ["BOT_MODE"] = "PROD"
    try:
        importlib.reload(features.config)
        prod = importlib.reload(features.privacy_policy)
        rendered = _rendered(prod.build_privacy_embeds(PROD_GUILD_ID))
        assert f"<#{PROD_TICKETS_CHANNEL_ID}>" in rendered
    finally:
        os.environ["BOT_MODE"] = "TEST"
        importlib.reload(features.config)
        importlib.reload(features.privacy_policy)


def test_policy_site_is_the_only_external_link():
    urls = re.findall(r"https?://[^\s)]+", _rendered(build_privacy_embeds(GUILD_ID)))
    assert POLICY_URL in urls, "the web link should be present"
    for url in urls:
        assert url == POLICY_URL, f"unexpected external link: {url}"


def test_web_link_is_at_the_foot_of_the_last_embed():
    embeds = build_privacy_embeds(GUILD_ID)
    assert POLICY_URL not in _rendered(embeds[:-1])
    assert embeds[-1].description.rstrip().endswith(f"({POLICY_URL})")


def test_contact_line_has_no_broken_link_without_a_guild():
    rendered = _rendered(build_privacy_embeds(None))
    assert "discord.com/channels" not in rendered
    assert "Server Support" in rendered


def test_policy_text_lives_only_in_the_content_module():
    # A sentence from the middle of the policy. If it turns up in a second
    # feature file, the text has been duplicated instead of imported.
    marker = "All data is stored in our own MongoDB Atlas database"
    hits = [
        path
        for path in (REPO_ROOT / "features").rglob("*.py")
        if marker in path.read_text(encoding="utf-8")
    ]
    assert [path.name for path in hits] == ["privacy_policy.py"]


# --- repo document ---


def test_privacy_policy_document_exists_at_repo_root():
    assert (REPO_ROOT / "PRIVACY_POLICY.md").is_file()


def test_privacy_policy_document_covers_every_section():
    text = (REPO_ROOT / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
    for heading in POLICY_HEADINGS:
        assert f"## {heading}" in text


def test_privacy_policy_document_carries_the_last_updated_date():
    text = (REPO_ROOT / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
    assert f"Last updated: {LAST_UPDATED}" in text


def test_privacy_policy_document_has_no_external_links():
    text = (REPO_ROOT / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
    assert re.findall(r"https?://\S+", text) == []


def test_readme_links_the_privacy_policy_document():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "./PRIVACY_POLICY.md" in text


def test_privacy_docs_guide_links_only_the_policy_site():
    text = (REPO_ROOT / "docs" / "PRIVACY_SYSTEM.md").read_text(encoding="utf-8")
    urls = re.findall(r"https?://[^\s>)]+", text)
    for url in urls:
        assert url == POLICY_URL, f"unexpected external link: {url}"


# --- /privacy-policy command ---


async def test_privacy_command_responds_with_the_embed_sequence(
    mock_bot, mock_interaction
):
    mock_interaction.guild_id = GUILD_ID
    cog = PrivacyPolicy(mock_bot)
    await cog.privacy_policy.callback(cog, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert len(kwargs["embeds"]) == len(build_privacy_embeds(GUILD_ID))


async def test_privacy_command_is_ephemeral(mock_bot, mock_interaction):
    mock_interaction.guild_id = GUILD_ID
    cog = PrivacyPolicy(mock_bot)
    await cog.privacy_policy.callback(cog, mock_interaction)

    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_privacy_command_works_for_a_member_with_no_roles(
    mock_bot, mock_interaction
):
    mock_interaction.guild_id = GUILD_ID
    mock_interaction.user.roles = []
    cog = PrivacyPolicy(mock_bot)
    await cog.privacy_policy.callback(cog, mock_interaction)

    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert kwargs["embeds"]


async def test_privacy_command_response_mentions_the_tickets_channel(
    mock_bot, mock_interaction
):
    mock_interaction.guild_id = GUILD_ID
    cog = PrivacyPolicy(mock_bot)
    await cog.privacy_policy.callback(cog, mock_interaction)

    embeds = mock_interaction.response.send_message.call_args.kwargs["embeds"]
    assert f"<#{OTHER_TICKET_CHANNEL_ID}>" in _rendered(embeds)


# --- startup repost ---


async def test_repost_deletes_the_previous_bot_messages_before_posting(
    mock_bot, privacy_channel_configured
):
    order = []
    stale = [_message(mock_bot.user), _message(mock_bot.user)]
    for message in stale:
        message.delete = AsyncMock(side_effect=lambda: order.append("delete"))
    channel = _privacy_channel(stale)
    channel.send = AsyncMock(side_effect=lambda *a, **k: order.append("send"))
    mock_bot.get_channel = MagicMock(return_value=channel)

    await repost_privacy_policy(mock_bot)

    assert order == ["delete", "delete", "send"]


async def test_repost_leaves_messages_from_other_authors_alone(
    mock_bot, privacy_channel_configured
):
    other = _message(MagicMock())
    mine = _message(mock_bot.user)
    channel = _privacy_channel([other, mine])
    mock_bot.get_channel = MagicMock(return_value=channel)

    await repost_privacy_policy(mock_bot)

    other.delete.assert_not_called()
    mine.delete.assert_called_once()


async def test_repost_posts_the_full_embed_sequence(
    mock_bot, privacy_channel_configured
):
    channel = _privacy_channel([])
    mock_bot.get_channel = MagicMock(return_value=channel)

    await repost_privacy_policy(mock_bot)

    channel.send.assert_called_once()
    embeds = channel.send.call_args.kwargs["embeds"]
    assert len(embeds) == len(build_privacy_embeds(GUILD_ID))


async def test_repost_mentions_the_tickets_channel(
    mock_bot, privacy_channel_configured
):
    channel = _privacy_channel([])
    mock_bot.get_channel = MagicMock(return_value=channel)

    await repost_privacy_policy(mock_bot)

    embeds = channel.send.call_args.kwargs["embeds"]
    assert f"<#{OTHER_TICKET_CHANNEL_ID}>" in _rendered(embeds)


async def test_repost_posts_even_when_the_channel_is_empty(
    mock_bot, privacy_channel_configured
):
    channel = _privacy_channel([])
    mock_bot.get_channel = MagicMock(return_value=channel)

    await repost_privacy_policy(mock_bot)

    channel.send.assert_called_once()


async def test_repost_skips_a_missing_channel(mock_bot, privacy_channel_configured):
    mock_bot.get_channel = MagicMock(return_value=None)

    await repost_privacy_policy(mock_bot)  # must not raise


async def test_repost_skips_a_non_text_channel(mock_bot, privacy_channel_configured):
    voice = MagicMock(spec=discord.VoiceChannel)
    mock_bot.get_channel = MagicMock(return_value=voice)

    await repost_privacy_policy(mock_bot)  # must not raise


async def test_repost_survives_a_discord_error(mock_bot, privacy_channel_configured):
    channel = _privacy_channel([])
    channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "boom"))
    mock_bot.get_channel = MagicMock(return_value=channel)

    await repost_privacy_policy(mock_bot)  # startup must not be blocked


async def test_repost_skips_when_the_channel_id_is_unset(mock_bot, monkeypatch):
    import features.privacy_policy as module

    monkeypatch.setattr(module, "PRIVACY_CHANNEL_ID", 0)
    mock_bot.get_channel = MagicMock()

    await repost_privacy_policy(mock_bot)

    mock_bot.get_channel.assert_not_called()


def test_privacy_channel_id_is_set_in_both_config_branches():
    """Every ID lives twice — once for the real server, once for the test one."""
    source = (REPO_ROOT / "features" / "config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    def assigned_names(body):
        names = set()
        for stmt in body:
            if isinstance(stmt, ast.Assign):
                names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        return names

    split = next(
        node
        for node in tree.body
        if isinstance(node, ast.If) and len(assigned_names(node.body)) > 3
    )
    assert "PRIVACY_CHANNEL_ID" in assigned_names(split.body)
    assert "PRIVACY_CHANNEL_ID" in assigned_names(split.orelse)
