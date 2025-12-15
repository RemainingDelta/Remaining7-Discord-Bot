import discord

class TourneyReportModal(discord.ui.Modal, title="Tourney Support"):
    def __init__(self):
        super().__init__()

        self.team_name = discord.ui.TextInput(
            label="Matcherino Team Name",
            placeholder="Ex. XYZ",
            required=True,
            max_length=100,
        )
        self.bracket = discord.ui.TextInput(
            label="Match No.",
            placeholder="Ex. 3, 23, 145",
            required=True,
            max_length=50,
        )
        self.issue = discord.ui.TextInput(
            label="Issue / Report",
            placeholder="Describe the issue you are trying to report…",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )

        # add the inputs to the modal
        self.add_item(self.team_name)
        self.add_item(self.bracket)
        self.add_item(self.issue)

    async def on_submit(self, interaction: discord.Interaction):
        # we’ll implement this helper in tourney_utils
        from .tourney_utils import create_tourney_ticket_channel

        await create_tourney_ticket_channel(
            interaction,
            team_name=self.team_name.value,
            bracket=self.bracket.value,
            issue=self.issue.value,
        )


class TourneyOpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Tourney Ticket ⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="tourney_open_ticket",
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        modal = TourneyReportModal()
        await interaction.response.send_modal(modal)
        

class PreTourneyReportModal(discord.ui.Modal, title="Pre-Tourney Support"):
    def __init__(self):
        super().__init__()

        self.team_name = discord.ui.TextInput(
            label="Team Name (Optional)",
            placeholder="Ex. XYZ",
            required=False, # <--- NOT REQUIRED
            max_length=100,
        )
        self.issue = discord.ui.TextInput(
            label="Issue / Question",
            placeholder="How can we help?",
            style=discord.TextStyle.paragraph,
            required=True, # <--- REQUIRED
            max_length=1000,
        )

        self.add_item(self.team_name)
        self.add_item(self.issue)

    async def on_submit(self, interaction: discord.Interaction):
        from .tourney_utils import create_pre_tourney_ticket_channel

        await create_pre_tourney_ticket_channel(
            interaction,
            team_name=self.team_name.value,
            issue=self.issue.value,
        )


class PreTourneyOpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Contact Support 📩",
        style=discord.ButtonStyle.primary,
        custom_id="pretourney_open_ticket",
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        modal = PreTourneyReportModal()
        await interaction.response.send_modal(modal)


class DeleteTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Delete Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="tourney_delete_ticket",
    )
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        from .tourney_utils import delete_tourney_ticket
        await delete_tourney_ticket(interaction)
        
    @discord.ui.button(
        label="Reopen Ticket",
        style=discord.ButtonStyle.success,
        custom_id="tourney_reopen_ticket",
    )
    async def reopen_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        from .tourney_utils import reopen_tourney_ticket
        await reopen_tourney_ticket(interaction)

