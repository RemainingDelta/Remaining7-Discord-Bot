import datetime
import re
import zoneinfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database.mongo import get_setting, set_setting
from features.config import (
    ALLOWED_STAFF_ROLES,
    TOURNEY_REPORT_CHANNEL_ID,
)

# Settings key recording the "YYYY-MM" of the last month a report was generated for.
# Gates the scheduled run so it's idempotent, and lets a cold-boot catch-up detect a
# run missed because the bot was down at 06:00 UTC on the 1st (a time= loop silently
# skips missed firings — no back-fill).
LAST_MONTHLY_REPORT_KEY = "last_monthly_report_month"


def is_staff(member: discord.Member) -> bool:
    return any(role.id in ALLOWED_STAFF_ROLES for role in member.roles)


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _month_range(year: int, month: int) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
    ny, nm = (year, month + 1) if month < 12 else (year + 1, 1)
    end = datetime.datetime(ny, nm, 1, tzinfo=datetime.timezone.utc)
    return start, end


def _parse_tourney_date(date_str: str) -> datetime.datetime | None:
    for fmt in (
        "%B %d, %Y",
        "%B %dst, %Y",
        "%B %dnd, %Y",
        "%B %drd, %Y",
        "%B %dth, %Y",
    ):
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt).replace(
                tzinfo=datetime.timezone.utc
            )
        except ValueError:
            continue
    return None


async def _run_monthly_report(
    bot: commands.Bot,
    year: int,
    month: int,
    *,
    status_cb=None,
) -> str:
    """
    Core logic for generating a monthly tournament report.

    Reads #tourney-reports for per-tourney embeds whose Tournament Date falls
    in the given month/year. Aggregates and posts a combined embed to the same
    channel.

    status_cb: optional async callable(str) for streaming progress to a slash command.
    Returns a summary string on success, or raises ValueError with an error message.
    """

    async def status(msg: str):
        print(msg)
        if status_cb:
            await status_cb(msg)

    month_label = datetime.datetime(year, month, 1).strftime("%B %Y")
    start_dt, end_dt = _month_range(year, month)

    report_channel = bot.get_channel(TOURNEY_REPORT_CHANNEL_ID)
    if not report_channel:
        raise ValueError(
            "⚠️ `TOURNEY_REPORT_CHANNEL_ID` not found — update it in `config.py`."
        )

    await status(f"🔍 Scanning {report_channel.mention} for **{month_label}**...")

    total_tickets = 0
    total_messages = 0
    peak_queues: list[int] = []
    staff_totals: dict[str, int] = {}
    tourney_count = 0
    parse_warnings: list[str] = []

    async for msg in report_channel.history(limit=1000):
        if msg.author.id != bot.user.id:
            continue
        for embed in msg.embeds:
            # Skip monthly rollup embeds to avoid double-counting
            if embed.title and "Monthly Tournament Report" in embed.title:
                continue

            date_field = next(
                (f for f in embed.fields if "Tournament Date" in f.name), None
            )
            if not date_field:
                continue

            parsed = _parse_tourney_date(date_field.value)
            if not parsed:
                parse_warnings.append(
                    f"⚠️ Could not parse date `{date_field.value}` "
                    f"from embed posted {msg.created_at.strftime('%Y-%m-%d')} — skipped."
                )
                continue

            if not (start_dt <= parsed < end_dt):
                continue

            tourney_count += 1

            for field in embed.fields:
                name = field.name
                val = field.value
                if "Total Tickets" in name:
                    m = re.search(r"\d+", val)
                    if m:
                        total_tickets += int(m.group())
                elif "Total Messages" in name:
                    m = re.search(r"\d+", val)
                    if m:
                        total_messages += int(m.group())
                elif "Peak Queue" in name:
                    m = re.search(r"\d+", val)
                    if m:
                        peak_queues.append(int(m.group()))
                elif "Top Tourney Admins" in name:
                    for user_id, count in re.findall(r"<@(\d+)>: (\d+) tickets", val):
                        staff_totals[user_id] = staff_totals.get(user_id, 0) + int(
                            count
                        )

    for warning in parse_warnings:
        await status(warning)

    if tourney_count == 0:
        return (
            f"📊 No tournaments found in **{month_label}**. "
            f"If reports exist for this month, ensure they include a **📅 Tournament Date** field."
        )

    avg_peak = round(sum(peak_queues) / len(peak_queues), 1) if peak_queues else 0

    sorted_staff = sorted(staff_totals.items(), key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    staff_lines = []
    for i, (user_id, count) in enumerate(sorted_staff[:12]):
        icon = medals[i] if i < 3 else f"**{i + 1}.**"
        staff_lines.append(f"{icon} <@{user_id}>: {count} tickets")
    staff_msg = "\n".join(staff_lines) if staff_lines else "No tickets closed."

    embed = discord.Embed(
        title=f"📅 Monthly Tournament Report — {month_label}",
        color=discord.Color.purple(),
    )
    embed.add_field(name="🏆 Tournaments", value=f"`{tourney_count}`", inline=True)
    embed.add_field(name="📩 Total Tickets", value=f"`{total_tickets}`", inline=True)
    embed.add_field(name="💬 Total Messages", value=f"`{total_messages}`", inline=True)
    embed.add_field(
        name="📈 Avg Peak Queue", value=f"`{avg_peak}` tickets", inline=True
    )
    embed.add_field(name="🏆 Top Tourney Admins", value=staff_msg, inline=False)

    await report_channel.send(embed=embed)
    return (
        f"✅ Monthly report for **{month_label}** posted — "
        f"{tourney_count} tournament(s), {total_tickets} total tickets."
    )


class TourneyReports(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.monthly_report_task.start()
        self.monthly_report_catchup_task.start()

    def cog_unload(self):
        self.monthly_report_task.cancel()
        self.monthly_report_catchup_task.cancel()

    async def _maybe_run_monthly_report(self):
        """Generate the previous month's report unless it's already been recorded.

        Idempotent via LAST_MONTHLY_REPORT_KEY, so the daily 06:00 firing runs it at
        most once per month and — crucially — a firing on any day after downtime that
        spanned the 1st still catches the missed month. Only stamps on success; a
        ValueError (e.g. report channel missing) or unexpected error leaves the marker
        unset so the next firing or boot retries.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        py, pm = _prev_month(now.year, now.month)
        target_key = f"{py:04d}-{pm:02d}"
        if await get_setting(LAST_MONTHLY_REPORT_KEY) == target_key:
            return

        try:
            result = await _run_monthly_report(self.bot, py, pm)
            print(f"✅ Auto monthly report: {result}")
            await set_setting(LAST_MONTHLY_REPORT_KEY, target_key)
        except ValueError as e:
            print(f"❌ Auto monthly report failed (will retry): {e}")
        except Exception as e:
            print(f"❌ Auto monthly report unexpected error (will retry): {e}")

    # ⚠️ FOR TESTING: Change to @tasks.loop(seconds=30)
    @tasks.loop(time=datetime.time(hour=6, minute=0, tzinfo=zoneinfo.ZoneInfo("UTC")))
    async def monthly_report_task(self):
        if not self.bot.is_ready():
            return
        await self._maybe_run_monthly_report()

    # Cold-boot catch-up: a time= loop only fires at the next matching wall-clock
    # instant, so a bot down at 06:00 UTC on the 1st silently loses that month's run.
    @tasks.loop(count=1)
    async def monthly_report_catchup_task(self):
        await self.bot.wait_until_ready()
        try:
            await self._maybe_run_monthly_report()
        except Exception as e:
            print(f"❌ Monthly report catch-up failed: {e}")

    @app_commands.command(
        name="monthly-report",
        description="STAFF ONLY: Generate (or re-generate) a monthly tournament report.",
    )
    @app_commands.describe(
        month="Month number (1–12). Defaults to last month.",
        year="4-digit year. Defaults to the year of last month.",
    )
    async def monthly_report_cmd(
        self,
        interaction: discord.Interaction,
        month: int | None = None,
        year: int | None = None,
    ):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return

        if month is not None and not (1 <= month <= 12):
            await interaction.response.send_message(
                "❌ Month must be between 1 and 12.", ephemeral=True
            )
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        if month is None or year is None:
            py, pm = _prev_month(now.year, now.month)
            month = month if month is not None else pm
            year = year if year is not None else py

        await interaction.response.defer(ephemeral=True)

        messages: list[str] = []

        async def status_cb(msg: str):
            messages.append(msg)
            await interaction.edit_original_response(content="\n".join(messages))

        try:
            result = await _run_monthly_report(
                self.bot, year, month, status_cb=status_cb
            )
            messages.append(result)
        except ValueError as e:
            messages.append(str(e))
        except Exception as e:
            messages.append(f"❌ Unexpected error: {e}")

        await interaction.edit_original_response(content="\n".join(messages))


async def setup(bot: commands.Bot):
    await bot.add_cog(TourneyReports(bot))
