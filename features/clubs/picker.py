"""The "Choose a Club" dropdowns under the club stats message (#619).

Two persistent select menus (Discord allows 25 options each) list every
tracked club by trophies. Picking one replies privately with that club's
details. The view is registered at startup, so the menus keep working after a
restart; its options come from the message itself when a member picks one.
"""

import discord

from database.mongo import get_tracked_club
from features.clubs.board import (
    build_club_detail_embed,
    club_trophies,
    sorted_by_trophies,
)
from features.clubs.snapshots import TrackedClub

OPTIONS_PER_MENU = 25
MENUS = (
    ("club_picker:1", "Choose a Club (1-25)"),
    ("club_picker:2", "Choose a Club (26-50)"),
)


def _option(club: TrackedClub) -> discord.SelectOption:
    suffix = f" | 🏆 {club_trophies(club):,}"
    name = club["name"][: 100 - len(suffix)]  # Discord caps labels at 100
    return discord.SelectOption(label=f"{name}{suffix}", value=club["_id"])


class ClubSelect(discord.ui.Select):
    def __init__(self, custom_id: str, placeholder: str, options: list):
        super().__init__(custom_id=custom_id, placeholder=placeholder, options=options)

    async def callback(self, interaction: discord.Interaction):
        club = await get_tracked_club(self.values[0])
        if club is None:
            await interaction.response.send_message(
                "That club is no longer tracked.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=build_club_detail_embed(club), ephemeral=True
        )


class ClubPicker(discord.ui.View):
    """Both menus, empty. Register this once with `bot.add_view` at startup."""

    def __init__(self):
        super().__init__(timeout=None)
        for custom_id, placeholder in MENUS:
            self.add_item(ClubSelect(custom_id, placeholder, []))

    @classmethod
    def for_clubs(cls, clubs: list[TrackedClub]) -> "ClubPicker | None":
        """The menus to attach to the board, filled by trophies; None with no clubs."""
        ordered = sorted_by_trophies(clubs)
        if not ordered:
            return None
        view = cls()
        for i, select in enumerate(list(view.children)):
            chunk = ordered[i * OPTIONS_PER_MENU : (i + 1) * OPTIONS_PER_MENU]
            if chunk:
                select.options = [_option(club) for club in chunk]
            else:
                view.remove_item(select)  # hide the second menu with 25 or fewer
        return view
