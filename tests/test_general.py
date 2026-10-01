"""
Sample tests for the General cog.
These serve as a template — follow this pattern when adding tests for other cogs.
"""

from features.general import General


async def test_help_command_sends_embed(mock_bot, mock_interaction):
    """Help command should respond with a single embed."""
    cog = General(mock_bot)
    await cog.help_command.callback(cog, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert "embed" in kwargs


async def test_help_embed_has_title(mock_bot, mock_interaction):
    """Help embed title should mention the bot version."""
    cog = General(mock_bot)
    await cog.help_command.callback(cog, mock_interaction)

    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    assert "R7 Bot" in embed.title


async def test_help_counting_field_matches_behavior(mock_bot, mock_interaction):
    """The counting help must reflect real behavior: math expressions are
    accepted, and a wrong number is deleted rather than resetting the count
    (regression guard for the #325-class 'wrong number resets the count' error).
    """
    cog = General(mock_bot)
    await cog.help_command.callback(cog, mock_interaction)

    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    counting = next(f.value for f in embed.fields if "Counting" in f.name)
    assert "reset" not in counting.lower()
    assert "7*10" in counting


# --- v1.15.0 help audit (#582) ---

import re  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from features.config import ADMIN_ROLE_ID  # noqa: E402

PREFIX_COMMAND = re.compile(r"(?<![\w`])!\w|`!\w")


def _as_admin(interaction):
    role = MagicMock()
    role.id = ADMIN_ROLE_ID
    interaction.user.roles = [role]
    return interaction


def _embed_text(interaction):
    embed = interaction.response.send_message.call_args.kwargs["embed"]
    parts = [embed.title or "", embed.description or ""]
    for field in embed.fields:
        parts += [field.name, field.value]
    return "\n".join(parts)


async def test_admin_help_lists_github_issue_menu(mock_bot, mock_interaction):
    cog = General(mock_bot)
    await cog.admin_help.callback(cog, _as_admin(mock_interaction))

    text = _embed_text(mock_interaction)
    assert "**GitHub Issue**" in text
    assert "edit" in text.lower()


async def test_admin_help_lists_support_panel(mock_bot, mock_interaction):
    cog = General(mock_bot)
    await cog.admin_help.callback(cog, _as_admin(mock_interaction))

    assert "/support-panel" in _embed_text(mock_interaction)


async def test_no_help_embed_mentions_a_prefix_command(mock_bot, mock_interaction):
    """#563 removed every ! command, so none of the help embeds may name one."""
    cog = General(mock_bot)
    for command in (cog.help_command, cog.mod_help, cog.admin_help):
        mock_interaction.response.send_message.reset_mock()
        await command.callback(cog, _as_admin(mock_interaction))
        text = _embed_text(mock_interaction)
        assert not PREFIX_COMMAND.search(text), (
            f"{command.name}: {PREFIX_COMMAND.search(text)}"
        )
