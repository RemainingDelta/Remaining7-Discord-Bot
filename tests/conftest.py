import os
import pytest
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

# Ensure no real connections are attempted during tests
os.environ.setdefault("BOT_MODE", "TEST")
os.environ.setdefault("MONGO_URI", "")
os.environ.setdefault("DISCORD_TOKEN", "")
os.environ.setdefault("FAKE_TOKEN", "")


@pytest.fixture
def mock_bot():
    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock()
    bot.user.id = 123456789
    return bot


@pytest.fixture
def mock_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 987654321
    interaction.user.display_name = "TestUser"
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 111111111
    return interaction


@pytest.fixture
def mock_collection():
    col = AsyncMock()
    col.find_one = AsyncMock(return_value=None)
    col.update_one = AsyncMock()
    col.insert_one = AsyncMock()
    col.find = MagicMock(return_value=AsyncMock())
    return col


@pytest.fixture
def mock_dm_message():
    """A message sent to the bot in a DM.

    `channel` is spec'd to discord.DMChannel so `.category` raises
    AttributeError exactly as it does in production (#517). A specless
    MagicMock auto-creates a truthy `.category`, which is why the DM crash
    was invisible to the suite.
    """
    message = MagicMock(spec=discord.Message)
    message.author = MagicMock(spec=discord.User)
    message.author.bot = False
    message.author.id = 987654321
    message.content = "hello"
    message.guild = None
    message.channel = MagicMock(spec=discord.DMChannel)
    message.channel.id = 555555555
    return message


@pytest.fixture
def guild_message():
    """Factory for a member's message in a guild text channel.

    `category_id=None` puts the channel outside any category. Paired with
    `mock_dm_message` so both sides of the guild/DM boundary come from one
    place.
    """

    def _make(channel_id, category_id=None):
        message = MagicMock(spec=discord.Message)
        message.author = MagicMock(spec=discord.Member)
        message.author.bot = False
        message.author.id = 987654321
        message.content = "hello"
        message.guild = MagicMock(spec=discord.Guild)
        message.guild.get_role = MagicMock(return_value=None)
        message.channel = MagicMock(spec=discord.TextChannel)
        message.channel.id = channel_id
        message.channel.send = AsyncMock()
        if category_id is None:
            message.channel.category = None
        else:
            message.channel.category = MagicMock(spec=discord.CategoryChannel)
            message.channel.category.id = category_id
        return message

    return _make
