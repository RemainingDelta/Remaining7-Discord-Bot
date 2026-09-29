"""Tests for features/interaction_context.py (#567).

The tourney start/end flows were written against commands.Context. The adapter
lets a slash command drive them unchanged: gate replies stay private to the
invoker, progress posts go to the channel as they always did, and a long run
never depends on the 15-minute interaction token.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from features.interaction_context import InteractionContext


@pytest.fixture
def interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.send = AsyncMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.client = MagicMock()
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    return interaction


def test_exposes_the_context_attributes_the_flows_read(interaction):
    ctx = InteractionContext(interaction)

    assert ctx.author is interaction.user
    assert ctx.channel is interaction.channel
    assert ctx.guild is interaction.guild
    assert ctx.bot is interaction.client


async def test_start_defers_privately(interaction):
    await InteractionContext(interaction).start()

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)


async def test_first_reply_is_private_to_the_invoker(interaction):
    ctx = InteractionContext(interaction)
    await ctx.start()

    await ctx.reply("You don't have permission.")

    interaction.followup.send.assert_awaited_once_with(
        "You don't have permission.", ephemeral=True
    )
    interaction.channel.send.assert_not_awaited()


async def test_later_replies_go_to_the_channel(interaction):
    ctx = InteractionContext(interaction)
    await ctx.start()
    await ctx.reply("first")

    await ctx.reply("second")

    interaction.followup.send.assert_awaited_once()
    interaction.channel.send.assert_awaited_once_with("second")


async def test_send_posts_to_the_channel(interaction):
    ctx = InteractionContext(interaction)
    await ctx.start()
    embed = discord.Embed(title="stats")

    await ctx.send(embed=embed)

    interaction.channel.send.assert_awaited_once_with(embed=embed)
    interaction.followup.send.assert_not_awaited()


async def test_finish_resolves_the_thinking_state_when_nothing_replied(interaction):
    ctx = InteractionContext(interaction)
    await ctx.start()

    await ctx.finish("✅ Done.")

    interaction.followup.send.assert_awaited_once_with("✅ Done.", ephemeral=True)


async def test_finish_is_silent_after_a_reply_already_answered(interaction):
    ctx = InteractionContext(interaction)
    await ctx.start()
    await ctx.reply("⚠️ A tourney session is already active.")

    await ctx.finish("✅ Done.")

    interaction.followup.send.assert_awaited_once()


async def test_finish_survives_an_expired_interaction_token(interaction):
    """A long start or end can outlive the 15-minute followup window."""
    ctx = InteractionContext(interaction)
    await ctx.start()
    interaction.followup.send.side_effect = discord.NotFound(
        MagicMock(status=404), "Unknown Webhook"
    )

    await ctx.finish("✅ Done.")  # must not raise
