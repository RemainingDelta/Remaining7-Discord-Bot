import re

import discord
from discord.ext import commands

from features.config import MODERATOR_ROLE_ID


# Matches a full Discord message link: guild_id / channel_id / message_id
MESSAGE_LINK_PATTERN = re.compile(
    r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com"
    r"/channels/(\d+)/(\d+)/(\d+)"
)

USER_MENTION_PATTERN = re.compile(r"<@!?\d+>")
ROLE_MENTION_PATTERN = re.compile(r"<@&\d+>")

WEBHOOK_NAME = "R7 Message Mirror"
MAX_MESSAGE_LENGTH = 2000


def _parse_message_link(content: str) -> tuple[int, int, int] | None:
    """Returns (guild_id, channel_id, message_id) if the content is exactly
    one Discord message link, else None.

    Requiring the message to be only a link (not a link inside a sentence)
    keeps the listener from deleting conversational messages.
    """
    match = MESSAGE_LINK_PATTERN.fullmatch(content.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _strip_mentions(text: str) -> str:
    """Removes user and role mention tokens so the mirror can't ping anyone."""
    text = USER_MENTION_PATTERN.sub("", text)
    text = ROLE_MENTION_PATTERN.sub("", text)
    # Clean up spaces left behind by removed tokens; leading indentation
    # (e.g. inside code blocks) is preserved
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r" +\n", "\n", text)
    return text.strip()


class MessageMirror(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _fetch_linked_message(
        self, channel_id: int, message_id: int
    ) -> discord.Message | None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.HTTPException, AttributeError):
            return None

    def _build_mirror_content(self, source: discord.Message) -> str:
        content = _strip_mentions(source.content or "")
        attachment_urls = [a.url for a in source.attachments]
        if attachment_urls:
            urls = "\n".join(attachment_urls)
            content = f"{content}\n{urls}" if content else urls
        return content[:MAX_MESSAGE_LENGTH]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        link = _parse_message_link(message.content)
        if link is None:
            return
        _, channel_id, message_id = link

        if message.author.get_role(MODERATOR_ROLE_ID) is None:
            return

        # Threads and voice channels can't own webhooks
        if not hasattr(message.channel, "create_webhook"):
            return

        source = await self._fetch_linked_message(channel_id, message_id)
        if source is None:
            return

        content = self._build_mirror_content(source)
        if not content:
            return

        try:
            webhook = await message.channel.create_webhook(name=WEBHOOK_NAME)
        except discord.HTTPException:
            return

        try:
            await webhook.send(
                content=content,
                username=source.author.display_name,
                avatar_url=source.author.display_avatar.url,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass
        finally:
            try:
                await webhook.delete()
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(MessageMirror(bot))
