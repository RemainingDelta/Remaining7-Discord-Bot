"""A slash-command stand-in for commands.Context (#567).

Long staff flows such as starting and ending a tourney were written against
``commands.Context``. Rewriting them for an Interaction would mean touching
every ``ctx.send`` in several hundred lines, so this adapter exposes just the
parts they use:

- ``author``, ``channel``, ``guild``, ``bot`` map onto the interaction.
- The first ``reply`` answers the invoker privately. Those replies are the
  gate messages (no permission, wrong channel, already running).
- ``send`` and later replies post in the channel, where the progress messages
  always went. Posting through the channel rather than the interaction
  followup keeps a long run from failing once the 15-minute token expires.
"""

import discord


class InteractionContext:
    def __init__(self, interaction: discord.Interaction):
        self.interaction = interaction
        self.author = interaction.user
        self.channel = interaction.channel
        self.guild = interaction.guild
        self.bot = interaction.client
        self._answered = False

    async def start(self) -> None:
        """Acknowledge within Discord's 3-second window before any slow work."""
        await self.interaction.response.defer(ephemeral=True, thinking=True)

    async def reply(self, content=None, **kwargs):
        if not self._answered:
            self._answered = True
            return await self.interaction.followup.send(content, ephemeral=True)
        return await self.send(content, **kwargs)

    async def send(self, content=None, **kwargs):
        if content is not None:
            return await self.channel.send(content, **kwargs)
        return await self.channel.send(**kwargs)

    async def finish(self, content: str) -> None:
        """Clear the "thinking" state if no gate reply already answered."""
        if self._answered:
            return
        self._answered = True
        try:
            await self.interaction.followup.send(content, ephemeral=True)
        except discord.HTTPException:
            pass  # the token expired during a long run; the channel has the result
