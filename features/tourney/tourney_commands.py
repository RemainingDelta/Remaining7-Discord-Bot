import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import re 
import datetime 
from .matcherino import fetch_ticket_context, fetch_payout_report, fetch_bracket_progress

from database.mongo import (
    add_payout_batch,         
    get_payout_logs,         
    get_user_unpaid_batches, 
    get_all_pending_payouts, 
    clear_pending_payout,
    add_blacklisted_user,
    remove_blacklisted_user,
    get_all_blacklisted_users,
    get_blacklisted_user,
    create_tourney_session,
    get_active_tourney_session,
    end_tourney_session,
    reset_tourney_session_start_time,
    increment_tourney_message_count,
    update_matcherino_id,
    update_tourney_queue,
    increment_staff_closure,
    get_top_staff_stats,
    get_matcherino_id_from_active
)

# Import Config and Utils
from features.config import (
    ALLOWED_STAFF_ROLES,
    OTHER_TICKET_CHANNEL_ID,
    MEMBER_ROLE_ID,
    ADMIN_ROLE_ID,
    GENERAL_CHANNEL_ID,
    BRAWL_CHAT_CHANNEL_ID,
    TOURNEY_CHAT_CHANNEL_ID,
    TOURNEY_UPDATES_CHANNEL_ID,
    TOURNEY_VS_EMOJI,
    TOURNEY_MATCHERINO_WIN_EMOJI,
    TOURNEY_SUPPORT_CHANNEL_ID,
    TOURNEY_ADMIN_CHANNEL_ID,
    PRE_TOURNEY_SUPPORT_CHANNEL_ID,
    TOURNEY_CATEGORY_ID,
    PRE_TOURNEY_CATEGORY_ID,
    TOURNEY_CLOSED_CATEGORY_ID,
    PRE_TOURNEY_CLOSED_CATEGORY_ID,
    HALL_OF_FAME_CHANNEL_ID,
    BOT_VERSION,
    TOURNEY_TEST_MODE
)
from .tourney_utils import (
    close_ticket_via_command,
    reset_ticket_counter,
    delete_ticket_with_transcript,
    delete_ticket_via_command,
    reopen_ticket_via_command
)
from .tourney_views import TourneyOpenTicketView, PreTourneyOpenTicketView

# Global lock tasks dictionary to track auto-reopen timers
lock_tasks: dict[int, asyncio.Task] = {}
LOCK_DURATION_HOURS = 6
TOURNEY_STAGE_HYPE_GIF_URL = "https://cdn.discordapp.com/attachments/807243155698352138/1314223834018222142/4M7IWwP.gif?ex=693ebd53&is=693d6bd3&hm=2a7e2767c8c441f51fad04d147e99b5db2faad7e28a2c799a21356da05ad2294"

def is_staff(member: discord.Member) -> bool:
    """Return True if the member has any of the allowed staff roles."""
    return any(role.id in ALLOWED_STAFF_ROLES for role in member.roles)

class PayoutResetConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.value = None

    @discord.ui.button(label="Confirm Reset All", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()

class QueueDashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dashboard_message_id: int | None = None
        self._progress_dashboard_lock = asyncio.Lock()
        self._announcement_lock = asyncio.Lock()
        self._stage_announcement_state: dict[str, dict[str, str | int | None]] = {
            "semi_finals": {"signature": None, "message_id": None, "hype_message_id": None},
            "finals": {"signature": None, "message_id": None, "hype_message_id": None},
        }
        self._winner_announcement_state: dict[str, str | int | None] = {
            "winner": None,
            "message_id": None,
        }
        self._announcement_matcherino_id: str | None = None
        # The dashboard_task is still manually started via !starttourney
        # The match_refresher starts automatically to monitor any active tickets
        self.match_refresher_task.start()

    def cog_unload(self):
        self.dashboard_task.cancel()
        self.progress_dashboard_task.cancel()
        self.match_refresher_task.cancel()

    async def start_dashboard(self):
        """Starts dashboard loops if not already running."""
        if not self.dashboard_task.is_running():
            self.dashboard_task.start()
            print("📊 Queue Dashboard Started")
        if not self.progress_dashboard_task.is_running():
            self.progress_dashboard_task.start()
            print("📈 Tourney Progress Dashboard Started")

        # Ensure the progress panel appears immediately at tournament start.
        await self.update_progress_dashboard()

    async def stop_dashboard(self):
        """Stops dashboard loops and deletes dashboard messages."""
        if self.dashboard_task.is_running():
            self.dashboard_task.cancel()
            print("📊 Queue Dashboard Stopped")
        if self.progress_dashboard_task.is_running():
            self.progress_dashboard_task.cancel()
            print("📈 Tourney Progress Dashboard Stopped")
        
        channel = self.bot.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if channel and isinstance(channel, discord.TextChannel):
            try:
                async for m in channel.history(limit=10):
                    if m.author == self.bot.user and m.embeds and m.embeds[0].title == "📊 Live Tournament Queue":
                        await m.delete()
                        break
            except Exception as e:
                print(f"Failed to cleanup dashboard message: {e}")

        admin_channel = self.bot.get_channel(TOURNEY_ADMIN_CHANNEL_ID)
        if admin_channel and isinstance(admin_channel, discord.TextChannel):
            try:
                if self.dashboard_message_id:
                    msg = await admin_channel.fetch_message(self.dashboard_message_id)
                    await msg.delete()
                else:
                    async for m in admin_channel.history(limit=20):
                        if m.author == self.bot.user and m.embeds and m.embeds[0].title == "📈 Live Tournament Progress":
                            await m.delete()
                            break
            except Exception as e:
                print(f"Failed to cleanup progress dashboard message: {e}")
            finally:
                self.dashboard_message_id = None

    def _reset_announcement_state_if_needed(self, matcherino_id: str):
        if self._announcement_matcherino_id != matcherino_id:
            self._announcement_matcherino_id = matcherino_id
            for stage_key in self._stage_announcement_state:
                self._stage_announcement_state[stage_key]["signature"] = None
                self._stage_announcement_state[stage_key]["message_id"] = None
                self._stage_announcement_state[stage_key]["hype_message_id"] = None
            self._winner_announcement_state["winner"] = None
            self._winner_announcement_state["message_id"] = None

    @staticmethod
    def _is_known_team(team_name: str | None) -> bool:
        if not team_name:
            return False
        return team_name.strip().upper() not in {"TBD", "BYE", "UNKNOWN", "UNKNOWN TEAM"}

    def _is_fully_matched(self, match: dict) -> bool:
        return self._is_known_team(match.get("team_a")) and self._is_known_team(match.get("team_b"))

    @staticmethod
    def _build_stage_signature(matches: list[dict]) -> str:
        sorted_matches = sorted(
            matches,
            key=lambda m: m.get("id") if isinstance(m.get("id"), int) else 9999,
        )
        return "|".join(
            f"{m.get('id')}::{m.get('team_a', 'TBD')}::{m.get('team_b', 'TBD')}"
            for m in sorted_matches
        )

    async def _delete_previous_stage_messages(self, channel: discord.TextChannel, stage_key: str):
        stage_state = self._stage_announcement_state[stage_key]
        message_ids = [
            stage_state.get("message_id"),
            stage_state.get("hype_message_id"),
        ]

        for msg_id in message_ids:
            if not isinstance(msg_id, int):
                continue
            try:
                old_msg = await channel.fetch_message(msg_id)
                await old_msg.delete()
                print(f"[ANNOUNCE][{stage_key}] deleted previous message {msg_id}")
            except (discord.NotFound, discord.Forbidden):
                pass
            except Exception as e:
                print(f"Stage announcement cleanup error ({stage_key}): {e}")

        stage_state["message_id"] = None
        stage_state["hype_message_id"] = None
        stage_state["signature"] = None

    async def _sync_stage_announcement(
        self,
        channel: discord.TextChannel,
        stage_key: str,
        stage_title: str,
        matches: list[dict],
        required_count: int,
    ):
        stage_state = self._stage_announcement_state[stage_key]

        # Guard: only announce once the entire stage matchup is known.
        if len(matches) != required_count:
            print(
                f"[ANNOUNCE][{stage_key}] skip stage post: matched_count={len(matches)} required={required_count}"
            )
            await self._delete_previous_stage_messages(channel, stage_key)
            return

        signature = self._build_stage_signature(matches)
        current_signature = stage_state.get("signature")
        current_message_id = stage_state.get("message_id")

        if signature == current_signature and isinstance(current_message_id, int):
            print(f"[ANNOUNCE][{stage_key}] skip stage post: unchanged signature")
            return

        await self._delete_previous_stage_messages(channel, stage_key)

        sorted_matches = sorted(matches, key=lambda m: m.get("id") if isinstance(m.get("id"), int) else 9999)

        match_lines = []
        for m in sorted_matches:
            team_a = m.get("team_a", "TBD")
            team_b = m.get("team_b", "TBD")
            match_lines.append(f"{team_a}  {TOURNEY_VS_EMOJI}  {team_b}")

        content = f"# {stage_title}\n" + "\n".join(match_lines)

        # Cross-check recent messages so duplicated scheduler invocations don't post twice.
        async for recent in channel.history(limit=8):
            if recent.author == self.bot.user and recent.content == content:
                stage_state["message_id"] = recent.id
                stage_state["signature"] = signature
                stage_state["hype_message_id"] = None
                print(f"[ANNOUNCE][{stage_key}] skip stage post: identical content already exists ({recent.id})")
                return

        new_message = await channel.send(content)
        hype_message = await channel.send(TOURNEY_STAGE_HYPE_GIF_URL)
        stage_state["message_id"] = new_message.id
        stage_state["hype_message_id"] = hype_message.id
        stage_state["signature"] = signature
        print(
            f"[ANNOUNCE][{stage_key}] sent stage message {new_message.id} and hype gif {hype_message.id}"
        )

    async def _sync_winner_announcement(
        self,
        channel: discord.TextChannel,
        tournament_complete: bool,
        winner_team: str | None,
    ):
        winner_state = self._winner_announcement_state
        current_winner = winner_state.get("winner")
        current_message_id = winner_state.get("message_id")

        if not tournament_complete or not winner_team:
            reason = "tournament not complete" if not tournament_complete else "winner missing"
            print(f"[ANNOUNCE][winner] skip winner post: {reason}")
            if isinstance(current_message_id, int):
                try:
                    old_msg = await channel.fetch_message(current_message_id)
                    await old_msg.delete()
                    print(f"[ANNOUNCE][winner] deleted previous winner message {current_message_id}")
                except (discord.NotFound, discord.Forbidden):
                    pass
                except Exception as e:
                    print(f"Winner announcement cleanup error: {e}")
            winner_state["winner"] = None
            winner_state["message_id"] = None
            return

        if winner_team == current_winner and isinstance(current_message_id, int):
            print("[ANNOUNCE][winner] skip winner post: unchanged winner")
            return

        content = f"# GGs!\n{winner_team} won !! {TOURNEY_MATCHERINO_WIN_EMOJI}"

        if isinstance(current_message_id, int):
            try:
                old_msg = await channel.fetch_message(current_message_id)
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            except Exception as e:
                print(f"Winner announcement replace cleanup error: {e}")

        async for recent in channel.history(limit=10):
            if recent.author == self.bot.user and recent.content == content:
                winner_state["winner"] = winner_team
                winner_state["message_id"] = recent.id
                print(f"[ANNOUNCE][winner] skip winner post: identical content already exists ({recent.id})")
                return

        new_msg = await channel.send(content)
        winner_state["winner"] = winner_team
        winner_state["message_id"] = new_msg.id
        print(f"[ANNOUNCE][winner] sent winner message {new_msg.id} for {winner_team}")

    async def announce_high_stakes_matches(self, matcherino_id: str, progress_data: dict):
        async with self._announcement_lock:
            self._reset_announcement_state_if_needed(matcherino_id)

            updates_channel = self.bot.get_channel(TOURNEY_UPDATES_CHANNEL_ID)
            if not updates_channel:
                try:
                    fetched = await self.bot.fetch_channel(TOURNEY_UPDATES_CHANNEL_ID)
                    updates_channel = fetched if isinstance(fetched, discord.TextChannel) else None
                except Exception:
                    updates_channel = None
            if not updates_channel or not isinstance(updates_channel, discord.TextChannel):
                print(f"High-stakes announcements skipped: updates channel not found ({TOURNEY_UPDATES_CHANNEL_ID}).")
                return

            max_round = progress_data.get("max_round")
            active_matches = progress_data.get("active_matches", [])
            if not isinstance(max_round, int) or max_round < 1:
                print(f"[ANNOUNCE] skip all: invalid max_round={max_round}")
                return
            if not isinstance(active_matches, list):
                print("[ANNOUNCE] active_matches malformed; coercing to empty list")
                active_matches = []

            semi_round = max_round - 1
            semi_candidates = [
                m for m in active_matches
                if semi_round >= 1 and m.get("round") == semi_round and self._is_fully_matched(m)
            ]
            final_candidates = [
                m for m in active_matches
                if m.get("round") == max_round and self._is_fully_matched(m)
            ]

            # Some brackets may expose extra matches in these rounds.
            # We only need the canonical stage pairings: 2 semis, 1 finals.
            semi_candidates = sorted(
                semi_candidates,
                key=lambda m: m.get("id") if isinstance(m.get("id"), int) else 9999,
            )
            final_candidates = sorted(
                final_candidates,
                key=lambda m: m.get("id") if isinstance(m.get("id"), int) else 9999,
            )

            semi_finals = semi_candidates[:2] if len(semi_candidates) >= 2 else []
            finals = final_candidates[:1] if len(final_candidates) >= 1 else []

            print(
                f"[ANNOUNCE] scan matcherino={matcherino_id} max_round={max_round} active={len(active_matches)} "
                f"semi_candidates={len(semi_candidates)} finals_candidates={len(final_candidates)}"
            )

            await self._sync_stage_announcement(
                updates_channel,
                "semi_finals",
                "Semi Finals",
                semi_finals,
                required_count=2,
            )
            await self._sync_stage_announcement(
                updates_channel,
                "finals",
                "Finals",
                finals,
                required_count=1,
            )

            remaining_matches = max(0, int(progress_data.get("total", 0)) - int(progress_data.get("closed", 0)))
            tournament_complete = progress_data.get("completion_pct", 0) >= 100 or remaining_matches == 0
            winner_team = progress_data.get("winner_team")
            if isinstance(winner_team, str):
                winner_team = winner_team.strip()
            print(
                f"[ANNOUNCE] winner check complete={tournament_complete} "
                f"remaining_matches={remaining_matches} winner={winner_team or 'None'}"
            )
            await self._sync_winner_announcement(updates_channel, tournament_complete, winner_team)

    async def update_progress_dashboard(self):
        """Build or update a single persistent progress panel in the admin channel."""
        async with self._progress_dashboard_lock:
            session = await get_active_tourney_session()
            if not session or not session.get("matcherino_id"):
                return

            admin_channel = self.bot.get_channel(TOURNEY_ADMIN_CHANNEL_ID)
            if not admin_channel or not isinstance(admin_channel, discord.TextChannel):
                return

            m_id = session["matcherino_id"]
            bracket_url = f"https://matcherino.com/tournaments/{m_id}/bracket"
            data = fetch_bracket_progress(bracket_url)
            if data.get("status") != "success":
                return

            try:
                await self.announce_high_stakes_matches(m_id, data)
            except Exception as e:
                print(f"High-stakes announcement error: {e}")

            start_time = session['start_time']
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=datetime.timezone.utc)
            duration = discord.utils.utcnow() - start_time
            hours, mins = divmod(int(duration.total_seconds()), 3600)
            mins, _ = divmod(mins, 60)

            embed = discord.Embed(title="📈 Live Tournament Progress", color=discord.Color.gold())
            embed.description = (
                f"**⏱️ Total Duration:** `{hours}h {mins}m` | "
                f"**📈 Completion:** `{data['completion_pct']}%` ({data['closed']}/{data['total']})\n"
                f"**Last Updated:** <t:{int(discord.utils.utcnow().timestamp())}:R>"
            )

            remaining_matches = max(0, data['total'] - data['closed'])
            tournament_complete = data['completion_pct'] >= 100 or remaining_matches == 0

            if tournament_complete:
                path_text = "🏆 **Tournament Over!**"
            else:
                rounds_left = max(0, data['max_round'] - data['dominant_round'])
                path_text = f"{rounds_left} rounds remaining" if rounds_left > 0 else "🏆 **Finals in progress!**"

            active_matches_text = "No matches remaining" if tournament_complete else f"{data['active_count']} Currently Playable"

            embed.add_field(
                name="🏆 Bracket Status",
                value=(
                    f"• **Dominant Round:** Round {data['dominant_round']}\n"
                    f"• **Path to Finals:** {path_text}\n"
                    f"• **Active Matches:** {active_matches_text}"
                ),
                inline=False
            )

            if data['bottlenecks']:
                bn_text = ""
                for bn in data['bottlenecks'][:5]:
                    bn_text += f"**#{bn['id']}** (Round {bn['round']}) | {bn['team_a']} vs {bn['team_b']} ({bn['score_a']}-{bn['score_b']})\n"
                embed.add_field(name="⚠️ Bottleneck Matches", value=bn_text, inline=False)
            else:
                embed.add_field(name="⚠️ Bottleneck Matches", value="✅ All playable matches are current with the dominant round.", inline=False)

            embed.set_footer(text=f"Matcherino ID: {m_id} | Auto Refresh: 5m")

            try:
                existing_msg = None
                if self.dashboard_message_id:
                    try:
                        existing_msg = await admin_channel.fetch_message(self.dashboard_message_id)
                    except discord.NotFound:
                        existing_msg = None

                # Recovery path (bot restart / cache loss): locate prior dashboard message by title.
                if existing_msg is None:
                    async for m in admin_channel.history(limit=30):
                        if m.author == self.bot.user and m.embeds and m.embeds[0].title == "📈 Live Tournament Progress":
                            existing_msg = m
                            self.dashboard_message_id = m.id
                            break

                latest = [msg async for msg in admin_channel.history(limit=1)]
                latest_msg = latest[0] if latest else None

                # If dashboard is already the latest message, edit in place.
                if existing_msg and latest_msg and latest_msg.id == existing_msg.id:
                    await existing_msg.edit(embed=embed)
                    return

                # Otherwise repost so it jumps to the bottom as the newest message.
                new_msg = await admin_channel.send(embed=embed)
                self.dashboard_message_id = new_msg.id

                if existing_msg:
                    try:
                        await existing_msg.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass

            except Exception as e:
                print(f"Progress Dashboard Error: {e}")

    @tasks.loop(seconds=15)
    async def dashboard_task(self):
        """Original 15-second loop: Updates the live queue status in support channel."""
        await self.bot.wait_until_ready()
        
        channel = self.bot.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        guild = channel.guild
        cat = guild.get_channel(TOURNEY_CATEGORY_ID)
        
        active_tickets = []
        active_nums = []

        if cat and isinstance(cat, discord.CategoryChannel):
            active_tickets = [c for c in cat.channels if isinstance(c, discord.TextChannel) and "ticket-" in c.name]
            active_tickets.sort(key=lambda c: c.created_at)

            for t in active_tickets:
                match = re.search(r"ticket-(\d+)", t.name)
                if match:
                    try: active_nums.append(int(match.group(1)))
                    except: pass
            active_nums.sort()

        count = len(active_tickets)
        embed = discord.Embed(title="📊 Live Tournament Queue", color=discord.Color.blurple())
        
        if count == 0:
            embed.color = discord.Color.green()
            embed.description = "✅ **No tickets currently in the queue.**\nStaff are standing by!"
            serving_display = None
        else:
            max_closed_num = 0
            closed_cat = guild.get_channel(TOURNEY_CLOSED_CATEGORY_ID)
            if closed_cat and isinstance(closed_cat, discord.CategoryChannel):
                for ch in closed_cat.channels:
                    match = re.search(r"ticket-(\d+)", ch.name)
                    if match:
                        try:
                            num = int(match.group(1))
                            if num > max_closed_num: max_closed_num = num
                        except: pass
            
            target_num = max_closed_num + 1
            final_serving_num = target_num if target_num in active_nums else (min(active_nums) if active_nums else 0)
            serving_display = f"ticket-{final_serving_num:03d}"
            embed.color = discord.Color.orange()

        current_timestamp = int(discord.utils.utcnow().timestamp())
        embed.description = f"**Last Updated:** <t:{current_timestamp}:R>\n\n{embed.description or ''}"

        if serving_display:
            embed.add_field(name="🟢 Currently Serving", value=f"**{serving_display}**", inline=True)
            embed.add_field(name="👥 In Line", value=f"**{count}** tickets waiting", inline=True)

        try:
            old_dashboard_msg = None
            async for m in channel.history(limit=10):
                if m.author == self.bot.user and m.embeds and m.embeds[0].title == "📊 Live Tournament Queue":
                    old_dashboard_msg = m
                    break

            msgs = [msg async for msg in channel.history(limit=1)]
            last_message = msgs[0] if msgs else None

            if old_dashboard_msg and last_message and last_message.id == old_dashboard_msg.id:
                await old_dashboard_msg.edit(embed=embed)
            else:
                if old_dashboard_msg: await old_dashboard_msg.delete()
                await channel.send(embed=embed)
        except Exception as e:
            print(f"Queue Dashboard Error: {e}")

    @tasks.loop(minutes=1)
    async def match_refresher_task(self):
        """Refreshes Matcherino scores in active tickets every 1 minutes."""
        await self.bot.wait_until_ready()
        
        # 1. Get Matcherino ID from database
        m_id = await get_matcherino_id_from_active()
        if not m_id:
            return

        bracket_url = f"https://matcherino.com/tournaments/{m_id}/bracket"
        
        # 2. Locate the active guild safely
        dashboard_channel = self.bot.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if not dashboard_channel: return
        guild = dashboard_channel.guild
        category = guild.get_channel(TOURNEY_CATEGORY_ID)
        
        if not category or not isinstance(category, discord.CategoryChannel):
            return

        # 3. Process each ticket channel
        for channel in category.channels:
            # Skip if not a ticket, or if it is closed (👍) or inactive
            if not isinstance(channel, discord.TextChannel) or "ticket-" not in channel.name:
                continue
            if "👍" in channel.name or "❗" not in channel.name:
                continue

            # Parse Match Number and Team Name from topic
            match_num = None
            topic_team_name = None
            if channel.topic:
                match_res = re.search(r"bracket:(\d+)", channel.topic)
                if match_res:
                    try: match_num = int(match_res.group(1))
                    except: continue
                team_res = re.search(r"team:(.*?)(?:\||$)", channel.topic)
                if team_res:
                    topic_team_name = team_res.group(1).strip() or None

            if match_num is None: continue

            # 4. Fetch Fresh Match Data (with topic team for fuzzy mismatch check)
            data = fetch_ticket_context(bracket_url, match_num, topic_team_name=topic_team_name)
            if data.get("status") != "success":
                continue

            # 5. Construct the Live Embed with Relative Timestamp
            now_ts = int(discord.utils.utcnow().timestamp())
            is_mismatch = data.get("team_name_mismatch", False)
            best_match_team = data.get("team_name_best_match")
            embed = discord.Embed(
                title=f"📊 Live Match Update: Match #{match_num}",
                description=f"**Last Update:** <t:{now_ts}:R>",
                color=discord.Color.red() if is_mismatch else discord.Color.gold()
            )

            embed.add_field(name="Match Status", value=f"`{data['match_status'].upper()}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            team_a, team_b = data['team_a'], data['team_b']
            p_a = "\n".join([f"• {p}" for p in team_a['players']]) or "• *No players*"
            p_b = "\n".join([f"• {p}" for p in team_b['players']]) or "• *No players*"

            embed.add_field(name=f"🔵 {team_a['name']} ({team_a['score']})", value=f"**Roster:**\n{p_a}", inline=True)
            embed.add_field(name="⚔️", value="\u200b", inline=True)
            embed.add_field(name=f"🔴 {team_b['name']} ({team_b['score']})", value=f"**Roster:**\n{p_b}", inline=True)

            # For mismatches, keep the warning simple.
            if is_mismatch:
                warning_text = "The team name in this ticket does not closely match either team in the bracket for this match."
                if topic_team_name:
                    warning_text += f"\nTeam entered: `{topic_team_name}`"
                warning_text += "\nUse `/set-ticket-match` to correct the match number or team name."

                embed.add_field(
                    name="⚠️ Team name / Match number Mismatch",
                    value=warning_text,
                    inline=False,
                )
            # For close/exact matches, show the suspected bracket team in a code block for easy copy/paste.
            elif topic_team_name and best_match_team:
                embed.add_field(
                    name="Detected Team",
                    value=f"```\n{best_match_team}\n```",
                    inline=False,
                )

            embed.set_footer(text=f"Matcherino ID: {m_id}")

            # 6. Single live message: only edit the embed that shows THIS channel's match (from topic)
            try:
                old_info_msg = None
                async for msg in channel.history(limit=20):
                    if msg.author != self.bot.user or not msg.embeds:
                        continue
                    title = msg.embeds[0].title or ""
                    if "Matcherino Data" not in title and "Live Match Update" not in title:
                        continue
                    # Only update a message that already shows this channel's match number
                    title_match = re.search(r"Match #(\d+)", title)
                    if title_match and int(title_match.group(1)) == match_num:
                        old_info_msg = msg
                        break
                
                if old_info_msg:
                    await old_info_msg.edit(embed=embed)
                else:
                    await channel.send(embed=embed)
                
                # Sequential delay to avoid global rate limits
                await asyncio.sleep(1.5)

            except Exception as e:
                print(f"Refresher error in {channel.name}: {e}")

    @tasks.loop(minutes=5)
    async def progress_dashboard_task(self):
        """Refreshes the tournament progress dashboard every 5 minutes."""
        await self.bot.wait_until_ready()
        await self.update_progress_dashboard()
            
class BlacklistGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="blacklist", description="Manage tournament blacklisted users")
        self.bot = bot

    @app_commands.command(name="add", description="Blacklist a user from tournaments.")
    @app_commands.describe(
        user="The user to blacklist",
        reason="Why are they being blacklisted?",
        matcherino="Link to their Matcherino profile (Optional)",
        alts="List of Alt User IDs or mentions (space separated) (Optional)"
    )
    async def blacklist_add(self, interaction: discord.Interaction, user: discord.User, reason: str, matcherino: str = None, alts: str = None):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Parse Alts string into a list of IDs
        alt_ids = []
        if alts:
            # clear out <@! > formatting to get raw IDs
            raw_ids = re.findall(r'\d+', alts)
            alt_ids = list(set(raw_ids)) # unique IDs only

        await add_blacklisted_user(
            user_id=str(user.id),
            reason=reason,
            admin_id=str(interaction.user.id),
            matcherino=matcherino,
            alts=alt_ids
        )

        embed = discord.Embed(title="⛔ User Blacklisted", color=discord.Color.dark_red())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        if matcherino:
            embed.add_field(name="Matcherino", value=matcherino, inline=False)
        if alt_ids:
            alt_mentions = ", ".join([f"<@{aid}>" for aid in alt_ids])
            embed.add_field(name="Registered Alts", value=alt_mentions, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Remove a user from the blacklist.")
    async def blacklist_remove(self, interaction: discord.Interaction, user: discord.User):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Check if they are actually blacklisted first
        existing = await get_blacklisted_user(str(user.id))
        if not existing:
            await interaction.response.send_message(f"⚠️ {user.mention} is not currently blacklisted.", ephemeral=True)
            return

        await remove_blacklisted_user(str(user.id))
        await interaction.response.send_message(f"✅ {user.mention} has been removed from the blacklist.")

    @app_commands.command(name="list", description="View all blacklisted users.")
    async def blacklist_list(self, interaction: discord.Interaction):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        users = await get_all_blacklisted_users()
        if not users:
            await interaction.response.send_message("✅ No users are currently blacklisted.", ephemeral=True)
            return

        # Simple pagination or long list logic
        embed = discord.Embed(title="⛔ Blacklisted Users", color=discord.Color.dark_red())
        
        description_lines = []
        for doc in users:
            uid = doc["_id"]
            reason = doc.get("reason", "No reason provided")
            date_str = doc.get("timestamp").strftime("%Y-%m-%d") if doc.get("timestamp") else "Unknown Date"
            description_lines.append(f"• <@{uid}> (`{uid}`) — {date_str}\n  Reason: *{reason}*")

        # Join lines. If too long, Discord will error, so ideally chunk this. 
        # For now, we truncate to 4000 chars to be safe.
        full_text = "\n\n".join(description_lines)
        if len(full_text) > 4000:
            full_text = full_text[:3990] + "... (list truncated)"
            
        embed.description = full_text
        await interaction.response.send_message(embed=embed)
                                    
def setup_tourney_commands(bot: commands.Bot):
    sticky_redirect_state = {"enabled": False, "region": None}

    @bot.command(name="close", aliases=["c"])
    async def close_command(ctx: commands.Context):
        """Close a tourney ticket (staff only)."""
        active_session = await get_active_tourney_session()
        if active_session:
            await increment_staff_closure(active_session['_id'], ctx.author.id, ctx.author.name)
            await update_tourney_queue(active_session['_id'], change=-1)
        # -----------------------
        
        await close_ticket_via_command(ctx)

    @bot.command(name="lock")
    async def lock_command(ctx: commands.Context):
        """Temporarily lock the OTHER ticket channel from members."""
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to lock the ticket channel.")
            return

        channel = bot.get_channel(OTHER_TICKET_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await ctx.reply("Configured ticket channel not found. Check OTHER_TICKET_CHANNEL_ID.")
            return

        guild = channel.guild

        # Use member role from config, or @everyone if MEMBER_ROLE_ID is None
        if MEMBER_ROLE_ID is None:
            member_role = guild.default_role
        else:
            member_role = guild.get_role(MEMBER_ROLE_ID)

        if member_role is None:
            await ctx.reply("Member role not found in this server.")
            return

        # Hide from members
        await channel.set_permissions(member_role, view_channel=False)
        await ctx.reply(
            f"🔒 Locked {channel.mention}. It will auto-reopen in {LOCK_DURATION_HOURS} hours "
            f"or when `!reopen` is used."
        )

        # Cancel any old timer
        old = lock_tasks.get(channel.id)
        if old and not old.done():
            old.cancel()

        # Remember where the command was run so we can notify there later
        notify_channel_id = ctx.channel.id

        async def auto_reopen():
            try:
                await asyncio.sleep(LOCK_DURATION_HOURS * 3600)
            except asyncio.CancelledError:
                return  # manually reopened with !reopen

            ticket_ch = bot.get_channel(OTHER_TICKET_CHANNEL_ID)
            if isinstance(ticket_ch, discord.TextChannel):
                await ticket_ch.set_permissions(member_role, view_channel=True)

            # Notify in the original channel where !lock was used
            notify_ch = bot.get_channel(notify_channel_id)
            if isinstance(notify_ch, discord.TextChannel):
                await notify_ch.send(
                    f"🔓 Reopened {ticket_ch.mention} automatically after {LOCK_DURATION_HOURS} hours."
                )

        task = asyncio.create_task(auto_reopen())
        lock_tasks[channel.id] = task

    @bot.command(name="unlock")
    async def unlock_command(ctx: commands.Context):
        """
        Manually unlock the general support channel (Legacy feature).
        Previously named !reopen.
        """
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to unlock the ticket channel.")
            return

        channel = bot.get_channel(OTHER_TICKET_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await ctx.reply("Configured ticket channel not found. Check OTHER_TICKET_CHANNEL_ID.")
            return

        guild = channel.guild

        if MEMBER_ROLE_ID is None:
            member_role = guild.default_role
        else:
            member_role = guild.get_role(MEMBER_ROLE_ID)

        if member_role is None:
            await ctx.reply("Member role not found in this server.")
            return

        # Restore permissions for members
        await channel.set_permissions(member_role, view_channel=True)

        # Cancel any auto-lock timer
        task = lock_tasks.pop(channel.id, None)
        if task and not task.done():
            task.cancel()

        await ctx.reply(f"🔓 **Unlocked** {channel.mention}. Members can see it again.")
        
    @bot.command(name="delete", aliases=["del"])
    async def delete_command(ctx: commands.Context):
        """Delete a ticket (backup for button)."""
        await delete_ticket_via_command(ctx)

    @bot.command(name="reopen")
    async def reopen_command(ctx: commands.Context):
        """
        Reopen a closed tourney ticket channel.
        Moves it from the Closed Category back to the Active Category.
        """
        # Check if we are inside a CLOSED ticket category
        if ctx.channel.category_id in (TOURNEY_CLOSED_CATEGORY_ID, PRE_TOURNEY_CLOSED_CATEGORY_ID):
            await reopen_ticket_via_command(ctx)
        else:
            await ctx.reply("⚠️ This command is for reopening **Closed Tourney Tickets**.\nTo unlock the main support channel, use `!unlock`.")

    @bot.command(name="starttourney")
    async def start_tourney_command(ctx: commands.Context, region: str = None):
        import features.config as config
        """
        Start a tourney with an optional region (e.g., !starttourney SA).
        """
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to start the tourney.")
            return

        guild = ctx.guild
        if not guild: return

        normalized_region = region.upper() if isinstance(region, str) else None

        # Enable sticky redirect notices while tournament mode is active.
        sticky_redirect_state["enabled"] = True
        sticky_redirect_state["region"] = normalized_region

        # Standard Startup Logic
        reset_ticket_counter()
        existing_session = await get_active_tourney_session()
        if not existing_session:
            await create_tourney_session()
        else:
            await reset_tourney_session_start_time(existing_session["_id"])
        
        await lock_command(ctx)

        # --- SA REGION LOGIC ---
        if normalized_region == "SA":
            from features.config import SPANISH_CHANNEL_ID
            spa_channel = guild.get_channel(SPANISH_CHANNEL_ID)
            
            if isinstance(spa_channel, discord.TextChannel):
                # 1. Lock sending messages
                await spa_channel.set_permissions(guild.default_role, send_messages=False)
                
                # 2. Send Large Redirect Message
                main_support = guild.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
                support_mention = main_support.mention if main_support else "#tourney-support"
                
                embed = discord.Embed(
                    description=f"# ⚠️ ¡Atención!\n# Por favor, utiliza {support_mention} para abrir un ticket de apoyo para el torneo.",
                    color=discord.Color.red()
                )
                await spa_channel.send(embed=embed)
                await ctx.send(f"✅ SA Region active: {spa_channel.mention} has been locked and redirected.")

        # 2. Update MAIN Tourney Support Channel
        # GOAL: 「🔴」tourney-support | Perms: Everyone View(/) Send(X)
        main_channel = guild.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(main_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical - Do this first)
            overwrites = main_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await main_channel.edit(overwrites=overwrites)
            await main_channel.purge()

            # B. Send Panel (Critical)
            panel_text = (
                "Experiencing a match issue? We’ve got you covered.\n"
                "Use this if you're dealing with:\n\n"
                "⚠️ **No-show opponents**\n"
                "⚔️ **Score disputes**\n"
                "🛜 **Lobby / connection problems**\n"
                "📜 **Rule questions or clarifications**\n"
                "🔧 **Anything else blocking your match**\n\n"
                "Click the button below to open a **private support ticket**.\n\n"
                "You’ll be prompted to provide:\n"
                "📛 **Team Name**\n"
                "🔢 **Match / Bracket Number**\n"
                "📝 **Description of the Issue**\n\n"
                "A Tourney Admin will assist you as soon as possible. 🛠️"
            )

            # 2. Add the Test Mode warning if it's toggled ON
            if config.TOURNEY_TEST_MODE:
                panel_text += "\n\n🧪 **TEST MODE ACTIVE**: Limits set to 100 tickets | 0.1s cooldown."

            # 3. Create a single embed using that text
            embed = discord.Embed(
                title="🎟️ Tournament Support Ticket",
                description=panel_text,
                color=discord.Color.red() if config.TOURNEY_TEST_MODE else discord.Color.blurple()
            )

            # 5. Send it to the channel (using .send for TextChannels)
            await main_channel.send(embed=embed, view=TourneyOpenTicketView())

            # C. Attempt Rename (Background Task - Won't block if rate limited)
            asyncio.create_task(main_channel.edit(name="「🔴」tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Main Tourney Channel (ID: {TOURNEY_SUPPORT_CHANNEL_ID})")

        # 3. Update PRE-Tourney Support Channel
        # GOAL: 「❌❌❌」「🟡」pre-tourney-support | Perms: Everyone View(X)
        pre_channel = guild.get_channel(PRE_TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(pre_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical)
            overwrites = pre_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await pre_channel.edit(overwrites=overwrites)
            await pre_channel.purge() 

            # B. Attempt Rename (Background Task)
            asyncio.create_task(pre_channel.edit(name="「❌❌❌」「🟡」pre-tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Pre-Tourney Channel (ID: {PRE_TOURNEY_SUPPORT_CHANNEL_ID})")

        # 4. Delete ALL Pre-Tourney Tickets
        deleted_count = 0
        categories_to_check = [PRE_TOURNEY_CATEGORY_ID, PRE_TOURNEY_CLOSED_CATEGORY_ID]
        
        for cat_id in categories_to_check:
            pre_category = guild.get_channel(cat_id)
            if isinstance(pre_category, discord.CategoryChannel):
                for ch in pre_category.channels:
                    if isinstance(ch, discord.TextChannel) and "ticket-" in ch.name and ch.id != PRE_TOURNEY_SUPPORT_CHANNEL_ID:
                        try:
                            await delete_ticket_with_transcript(guild, ch, ctx.author, bot)
                            deleted_count += 1
                        except Exception as e:
                            print(f"Failed to delete pre-tourney ticket {ch.name}: {e}")
        
        await ctx.send(f"✅ Tourney Started! Channels updated and {deleted_count} pre-tourney tickets deleted.")

        # START THE DASHBOARD
        dashboard_cog = bot.get_cog("QueueDashboard")
        if dashboard_cog:
            await dashboard_cog.start_dashboard()

    @bot.command(name="endtourney")
    async def end_tourney_command(ctx: commands.Context):
        """
        End the tourney:
        - Reopen the "Other" ticket channel.
        - Setup Main Tourney Support (Close Perms, then Background Rename).
        - Setup Pre-Tourney Support (Open Perms, Send Panel, then Background Rename).
        - Close & delete all MAIN tourney tickets.
        """
        if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
            await ctx.reply("You don't have permission to end the tourney.")
            return

        guild = ctx.guild
        if guild is None:
            return

        # Force one last high-stakes/winner announcement sync so !endtourney doesn't
        # depend on the 5-minute loop timing.
        dashboard_cog = bot.get_cog("QueueDashboard")
        active_session_for_announcement = await get_active_tourney_session()
        if (
            dashboard_cog
            and active_session_for_announcement
            and active_session_for_announcement.get("matcherino_id")
        ):
            try:
                matcherino_id = active_session_for_announcement["matcherino_id"]
                bracket_url = f"https://matcherino.com/tournaments/{matcherino_id}/bracket"
                data = fetch_bracket_progress(bracket_url)
                if data.get("status") == "success":
                    await dashboard_cog.announce_high_stakes_matches(matcherino_id, data)
            except Exception as e:
                print(f"!endtourney announcement sync error: {e}")

        if dashboard_cog:
            await dashboard_cog.stop_dashboard()

        # Disable sticky redirect notices immediately when tournament ends.
        sticky_redirect_state["enabled"] = False
        sticky_redirect_state["region"] = None
        await cleanup_sticky_redirects(guild)

        session = await get_active_tourney_session()
        if session:
            # 1. Calculate Duration
            start_time = session['start_time']

            # Ensure start_time is aware of UTC to prevent subtraction errors
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=datetime.timezone.utc)

            duration = datetime.datetime.now(datetime.timezone.utc) - start_time
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)

            # 2. Get Staff Leaderboard
            top_staff = await get_top_staff_stats(session['_id'], limit=12)
            
            staff_msg = ""
            
            for i, s in enumerate(top_staff):
                if i == 0: icon = "🥇"
                elif i == 1: icon = "🥈"
                elif i == 2: icon = "🥉"
                else: icon = f"**{i+1}.**" # e.g. "4.", "5.", "6."
                
                staff_msg += f"{icon} **{s['username']}**: {s['tickets_closed']} tickets\n"
            
            if not staff_msg: staff_msg = "No tickets closed."

            # 3. Send Embed
            stat_embed = discord.Embed(title="📊 Tournament Report", color=discord.Color.gold())
            stat_embed.add_field(name="⏱️ Duration", value=f"`{hours}h {minutes}m`", inline=True)
            stat_embed.add_field(name="📩 Total Tickets", value=f"`{session['total_tickets']}`", inline=True)
            stat_embed.add_field(name="💬 Total Messages", value=f"`{session['total_messages']}`", inline=True)
            stat_embed.add_field(name="📈 Peak Queue", value=f"**{session['peak_queue']}** tickets", inline=False)
            stat_embed.add_field(name="🏆 Top Tourney Admins", value=staff_msg, inline=False)
                        
            report_msg = await ctx.send(embed=stat_embed)
            
            try:
                await report_msg.pin()
            except Exception as e:
                print(f"⚠️ Could not pin report: {e}")
            
            # 4. Close Session in DB
            await end_tourney_session(session['_id'])
        # ------------------------------

        await unlock_command(ctx)
        
        from features.config import SPANISH_CHANNEL_ID
        guild = ctx.guild
        spa_channel = guild.get_channel(SPANISH_CHANNEL_ID)
        if isinstance(spa_channel, discord.TextChannel):
            # Restore send_messages permission
            await spa_channel.set_permissions(guild.default_role, send_messages=True)
            await ctx.send(f"🔓 {spa_channel.mention} has been unlocked.")

        # 1. Update MAIN Tourney Support Channel
        # GOAL: 「❌❌❌」「🔴」tourney-support | Perms: Everyone View(X)
        main_channel = guild.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(main_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical)
            overwrites = main_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await main_channel.edit(overwrites=overwrites)
            await main_channel.purge()

            # B. Attempt Rename (Background Task)
            asyncio.create_task(main_channel.edit(name="「❌❌❌」「🔴」tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Main Tourney Channel (ID: {TOURNEY_SUPPORT_CHANNEL_ID})")

        # 2. Update PRE-Tourney Support Channel
        # GOAL: 「🟡」pre-tourney-support | Perms: Everyone View(/) Send(X)
        pre_channel = guild.get_channel(PRE_TOURNEY_SUPPORT_CHANNEL_ID)
        if isinstance(pre_channel, discord.TextChannel):
            # A. Update Permissions & Purge (Critical)
            overwrites = pre_channel.overwrites
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
            
            for role_id in ALLOWED_STAFF_ROLES:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            await pre_channel.edit(overwrites=overwrites)
            await pre_channel.purge()

            # B. Send Pre-Tourney Panel (Critical)
            embed = discord.Embed(
                title="📩 Pre-Tournament Support",
                description=(
                    "Need help before the tournament starts? Use this for:\n\n"
                    "📋 **Registration Issues**\n"
                    "🤝 **Team / Roster Questions**\n"
                    "❓ **General Inquiries**\n\n"
                    "Click the button below to open a ticket. **Team Name** is optional." 
                ),
                color=discord.Color.orange()
            )
            await pre_channel.send(embed=embed, view=PreTourneyOpenTicketView())

            # C. Attempt Rename (Background Task)
            asyncio.create_task(pre_channel.edit(name="「🟡」pre-tourney-support"))
        else:
            await ctx.send(f"⚠️ Could not find Pre-Tourney Channel (ID: {PRE_TOURNEY_SUPPORT_CHANNEL_ID})")

        # 3. Delete ALL MAIN Tourney Tickets
        ticket_channels: list[discord.TextChannel] = []
        categories_to_check = [TOURNEY_CATEGORY_ID, TOURNEY_CLOSED_CATEGORY_ID]

        for cat_id in categories_to_check:
            cat = guild.get_channel(cat_id)
            if isinstance(cat, discord.CategoryChannel):
                for ch in cat.channels:
                    # Delete if it's a ticket and NOT the support channel
                    if isinstance(ch, discord.TextChannel) and "ticket-" in ch.name and ch.id != TOURNEY_SUPPORT_CHANNEL_ID:
                        ticket_channels.append(ch)

        if not ticket_channels:
            await ctx.reply("No tourney tickets found to delete.")
            return

        await ctx.reply(
            f"Ending tourney. Deleting {len(ticket_channels)} ticket(s) with transcripts..."
        )

        for ch in ticket_channels:
            try:
                await delete_ticket_with_transcript(
                    guild=guild,
                    channel=ch,
                    deleter=ctx.author,
                    client=bot,
                )
            except Exception as e:
                print(f"Error deleting ticket {ch.id} ({ch.name}): {e}")


    # =========================================================================
    #  SLASH COMMANDS (Restored from your New File)
    # =========================================================================

    @app_commands.command(name="tourney-panel", description="Post the tourney support button.")
    async def tourney_panel(interaction: discord.Interaction):
        import features.config as config
        
        # 1. Permission Check
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return
        
        # 2. Define the base description in a variable first
        panel_desc = (
            "Experiencing a match issue? We’ve got you covered.\n"
            "Use this if you're dealing with:\n\n"
            "⚠️ **No-show opponents**\n"
            "⚔️ **Score disputes**\n"
            "🛜 **Lobby / connection problems**\n"
            "📜 **Rule questions or clarifications**\n"
            "🔧 **Anything else blocking your match**\n\n"
            "Click the button below to open a **private support ticket**.\n\n"
            "You’ll be prompted to provide:\n"
            "📛 **Team Name**\n"
            "🔢 **Match / Bracket Number**\n"
            "📝 **Description of the Issue**\n\n"
            "A Tourney Admin will assist you as soon as possible. 🛠️"
        )

        # 3. Modify text and select color based on Test Mode
        embed_color = discord.Color.blurple()
        
        if config.TOURNEY_TEST_MODE:
            panel_desc += "\n\n🧪 **TEST MODE ACTIVE**: Limits set to 100 tickets | 0.1s cooldown."
            embed_color = discord.Color.red()

        # 4. Create the single embed object
        embed = discord.Embed(
            title="🎟️ Tournament Support Ticket",
            description=panel_desc,
            color=embed_color
        )

        # 6. Send the response
        await interaction.response.send_message(embed=embed, view=TourneyOpenTicketView())
        
    @app_commands.command(name="pre-tourney-panel", description="Post the Pre-Tourney support button.")
    async def pre_tourney_panel(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📩 Pre-Tournament Support",
            description=(
                "Need help before the tournament starts? Use this for:\n\n"
                "📋 **Registration Issues**\n"
                "🤝 **Team / Roster Questions**\n"
                "❓ **General Inquiries**\n\n"
                "Click the button below to open a ticket. **Team Name** is optional."
            ),
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, view=PreTourneyOpenTicketView())

    @app_commands.command(name="add", description="Add a user to this tourney ticket.")
    async def add_to_ticket(interaction: discord.Interaction, user: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("You don't have permission to add users to tickets.", ephemeral=True)
            return
        
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a ticket text channel.", ephemeral=True)
            return

        if channel.category_id not in (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID):
            await interaction.response.send_message("This command can only be used inside a tourney ticket channel.", ephemeral=True)
            return

        await channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            use_application_commands=True,
        )
        await interaction.response.send_message(f"✅ Added {user.mention} to this ticket.", ephemeral=True)
        await channel.send(f"{user.mention} has been added to this ticket by {interaction.user.mention}.")
    
    @app_commands.command(name="remove", description="Remove a user from this tourney ticket.")
    async def remove_from_ticket(interaction: discord.Interaction, user: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("You don't have permission to remove users from tickets.", ephemeral=True)
            return
        
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("This command can only be used in a ticket text channel.", ephemeral=True)
            return

        if channel.category_id not in (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID):
            await interaction.response.send_message("This command can only be used inside a tourney ticket channel.", ephemeral=True)
            return

        await channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(f"✅ Removed {user.mention} from this ticket.", ephemeral=True)
        await channel.send(f"{user.mention} has been removed from this ticket by {interaction.user.mention}.")

    @app_commands.command(name="hall-of-fame", description="Automatically fetch results and post to Hall of Fame.")
    @app_commands.describe(tournament_id="The Matcherino ID (e.g. 183089)")
    async def hall_of_fame(interaction: discord.Interaction, tournament_id: str):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Get the target channel first to ensure config is correct
        target_channel = interaction.guild.get_channel(HALL_OF_FAME_CHANNEL_ID)
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message(f"❌ Could not find Hall of Fame channel (ID: {HALL_OF_FAME_CHANNEL_ID}).", ephemeral=True)
            return

        await interaction.response.defer()

        # Clean ID and fetch data using the new scraper
        clean_id = "".join(filter(str.isdigit, tournament_id))
        data = fetch_payout_report(clean_id)

        if "error" in data:
            await interaction.followup.send(f"❌ **Error:** {data['error']}", ephemeral=True)
            return

        # Map variables for the embed
        tourney_name = data['tourney_name']
        link = f"https://matcherino.com/tournaments/{clean_id}"
        total = data['total']
        res = data['results']

        embed = discord.Embed(
            title=f"🏆 {tourney_name}",
            url=link,
            description=(
                f"💰 **Total Prize:** ${total:.2f}\n\n"
                f"🥇 **{res['1st']}** — ${res['p1']:.2f} (50%)\n"
                f"🥈 **{res['2nd']}** — ${res['p2']:.2f} (25%)\n"
                f"🥉 **{res['3rd']}** — ${res['p3']:.2f} (15%)\n"
                f"4️⃣ **{res['4th']}** — ${res['p4']:.2f} (10%)"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Congratulations to the winners! 🎉")

        try:
            await target_channel.send(embed=embed)
            await interaction.followup.send(f"✅ Hall of Fame post sent to {target_channel.mention}!")
        except discord.Forbidden:
            await interaction.followup.send(f"❌ I don't have permission to post in {target_channel.mention}.", ephemeral=True)

    # =========================================================================
    #  PAYOUT COMMANDS
    # =========================================================================

    @app_commands.command(name="payout-add", description="Add compensation for tourney admins.")
    @app_commands.describe(
        mode="Split: Divides amount among admins. Flat: Each admin gets the full amount.",
        amount="The amount of currency.",
        staff_mentions="Mention the admins (e.g. @Admin1 @Admin2)",
        reason="Reason for this payout (e.g. Weekly Tourney)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Split Total Evenly", value="split"),
        app_commands.Choice(name="Flat Rate Per Person", value="flat")
    ])
    async def payout_add(interaction: discord.Interaction, mode: str, amount: float, staff_mentions: str, reason: str):
        # 1. Security Check
        if not isinstance(interaction.user, discord.Member) or not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ You do not have permission to manage payouts.", ephemeral=True)
            return

        # 2. Parse User IDs
        found_ids = [str(uid) for uid in re.findall(r'<@!?(\d+)>', staff_mentions)]
        staff_ids = list(set(found_ids)) # Remove duplicates

        if not staff_ids:
            await interaction.response.send_message("❌ No valid user mentions found.", ephemeral=True)
            return

        # 3. Calculate Math
        payout_per_person = 0
        if mode == "split":
            payout_per_person = amount / len(staff_ids)
        else:
            payout_per_person = amount

        # 4. Update Database (Batch System)
        await add_payout_batch(payout_per_person, staff_ids, reason)

        # 5. Response
        embed = discord.Embed(title="💰 Payouts Recorded", color=discord.Color.green())
        embed.add_field(name="Mode", value=mode.title(), inline=True)
        embed.add_field(name="Amount Per Admin", value=f"{payout_per_person:,.2f}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        mentions_str = " ".join([f"<@{uid}>" for uid in staff_ids])
        embed.add_field(name="Staff Credited", value=mentions_str, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="payout-list", description="View all pending tourney admin payouts.")
    async def payout_list(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        rows = await get_all_pending_payouts()

        if not rows:
            await interaction.response.send_message("✅ No pending payouts found. All clear!", ephemeral=True)
            return

        embed = discord.Embed(title="🧾 Pending Staff Payouts", color=discord.Color.blurple())
        description = ""
        total_owed = 0

        for row in rows:
            user_id = row["_id"]
            amt = row.get("amount", 0)
            if amt > 0:
                description += f"<@{user_id}>: **{amt:,.2f}**\n"
                total_owed += amt

        if total_owed == 0:
             await interaction.response.send_message("✅ No pending payouts found (balances are 0).", ephemeral=True)
             return

        embed.description = description
        embed.set_footer(text=f"Total Treasury Needed: {total_owed:,.2f}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="payout-reset", description="Clear payouts (Cash Out).")
    @app_commands.describe(target="Leave empty to reset ALL, or tag a user to reset only them.")
    async def payout_reset(interaction: discord.Interaction, target: discord.User = None):
        if not isinstance(interaction.user, discord.Member) or not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        # Option A: Reset One Person
        if target:
            await clear_pending_payout(str(target.id))
            await interaction.response.send_message(f"✅ Cashed out {target.mention}. Receipts cleared.", ephemeral=False)
            return

        # Option B: Reset EVERYONE
        view = PayoutResetConfirmView()
        await interaction.response.send_message(
            "⚠️ **WARNING** ⚠️\nYou are about to wipe **ALL** pending staff payouts.\nAre you sure?", 
            view=view, 
            ephemeral=True
        )

        await view.wait()
        
        if view.value is True:
            await clear_pending_payout(None)
            await interaction.followup.send("✅ All pending admin payouts have been cashed out.", ephemeral=False)
        else:
            await interaction.followup.send("❌ Operation cancelled.", ephemeral=True)

    @app_commands.command(name="payout-history", description="View log of multi-user additions.")
    async def payout_history(interaction: discord.Interaction):
        """
        Displays logs for multi-user adds. 
        Only shows users who still 'owe' the specific batch ID (have not been reset).
        """
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return
            
        logs = await get_payout_logs(limit=20)
        if not logs:
            await interaction.response.send_message("No logs found.", ephemeral=True)
            return

        embed = discord.Embed(title="📜 Group Payout History", color=discord.Color.gold())
        logs_found = False

        for entry in logs:
            # FILTER 1: Only show logs where multiple people were involved
            if len(entry["user_ids"]) <= 1:
                continue

            batch_id = entry.get("batch_id")
            active_users_display = []

            # FILTER 2: Check who still has the receipt
            for uid in entry["user_ids"]:
                user_batches = await get_user_unpaid_batches(uid)
                # If the batch_id is still in their list, they haven't been paid for this yet.
                if batch_id in user_batches:
                    active_users_display.append(f"<@{uid}>")

            # FILTER 3: If everyone in this log has been paid out, skip showing the log
            if not active_users_display:
                continue

            logs_found = True
            date_str = entry["timestamp"].strftime("%Y-%m-%d")
            
            users_str = ", ".join(active_users_display)
            value_text = (
                f"**Amount:** {entry['amount']:,.2f} per person\n"
                f"**Reason:** {entry['reason']}\n"
                f"**Included:** {users_str}"
            )
            
            embed.add_field(name=f"📅 {date_str} - Group Add", value=value_text, inline=False)

        if logs_found:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("✅ No outstanding multi-user payouts found.", ephemeral=True)
            
    @app_commands.command(name="queue", description="Check your current position in the ticket line.")
    async def check_queue(interaction: discord.Interaction):
        # 1. Validation
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or "ticket-" not in channel.name:
            await interaction.response.send_message("❌ This command can only be used inside a ticket channel.", ephemeral=True)
            return

        # 2. Identify Queue
        if channel.category_id == TOURNEY_CATEGORY_ID:
            cat = interaction.guild.get_channel(TOURNEY_CATEGORY_ID)
        elif channel.category_id == PRE_TOURNEY_CATEGORY_ID:
            cat = interaction.guild.get_channel(PRE_TOURNEY_CATEGORY_ID)
        else:
            await interaction.response.send_message("❌ This ticket is not in an active queue.", ephemeral=True)
            return

        # 3. Calculate Position
        tickets = [c for c in cat.channels if isinstance(c, discord.TextChannel) and "ticket-" in c.name]
        tickets.sort(key=lambda c: c.created_at)

        try:
            position = tickets.index(channel) + 1
            total = len(tickets)
        except ValueError:
            await interaction.response.send_message("Could not determine position.", ephemeral=True)
            return

        # 4. Report
        if position == 1:
            status = "🟢 **NOW SERVING**"
            desc = f"You are **1/{total}** in the queue.\nA staff member should be with you momentarily!"
            color = discord.Color.green()
        else:
            status = "🟠 **WAITING**"
            desc = f"You are **{position}/{total}** in the queue.\nPlease wait for a staff member."
            color = discord.Color.orange()

        embed = discord.Embed(title="⏳ Queue Status", description=desc, color=color)
        embed.add_field(name="Current Status", value=status, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @app_commands.command(name="tourney-admin-help", description="STAFF ONLY: Guide to Tournament Management commands.")
    async def tourney_admin_help(interaction: discord.Interaction):
        # Security Check: Only allow staff
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied. This command is for Tournament Staff only.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🛠️ Tournament Admin Guide | {BOT_VERSION}",
            description="Welcome to the Tourney Staff portal. Here is your cheat sheet for managing tournaments and support tickets.",
            color=discord.Color.dark_theme()
        )

        # --- 1. Session & Channel Management ---
        session_text = (
            "`!starttourney` - Wipes old tickets, locks the general server support channel, and posts the live support panel.\n"
            "`!endtourney` - Closes all active tickets, generates staff stats, posts the Pre-Tourney panel, and unlocks general support.\n"
            "`!lock` / `!unlock` - Manually close or open the general server support channel."
        )
        embed.add_field(name="⚙️ Session Management", value=session_text, inline=False)

        # --- 2. Ticket Commands ---
        ticket_text = (
            "`!close` (or `!c`) - Closes the current ticket and adds to your completed stats.\n"
            "`!reopen` - Moves a closed ticket back to the active category.\n"
            "`/add` / `/remove` - Add or remove a specific user to/from the current ticket."
        )
        embed.add_field(name="🎫 Ticket Control", value=ticket_text, inline=False)

        # --- Live Bracket / Matcherino ---
        matcherino_text = (
            "`/set-matcherino` - Set the active Matcherino bracket ID for the session.\n"
            "`/match-info` - Show live rosters, scores, and match status for a match number.\n"
            "`/match-history` - Show a team's previous rounds for a given match.\n"
            "`/set-ticket-match` - Correct this ticket's match number or team name."
        )
        embed.add_field(name="📊 Live Bracket / Matcherino", value=matcherino_text, inline=False)

        treasury_text = (
            "`/payout-list` - View your personal and team pending payout totals.\n"
            "`/payout-history` - View the audit log for group payout additions."
        )
        embed.add_field(name="💰 Treasury & Logs", value=treasury_text, inline=False)

        # --- 3. Moderation & Results ---
        mod_text = (
            "`/blacklist` `add/remove/list` - Manage users banned from participating.\n"
            "`/hall-of-fame <tourney_id>` - Uses the Matcherino Tourney ID to fetch the top 4 teams, calculates prize splits, and posts the results embed."
        )
        embed.add_field(name="⚖️ Moderation & Results", value=mod_text, inline=False)

        # --- 4. Workflow Guide ---
        workflow_text = (
            "**1. Claiming:** When a user opens a ticket, read their submitted Team Name and Issue.\n"
            "**2. Assisting:** Request screenshot proof for no-shows or score disputes.\n"
            "**3. Matcherino:** Perform the necessary actions (advancing teams, resetting matches, etc.) on the bracket on the Matcherino website.\n"
            "**4. Closing:** Once the issue is resolved in the bracket, let the players know they are good to go and type `!close` to archive the channel."
        )
        embed.add_field(name="🔄 Support Workflow", value=workflow_text, inline=False)

        # Ephemeral = True ensures no one else sees this message
        await interaction.response.send_message(embed=embed, ephemeral=True)
   
    bot.active_brackets = {} 

    @app_commands.command(name="set-matcherino", description="STAFF ONLY: Set the active Matcherino ID.")
    @app_commands.describe(m_id="The numeric Matcherino ID (e.g., 180454)")
    async def set_matcherino(interaction: discord.Interaction, m_id: str):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        active_session = await get_active_tourney_session()
        if not active_session:
            await interaction.response.send_message("❌ No active tourney session found. Start one first!", ephemeral=True)
            return

        # Extract only the numbers in case they paste a URL
        clean_id = "".join(filter(str.isdigit, m_id))
        if not clean_id:
            await interaction.response.send_message("❌ Please provide a numeric ID.", ephemeral=True)
            return
            
        await update_matcherino_id(active_session['_id'], clean_id)
        await interaction.response.send_message(f"✅ Active Matcherino ID set to: `{clean_id}`", ephemeral=True)
        
    @app_commands.command(name="tourney-test-mode", description="Toggle 100 tickets/0.1s cooldown for testing.")
    @app_commands.describe(enabled="True to enable test mode, False to return to production.")
    async def tourney_test_mode(interaction: discord.Interaction, enabled: bool):
        # Updated Security check: Now allows anyone in ALLOWED_STAFF_ROLES
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff permissions required.", ephemeral=True)
            return

        from features import config 
        config.TOURNEY_TEST_MODE = enabled
        
        status = "ENABLED 🧪 (100 tickets, 0.1s cooldown)" if enabled else "DISABLED ✅ (Production limits)"
        await interaction.response.send_message(f"📢 Tournament Test Mode is now **{status}**.")

    @app_commands.command(name="match-info", description="Display roster for a specific match.")
    @app_commands.describe(match_num="The Match Number from the bracket (e.g. 189)")
    async def match_info(interaction: discord.Interaction, match_num: int):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff permissions required.", ephemeral=True)
            return

        # Get the Matcherino ID from the active session
        session = await get_active_tourney_session()
        if not session or not session.get("matcherino_id"):
            await interaction.response.send_message("❌ No active Matcherino ID set. Use `/set-matcherino` first.", ephemeral=True)
            return

        await interaction.response.defer()

        m_id = session["matcherino_id"]
        bracket_url = f"https://matcherino.com/tournaments/{m_id}/bracket"

        # If run in a ticket, pass topic team name for fuzzy mismatch check
        topic_team_name = None
        if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.topic:
            team_res = re.search(r"team:(.*?)(?:\||$)", interaction.channel.topic)
            if team_res:
                topic_team_name = team_res.group(1).strip() or None

        match_data = fetch_ticket_context(bracket_url, match_num, topic_team_name=topic_team_name)

        if match_data.get("status") != "success":
            await interaction.followup.send(f"❌ **Error:** {match_data.get('error')}")
            return

        is_mismatch = match_data.get("team_name_mismatch", False)
        best_match_team = match_data.get("team_name_best_match")
        embed = discord.Embed(
            title=f"📊 Matcherino Data: Match #{match_num}",
            color=discord.Color.red() if is_mismatch else discord.Color.gold()
        )

        # Match Status Section
        embed.add_field(name="Match Status", value=f"`{match_data['match_status'].upper()}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        team_a = match_data['team_a']
        team_b = match_data['team_b']

        players_a = "\n".join([f"• {p}" for p in team_a['players']]) or "• *No players found*"
        players_b = "\n".join([f"• {p}" for p in team_b['players']]) or "• *No players found*"

        # Three-Column Layout: Team A | vs | Team B
        embed.add_field(
            name=f"🔵 {team_a['name']} (Score: {team_a['score']})", 
            value=f"**Matcherino Names:**\n{players_a}", 
            inline=True
        )
        embed.add_field(name="⚔️", value="\u200b", inline=True)
        embed.add_field(
            name=f"🔴 {team_b['name']} (Score: {team_b['score']})", 
            value=f"**Matcherino Names:**\n{players_b}", 
            inline=True
        )

        if is_mismatch:
            warning_text = "The team name in this ticket does not closely match either team in the bracket for this match."
            if topic_team_name:
                warning_text += f"\nTeam entered: `{topic_team_name}`"
            warning_text += "\nUse `/set-ticket-match` to correct the match number or team name."

            embed.add_field(
                name="⚠️ Team name / Match number Mismatch",
                value=warning_text,
                inline=False,
            )
        elif topic_team_name and best_match_team:
            embed.add_field(
                name="Detected Team",
                value=f"```\n{best_match_team}\n```",
                inline=False,
            )

        embed.set_footer(text=f"Matcherino ID: {m_id} | Tourney Admin: {interaction.user.name}")
        await interaction.followup.send(embed=embed)
   
    @app_commands.command(name="match-history", description="View the standardized tournament run of teams in a matchup.")
    @app_commands.describe(match_num="The visual match number from the bracket (e.g. 189)")
    async def match_history(interaction: discord.Interaction, match_num: int):
        # 1. Staff Check
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff permissions required.", ephemeral=True)
            return

        # 2. Get Matcherino ID from active session
        session = await get_active_tourney_session()
        if not session or not session.get("matcherino_id"):
            await interaction.response.send_message("❌ No active Matcherino ID set. Use `/set-matcherino` first.", ephemeral=True)
            return

        await interaction.response.defer()

        m_id = session["matcherino_id"]
        bracket_url = f"https://matcherino.com/tournaments/{m_id}/bracket"
        
        # 3. Fetch data using the updated standardized logic in matcherino.py
        data = fetch_ticket_context(bracket_url, match_num)

        if data.get("status") != "success":
            await interaction.followup.send(f"❌ **Error:** {data.get('error')}")
            return

        # 4. Construct the Embed
        embed = discord.Embed(
            title=f"📜 Match History: Match #{match_num}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        team_a_name = data['team_a']['name']
        team_b_name = data['team_b']['name']
        
        # Join history lists with newlines
        hist_a = "\n".join(data.get('team_a_history', []))
        hist_b = "\n".join(data.get('team_b_history', []))

        # Add fields with "First Round" fallback
        embed.add_field(
            name=f"🔵 {team_a_name}", 
            value=hist_a if hist_a else "*No previous matches (First Round)*", 
            inline=False
        )
        embed.add_field(
            name=f"🔴 {team_b_name}", 
            value=hist_b if hist_b else "*No previous matches (First Round)*", 
            inline=False
        )

        embed.set_footer(text=f"Matcherino ID: {m_id}")
        await interaction.followup.send(embed=embed)
        
    @app_commands.command(name="set-ticket-match", description="STAFF ONLY: Update match # or team name for this specific ticket.")
    @app_commands.describe(
        match_num="The correct visual match number (e.g., 42)",
        team_name="The correct Matcherino team name for this ticket"
    )
    async def set_ticket_match(
        interaction: discord.Interaction, 
        match_num: int = None, 
        team_name: str = None
    ):
        # 1. Permission and Channel Validation
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff permissions required.", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or "ticket-" not in channel.name:
            await interaction.response.send_message("❌ This command must be used inside a ticket channel.", ephemeral=True)
            return

        if match_num is None and team_name is None:
            await interaction.response.send_message("⚠️ Provide at least one field to update.", ephemeral=True)
            return

        # Defer so we have time to handle the potential wait
        await interaction.response.defer()

        # 2. Prepare the new Metadata
        topic = channel.topic or ""
        updates = []

        if match_num is not None:
            topic = re.sub(r"bracket:[^|]+", f"bracket:{match_num}", topic) if "bracket:" in topic else f"{topic}|bracket:{match_num}"
            updates.append(f"Match Number: **#{match_num}**")

        if team_name is not None:
            topic = re.sub(r"team:[^|]+", f"team:{team_name}", topic) if "team:" in topic else f"{topic}|team:{team_name}"
            updates.append(f"Team Name: **{team_name}**")

        # 3. Execution with Rate Limit "Kill Switch"
        try:
            # We create a task for the edit so we can cancel it if it hits the 10-minute wall
            edit_task = asyncio.create_task(
                channel.edit(
                    topic=topic,
                    reason=f"Details updated by {interaction.user.name}",
                )
            )
            
            try:
                # Wait only 2 seconds. If Discord is rate-limiting us, this will time out.
                await asyncio.wait_for(asyncio.shield(edit_task), timeout=2.0)
            except asyncio.TimeoutError:
                # STOP the bot from waiting 10 minutes
                edit_task.cancel()
                
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="🚫 Discord Rate Limit Hit",
                        description=(
                            "Discord allows only **2 channel edits every 10 minutes**.\n\n"
                            "The bot has **cancelled** this update to avoid hanging for 10 minutes. "
                            "Please wait a few minutes and try again."
                        ),
                        color=discord.Color.red()
                    )
                )
                return

            # 4. Success Response
            update_list = "\n".join([f"✅ {item}" for item in updates])
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚙️ Ticket Details Adjusted",
                    description=f"Changes applied successfully:\n\n{update_list}\n\n"
                                f"The live scoreboard will update in the next 1-minute cycle.",
                    color=discord.Color.green()
                )
            )

        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update channel: {e}")
            
    @app_commands.command(name="tourney-progress", description="STAFF ONLY: Real-time tournament health check.")
    async def tourney_progress(interaction: discord.Interaction):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        await interaction.response.defer()
        session = await get_active_tourney_session()
        if not session or not session.get("matcherino_id"):
            await interaction.followup.send("❌ No active session found.")
            return

        m_id = session["matcherino_id"]
        bracket_url = f"https://matcherino.com/tournaments/{m_id}/bracket"
        
        from .matcherino import fetch_bracket_progress
        data = fetch_bracket_progress(bracket_url)
        
        if data.get("status") != "success":
            await interaction.followup.send(f"❌ **Error:** {data.get('error')}")
            return

        # Fixed Timezone calculation
        start_time = session['start_time']
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=datetime.timezone.utc)
        duration = discord.utils.utcnow() - start_time
        hours, mins = divmod(int(duration.total_seconds()), 3600)
        mins, _ = divmod(mins, 60)

        embed = discord.Embed(title="📊 Tournament Progress Report", color=discord.Color.gold())
        embed.description = f"**⏱️ Total Duration:** `{hours}h {mins}m` | **📈 Completion:** `{data['completion_pct']}%` ({data['closed']}/{data['total']})"

        # Path to Finals / completion status
        remaining_matches = max(0, data['total'] - data['closed'])
        tournament_complete = data['completion_pct'] >= 100 or remaining_matches == 0

        if tournament_complete:
            path_text = "🏆 **Tournament Over!**"
        else:
            rounds_left = max(0, data['max_round'] - data['dominant_round'])
            path_text = f"{rounds_left} rounds remaining" if rounds_left > 0 else "🏆 **Finals in progress!**"

        active_matches_text = "No matches remaining" if tournament_complete else f"{data['active_count']} Currently Playable"

        embed.add_field(
            name="🏆 Bracket Status",
            value=(
                f"• **Dominant Round:** Round {data['dominant_round']}\n"
                f"• **Path to Finals:** {path_text}\n"
                f"• **Active Matches:** {active_matches_text}"
            ),
            inline=False
        )

        # Bottlenecks (Laggards behind dominant round)
        if data['bottlenecks']:
            bn_text = ""
            for bn in data['bottlenecks'][:5]:
                bn_text += f"**#{bn['id']}** (Round {bn['round']}) | {bn['team_a']} vs {bn['team_b']} ({bn['score_a']}-{bn['score_b']})\n"
            embed.add_field(name="⚠️ Bottleneck Matches", value=bn_text, inline=False)
        else:
            embed.add_field(name="⚠️ Bottleneck Matches", value="✅ All playable matches are current with the dominant round.", inline=False)

        embed.set_footer(text=f"Matcherino ID: {m_id} | Staff: {interaction.user.name}")
        await interaction.followup.send(embed=embed)

        
    # --- Start the Dashboard Task ---
    if bot.get_cog("QueueDashboard") is None:
        asyncio.create_task(bot.add_cog(QueueDashboard(bot)))
        print("✅ Queue Dashboard task started.")
    else:
        print("ℹ️ QueueDashboard already loaded; skipping duplicate add.")

    bot.tree.add_command(tourney_panel)
    bot.tree.add_command(pre_tourney_panel)
    bot.tree.add_command(add_to_ticket)
    bot.tree.add_command(remove_from_ticket)
    bot.tree.add_command(hall_of_fame)
    bot.tree.add_command(payout_add)
    bot.tree.add_command(payout_list)
    bot.tree.add_command(payout_reset)
    bot.tree.add_command(payout_history)
    bot.tree.add_command(check_queue)
    bot.tree.add_command(tourney_admin_help)
    bot.tree.add_command(set_matcherino)
    bot.tree.add_command(tourney_test_mode)
    bot.tree.add_command(match_info)
    bot.tree.add_command(match_history)
    bot.tree.add_command(set_ticket_match)
    bot.tree.add_command(tourney_progress)
    bot.tree.add_command(BlacklistGroup(bot))


    async def background_stats_update():
        try:
            active = await get_active_tourney_session()
            if active:
                await increment_tourney_message_count(active['_id'])
        except Exception:
            pass 

    sticky_redirect_message_ids: dict[int, int] = {}
    sticky_redirect_locks: dict[int, asyncio.Lock] = {}

    async def cleanup_sticky_redirects(guild: discord.Guild):
        """Remove tracked sticky redirect embeds from configured public channels."""
        target_ids = {
            cid for cid in (GENERAL_CHANNEL_ID, BRAWL_CHAT_CHANNEL_ID, TOURNEY_CHAT_CHANNEL_ID)
            if isinstance(cid, int)
        }
        target_names = {"general", "brawl-chat", "tourney-chat"}

        candidate_channels = [
            ch for ch in guild.text_channels
            if ch.id in target_ids or ch.name in target_names
        ]

        for channel in candidate_channels:
            old_msg_id = sticky_redirect_message_ids.pop(channel.id, None)
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

    async def refresh_sticky_redirect(channel: discord.TextChannel, is_sa_tourney: bool):
        """Keep exactly one support redirect embed pinned to the latest chat position."""
        lock = sticky_redirect_locks.setdefault(channel.id, asyncio.Lock())

        async with lock:
            support_channel = bot.get_channel(TOURNEY_SUPPORT_CHANNEL_ID)
            support_mention = support_channel.mention if isinstance(support_channel, discord.TextChannel) else "#tourney-support"

            if is_sa_tourney:
                description = f"# ⚠️ ¡Atención!\n# Por favor, usa {support_mention} para abrir un ticket de soporte para el torneo."
            else:
                description = f"# ⚠️ Attention!\n# Please use {support_mention} to open a support ticket for the tournament."

            embed = discord.Embed(
                description=description,
                color=discord.Color.red()
            )

            # Try deleting the previously tracked sticky message first.
            old_msg_id = sticky_redirect_message_ids.get(channel.id)
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            # Safety cleanup: remove any extra older sticky embeds by this bot.
            async for msg in channel.history(limit=30):
                if msg.author != bot.user or not msg.embeds:
                    continue
                if msg.embeds[0].description == embed.description:
                    try:
                        await msg.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass

            new_msg = await channel.send(embed=embed)
            sticky_redirect_message_ids[channel.id] = new_msg.id

    @bot.listen()
    async def on_message(message):
        if message.author.bot: return
        if not isinstance(message.channel, discord.TextChannel):
            return
        
        valid_categories = (TOURNEY_CATEGORY_ID, PRE_TOURNEY_CATEGORY_ID)
        
        # Check conditions (Fast in-memory checks)
        if "ticket-" in message.channel.name and message.channel.category_id in valid_categories:
            
            # This creates a background task so the bot doesn't wait for MongoDB.
            asyncio.create_task(background_stats_update())

        sticky_channel_ids = {
            cid for cid in (GENERAL_CHANNEL_ID, BRAWL_CHAT_CHANNEL_ID, TOURNEY_CHAT_CHANNEL_ID)
            if isinstance(cid, int)
        }
        sticky_channel_names = {"general", "brawl-chat", "tourney-chat"}

        if sticky_redirect_state["enabled"] and (
            message.channel.id in sticky_channel_ids or message.channel.name in sticky_channel_names
        ):
            is_sa_tourney = sticky_redirect_state.get("region") == "SA"
            asyncio.create_task(refresh_sticky_redirect(message.channel, is_sa_tourney))