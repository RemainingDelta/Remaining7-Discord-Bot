import re

import discord
from discord.ext import commands


class GitHubTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not re.search(rf"<@!?{self.bot.user.id}>", message.content):
            return

        raw_text = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()

        if not raw_text:
            await message.reply(
                "@ me with a description of your bug, enhancement, or feature"
                " and I'll create a GitHub issue."
            )
            return

        # TODO: Pass raw_text to Gemini integration
        await message.reply(f"Received: {raw_text}")


async def setup(bot):
    await bot.add_cog(GitHubTickets(bot))
