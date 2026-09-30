import asyncio
import io

import discord
from discord import app_commands
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
        # Context menus can't be declared as cog methods, so the "Set Sticky"
        # message command is built here and registered on the tree in cog_load.
        self.set_sticky_menu = app_commands.ContextMenu(
            name="Set Sticky", callback=self.set_sticky_message
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.set_sticky_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.set_sticky_menu.name, type=self.set_sticky_menu.type
        )

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

    async def set_sticky_message(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        if not self._has_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You need Administrator or Event Staff permissions to use this command.",
                ephemeral=True,
            )
            return

        # Reading attachments can outlast the 3-second response window.
        await interaction.response.defer(ephemeral=True)

        content = message.content or ""
        attachments = []
        for attachment in message.attachments:
            data = await attachment.read()
            attachments.append({"filename": attachment.filename, "data": data})

        if not content and not attachments:
            await interaction.followup.send(
                "❌ That message has no content or attachments.", ephemeral=True
            )
            return

        channel = interaction.channel

        # Remove any existing sticky bot message
        existing = await get_sticky(channel.id)
        if existing and existing.get("bot_message_id"):
            await self._delete_bot_message(channel, existing["bot_message_id"])

        sticky_msg = await self._post_sticky(
            channel,
            {"content": content, "attachments": attachments},
        )
        await set_sticky(channel.id, content, attachments, sticky_msg.id)

        await interaction.followup.send("✅ Sticky message set.", ephemeral=True)

    @app_commands.command(
        name="unsticky", description="Remove the sticky message from this channel."
    )
    async def unsticky(self, interaction: discord.Interaction):
        if not self._has_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You need Administrator or Event Staff permissions to use this command.",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        existing = await get_sticky(channel.id)
        if not existing:
            await interaction.response.send_message(
                "❌ There is no sticky message in this channel.", ephemeral=True
            )
            return

        if existing.get("bot_message_id"):
            await self._delete_bot_message(channel, existing["bot_message_id"])

        await delete_sticky(channel.id)
        pending = self._pending.pop(channel.id, None)
        if pending:
            pending.cancel()

        await interaction.response.send_message(
            "✅ Sticky message removed.", ephemeral=True
        )

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
