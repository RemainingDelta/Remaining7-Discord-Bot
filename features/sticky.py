import asyncio
import io

import discord
from discord.ext import commands

from database.mongo import (
    delete_sticky,
    get_sticky,
    set_sticky,
    update_sticky_message_id,
)
from features.config import EVENT_STAFF_ROLE_ID


DEBOUNCE_SECONDS = 1.5


class StickyMessages(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._pending: dict[int, asyncio.Task] = {}

    def _has_permission(self, member: discord.Member) -> bool:
        return bool(
            member.guild_permissions.administrator
            or member.get_role(EVENT_STAFF_ROLE_ID)
        )

    async def _post_sticky(
        self, channel: discord.TextChannel, sticky_doc: dict
    ) -> discord.Message:
        content = sticky_doc.get("content") or ""
        attachments = sticky_doc.get("attachments", [])
        files = [
            discord.File(io.BytesIO(bytes(a["data"])), filename=a["filename"])
            for a in attachments
        ]
        return await channel.send(content=content or None, files=files)

    async def _delete_bot_message(self, channel: discord.TextChannel, message_id: int):
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    @commands.command(name="sticky")
    async def sticky(self, ctx: commands.Context):
        if not self._has_permission(ctx.author):
            await ctx.send(
                "❌ You need Administrator or Event Staff permissions to use this command.",
                delete_after=5,
            )
            return

        if ctx.message.reference is None:
            await ctx.send(
                "❌ Please reply to a message to make it sticky.", delete_after=5
            )
            return

        try:
            ref_message = await ctx.channel.fetch_message(
                ctx.message.reference.message_id
            )
        except discord.NotFound:
            await ctx.send("❌ Could not find the referenced message.", delete_after=5)
            return

        content = ref_message.content or ""
        attachments = []
        for attachment in ref_message.attachments:
            data = await attachment.read()
            attachments.append({"filename": attachment.filename, "data": data})

        if not content and not attachments:
            await ctx.send(
                "❌ The referenced message has no content or attachments.",
                delete_after=5,
            )
            return

        # Remove any existing sticky bot message
        existing = await get_sticky(ctx.channel.id)
        if existing and existing.get("bot_message_id"):
            await self._delete_bot_message(ctx.channel, existing["bot_message_id"])

        sticky_msg = await self._post_sticky(
            ctx.channel,
            {"content": content, "attachments": attachments},
        )
        await set_sticky(ctx.channel.id, content, attachments, sticky_msg.id)

        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

    @commands.command(name="unsticky")
    async def unsticky(self, ctx: commands.Context):
        if not self._has_permission(ctx.author):
            await ctx.send(
                "❌ You need Administrator or Event Staff permissions to use this command.",
                delete_after=5,
            )
            return

        existing = await get_sticky(ctx.channel.id)
        if not existing:
            await ctx.send(
                "❌ There is no sticky message in this channel.", delete_after=5
            )
            return

        if existing.get("bot_message_id"):
            await self._delete_bot_message(ctx.channel, existing["bot_message_id"])

        await delete_sticky(ctx.channel.id)
        pending = self._pending.pop(ctx.channel.id, None)
        if pending:
            pending.cancel()

        await ctx.send("✅ Sticky message removed.")

    async def _repost_sticky(self, channel: discord.TextChannel):
        await asyncio.sleep(DEBOUNCE_SECONDS)
        self._pending.pop(channel.id, None)

        sticky_doc = await get_sticky(channel.id)
        if not sticky_doc:
            return

        if sticky_doc.get("bot_message_id"):
            await self._delete_bot_message(channel, sticky_doc["bot_message_id"])

        new_msg = await self._post_sticky(channel, sticky_doc)
        await update_sticky_message_id(channel.id, new_msg.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        sticky_doc = await get_sticky(message.channel.id)
        if not sticky_doc:
            return

        pending = self._pending.pop(message.channel.id, None)
        if pending:
            pending.cancel()

        self._pending[message.channel.id] = asyncio.create_task(
            self._repost_sticky(message.channel)
        )


async def setup(bot):
    await bot.add_cog(StickyMessages(bot))
