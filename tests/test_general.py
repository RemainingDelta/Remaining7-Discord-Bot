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
