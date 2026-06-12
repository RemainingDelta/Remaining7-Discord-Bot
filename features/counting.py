import discord
from discord import app_commands
from discord.ext import commands

from database.mongo import get_counting_state, update_counting_state
from features.config import (
    ADMIN_ROLE_ID,
    COUNTING_CHANNEL_ID,
    FOUNDER_ROLE_ID,
    MODERATOR_ROLE_ID,
)

COUNTING_MOD_ROLES = {MODERATOR_ROLE_ID, ADMIN_ROLE_ID, FOUNDER_ROLE_ID}


class Counting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.id != COUNTING_CHANNEL_ID:
            return

        state = await get_counting_state()
        current_count = state["current_count"]
        last_user_id = state["last_user_id"]
        expected = current_count + 1

        if message.author.id == last_user_id:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} You can't count twice in a row!",
                delete_after=5,
            )
            return

        try:
            number = int(message.content.strip())
        except ValueError:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} That's not a number! Next number is **{expected}**.",
                delete_after=5,
            )
            return

        if number != expected:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} Wrong number! Next number is **{expected}**.",
                delete_after=5,
            )
            return

        await update_counting_state(number, message.author.id)

    @app_commands.command(
        name="set-count", description="Set the current count (staff only)."
    )
    @app_commands.describe(count="The number to set the count to")
    async def set_count(self, interaction: discord.Interaction, count: int):
        if not isinstance(interaction.user, discord.Member) or not any(
            role.id in COUNTING_MOD_ROLES for role in interaction.user.roles
        ):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return

        if interaction.channel_id != COUNTING_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{COUNTING_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await update_counting_state(count, None)
        await interaction.response.send_message(
            f"✅ Count set to **{count}**.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Counting(bot))
