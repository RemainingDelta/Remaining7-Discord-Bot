import discord
from database.mongo import (
    get_active_tourney_session,
    update_tourney_queue,
)
from features.tourney.matcherino import fetch_ticket_context, find_match_by_team_name


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
        from .tourney_utils import create_tourney_ticket_channel
        from database.mongo import get_matcherino_id_from_active  # Add this import

        new_channel = await create_tourney_ticket_channel(
            interaction,
            team_name=self.team_name.value,
            bracket=self.bracket.value,
            issue=self.issue.value,
        )

        try:
            active_session = await get_active_tourney_session()
            if active_session:
                await update_tourney_queue(active_session["_id"], change=1)
        except Exception:
            pass

        if new_channel and interaction.guild_id:
            # Pull the ID from the database instead of memory
            m_id = await get_matcherino_id_from_active()

            if m_id:
                bracket_url = f"https://matcherino.com/supercell/tournaments/{m_id}/bracket/bracket"

                try:
                    match_num = int(self.bracket.value.strip())
                    topic_team = (self.team_name.value or "").strip()
                    match_data = fetch_ticket_context(
                        bracket_url, match_num, topic_team_name=topic_team or None
                    )

                    # Build the Embed (same title as refresher so it gets updated in place, not duplicated)
                    is_mismatch = match_data.get("team_name_mismatch", False)
                    best_match_team = match_data.get("team_name_best_match")
                    now_ts = int(discord.utils.utcnow().timestamp())
                    embed = discord.Embed(
                        title=f"📊 Live Match Update: Match #{match_num}",
                        description=f"**Last Update:** <t:{now_ts}:R>",
                        color=discord.Color.red()
                        if is_mismatch
                        else discord.Color.gold(),
                    )

                    if match_data.get("status") == "success":
                        embed.add_field(
                            name="Match Status",
                            value=f"`{match_data['match_status'].upper()}`",
                            inline=True,
                        )
                        embed.add_field(name="\u200b", value="\u200b", inline=True)
                        embed.add_field(name="\u200b", value="\u200b", inline=True)

                        team_a = match_data["team_a"]
                        team_b = match_data["team_b"]

                        players_a = (
                            "\n".join([f"• {p}" for p in team_a["players"]])
                            or "• *No players found*"
                        )
                        players_b = (
                            "\n".join([f"• {p}" for p in team_b["players"]])
                            or "• *No players found*"
                        )

                        embed.add_field(
                            name=f"🔵 {team_a['name']} ({team_a['score']})",
                            value=f"**Roster:**\n{players_a}",
                            inline=True,
                        )
                        embed.add_field(name="⚔️", value="\u200b", inline=True)
                        embed.add_field(
                            name=f"🔴 {team_b['name']} ({team_b['score']})",
                            value=f"**Roster:**\n{players_b}",
                            inline=True,
                        )

                        if is_mismatch and topic_team:
                            # Team doesn't match this match — try to find their real match
                            lookup = find_match_by_team_name(bracket_url, topic_team)
                            if lookup.get("status") == "found":
                                resolved_num = lookup["match_number"]
                                match_data = fetch_ticket_context(
                                    bracket_url,
                                    resolved_num,
                                    topic_team_name=topic_team,
                                )
                                match_num = resolved_num

                                # Rebuild embed with corrected match
                                now_ts = int(discord.utils.utcnow().timestamp())
                                is_mismatch = match_data.get(
                                    "team_name_mismatch", False
                                )
                                best_match_team = match_data.get("team_name_best_match")
                                embed = discord.Embed(
                                    title=f"📊 Live Match Update: Match #{resolved_num}",
                                    description=(
                                        f"**Last Update:** <t:{now_ts}:R>\n"
                                        f"*Match auto-corrected from #{int(self.bracket.value.strip())} "
                                        f"→ #{resolved_num} via team name "
                                        f"({lookup['ratio']:.0%} match to "
                                        f"`{lookup['matched_team']}`)*"
                                    ),
                                    color=discord.Color.red()
                                    if is_mismatch
                                    else discord.Color.gold(),
                                )

                                if match_data.get("status") == "success":
                                    embed.add_field(
                                        name="Match Status",
                                        value=f"`{match_data['match_status'].upper()}`",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name="\u200b",
                                        value="\u200b",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name="\u200b",
                                        value="\u200b",
                                        inline=True,
                                    )

                                    team_a = match_data["team_a"]
                                    team_b = match_data["team_b"]
                                    players_a = (
                                        "\n".join([f"• {p}" for p in team_a["players"]])
                                        or "• *No players found*"
                                    )
                                    players_b = (
                                        "\n".join([f"• {p}" for p in team_b["players"]])
                                        or "• *No players found*"
                                    )

                                    embed.add_field(
                                        name=f"🔵 {team_a['name']} ({team_a['score']})",
                                        value=f"**Roster:**\n{players_a}",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name="⚔️",
                                        value="\u200b",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name=f"🔴 {team_b['name']} ({team_b['score']})",
                                        value=f"**Roster:**\n{players_b}",
                                        inline=True,
                                    )

                                    if topic_team and best_match_team:
                                        embed.add_field(
                                            name="Detected Team",
                                            value=f"```\n{best_match_team}\n```",
                                            inline=False,
                                        )
                                else:
                                    embed.color = discord.Color.red()
                                    embed.description = f"⚠️ **Could not fetch match data:** {match_data.get('error')}"

                                # Update topic with corrected match number
                                if (
                                    isinstance(new_channel, discord.TextChannel)
                                    and new_channel.topic
                                ):
                                    import re as _re

                                    updated_topic = _re.sub(
                                        r"bracket:[^|]*",
                                        f"bracket:{resolved_num}",
                                        new_channel.topic,
                                    )
                                    try:
                                        await new_channel.edit(topic=updated_topic)
                                    except Exception:
                                        pass
                            else:
                                # Fallback lookup failed — show original mismatch warning
                                warning_text = "The team name for this ticket does not closely match either team in the bracket for this match."
                                if topic_team:
                                    warning_text += f"\nTeam entered: `{topic_team}`"
                                warning_text += (
                                    "\nStaff can correct with `/set-ticket-match`."
                                )
                                embed.add_field(
                                    name="⚠️ Team name / Match number Mismatch",
                                    value=warning_text,
                                    inline=False,
                                )

                        elif is_mismatch:
                            # Mismatch but no team name to look up
                            warning_text = "The team name for this ticket does not closely match either team in the bracket for this match."
                            warning_text += (
                                "\nStaff can correct with `/set-ticket-match`."
                            )
                            embed.add_field(
                                name="⚠️ Team name / Match number Mismatch",
                                value=warning_text,
                                inline=False,
                            )

                        elif topic_team and best_match_team:
                            embed.add_field(
                                name="Detected Team",
                                value=f"```\n{best_match_team}\n```",
                                inline=False,
                            )

                    else:
                        # Match number not found in bracket — try team name fallback
                        fallback_resolved = False
                        if topic_team:
                            lookup = find_match_by_team_name(bracket_url, topic_team)
                            if lookup.get("status") == "found":
                                resolved_num = lookup["match_number"]
                                match_data = fetch_ticket_context(
                                    bracket_url,
                                    resolved_num,
                                    topic_team_name=topic_team,
                                )
                                if match_data.get("status") == "success":
                                    fallback_resolved = True
                                    match_num = resolved_num
                                    is_mismatch = match_data.get(
                                        "team_name_mismatch", False
                                    )
                                    best_match_team = match_data.get(
                                        "team_name_best_match"
                                    )
                                    now_ts = int(discord.utils.utcnow().timestamp())
                                    embed = discord.Embed(
                                        title=f"📊 Live Match Update: Match #{resolved_num}",
                                        description=(
                                            f"**Last Update:** <t:{now_ts}:R>\n"
                                            f"*Match #{int(self.bracket.value.strip())} not found — "
                                            f"auto-corrected to #{resolved_num} via team name "
                                            f"({lookup['ratio']:.0%} match to "
                                            f"`{lookup['matched_team']}`)*"
                                        ),
                                        color=discord.Color.red()
                                        if is_mismatch
                                        else discord.Color.gold(),
                                    )
                                    embed.add_field(
                                        name="Match Status",
                                        value=f"`{match_data['match_status'].upper()}`",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name="\u200b",
                                        value="\u200b",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name="\u200b",
                                        value="\u200b",
                                        inline=True,
                                    )

                                    team_a = match_data["team_a"]
                                    team_b = match_data["team_b"]
                                    players_a = (
                                        "\n".join([f"• {p}" for p in team_a["players"]])
                                        or "• *No players found*"
                                    )
                                    players_b = (
                                        "\n".join([f"• {p}" for p in team_b["players"]])
                                        or "• *No players found*"
                                    )
                                    embed.add_field(
                                        name=f"🔵 {team_a['name']} ({team_a['score']})",
                                        value=f"**Roster:**\n{players_a}",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name="⚔️",
                                        value="\u200b",
                                        inline=True,
                                    )
                                    embed.add_field(
                                        name=f"🔴 {team_b['name']} ({team_b['score']})",
                                        value=f"**Roster:**\n{players_b}",
                                        inline=True,
                                    )

                                    if topic_team and best_match_team:
                                        embed.add_field(
                                            name="Detected Team",
                                            value=f"```\n{best_match_team}\n```",
                                            inline=False,
                                        )

                                    # Update topic with corrected match number
                                    if (
                                        isinstance(new_channel, discord.TextChannel)
                                        and new_channel.topic
                                    ):
                                        import re as _re

                                        updated_topic = _re.sub(
                                            r"bracket:[^|]*",
                                            f"bracket:{resolved_num}",
                                            new_channel.topic,
                                        )
                                        try:
                                            await new_channel.edit(topic=updated_topic)
                                        except Exception:
                                            pass

                        if not fallback_resolved:
                            embed.color = discord.Color.red()
                            embed.description = f"⚠️ **Could not fetch match data:** {match_data.get('error')}"

                    embed.set_footer(text=f"Matcherino ID: {m_id}")
                    await new_channel.send(embed=embed)

                except ValueError:
                    # User didn't enter a valid match number — fallback to team name lookup
                    topic_team = (self.team_name.value or "").strip()
                    if topic_team:
                        lookup = find_match_by_team_name(bracket_url, topic_team)

                        if lookup.get("status") == "found":
                            # Resolved a match number from team name — fetch full context
                            resolved_num = lookup["match_number"]
                            match_data = fetch_ticket_context(
                                bracket_url,
                                resolved_num,
                                topic_team_name=topic_team,
                            )

                            now_ts = int(discord.utils.utcnow().timestamp())
                            is_mismatch = match_data.get("team_name_mismatch", False)
                            best_match_team = match_data.get("team_name_best_match")
                            embed = discord.Embed(
                                title=f"📊 Live Match Update: Match #{resolved_num}",
                                description=(
                                    f"**Last Update:** <t:{now_ts}:R>\n"
                                    f"*Match auto-detected from team name "
                                    f"({lookup['ratio']:.0%} match to "
                                    f"`{lookup['matched_team']}`)*"
                                ),
                                color=discord.Color.red()
                                if is_mismatch
                                else discord.Color.gold(),
                            )

                            if match_data.get("status") == "success":
                                embed.add_field(
                                    name="Match Status",
                                    value=f"`{match_data['match_status'].upper()}`",
                                    inline=True,
                                )
                                embed.add_field(
                                    name="\u200b", value="\u200b", inline=True
                                )
                                embed.add_field(
                                    name="\u200b", value="\u200b", inline=True
                                )

                                team_a = match_data["team_a"]
                                team_b = match_data["team_b"]

                                players_a = (
                                    "\n".join([f"• {p}" for p in team_a["players"]])
                                    or "• *No players found*"
                                )
                                players_b = (
                                    "\n".join([f"• {p}" for p in team_b["players"]])
                                    or "• *No players found*"
                                )

                                embed.add_field(
                                    name=f"🔵 {team_a['name']} ({team_a['score']})",
                                    value=f"**Roster:**\n{players_a}",
                                    inline=True,
                                )
                                embed.add_field(name="⚔️", value="\u200b", inline=True)
                                embed.add_field(
                                    name=f"🔴 {team_b['name']} ({team_b['score']})",
                                    value=f"**Roster:**\n{players_b}",
                                    inline=True,
                                )

                                if topic_team and best_match_team:
                                    embed.add_field(
                                        name="Detected Team",
                                        value=f"```\n{best_match_team}\n```",
                                        inline=False,
                                    )
                            else:
                                embed.color = discord.Color.red()
                                embed.description = f"⚠️ **Could not fetch match data:** {match_data.get('error')}"

                            embed.set_footer(text=f"Matcherino ID: {m_id}")

                            # Update topic with resolved match number
                            if (
                                isinstance(new_channel, discord.TextChannel)
                                and new_channel.topic
                            ):
                                import re as _re

                                updated_topic = _re.sub(
                                    r"bracket:[^|]*",
                                    f"bracket:{resolved_num}",
                                    new_channel.topic,
                                )
                                try:
                                    await new_channel.edit(topic=updated_topic)
                                except Exception:
                                    pass

                            await new_channel.send(embed=embed)

                        else:
                            # No match found — flag for staff
                            embed = discord.Embed(
                                title="⚠️ Team Not Found in Bracket",
                                description=(
                                    f"Could not auto-detect a match for team `{topic_team}` "
                                    f"in the Matcherino bracket.\n\n"
                                    f"**Staff:** Please manually identify the team and "
                                    f"use `/set-ticket-match` to set the correct match number."
                                ),
                                color=discord.Color.orange(),
                            )
                            if lookup.get("best_team"):
                                embed.add_field(
                                    name="Closest Match",
                                    value=f"`{lookup['best_team']}` ({lookup.get('best_ratio', 0):.0%} similarity)",
                                    inline=False,
                                )
                            embed.set_footer(text=f"Matcherino ID: {m_id}")
                            await new_channel.send(embed=embed)


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
            required=False,  # <--- NOT REQUIRED
            max_length=100,
        )
        self.issue = discord.ui.TextInput(
            label="Issue / Question",
            placeholder="How can we help?",
            style=discord.TextStyle.paragraph,
            required=True,  # <--- REQUIRED
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

        try:
            active_session = await get_active_tourney_session()
            if active_session:
                await update_tourney_queue(active_session["_id"], change=1)
        except Exception:
            pass


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
