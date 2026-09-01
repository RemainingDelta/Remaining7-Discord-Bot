import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from features.config import (
    ADMIN_ROLE_ID,
    BOOSTER_CHANNEL_ID,
    BOT_VERSION,
    GENERAL_CHANNEL_ID,
    MODERATOR_ROLE_ID,
)


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all available bot commands.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"🤖 **R7 Bot Command Directory | {BOT_VERSION}**",
            description=(
                "Here is a list of all the commands you can use in the server!\n\n"
                "💡 **Want to know how to get tokens?**\n"
                "Use `/economy-help` for a full guide on earning and spending."
            ),
            color=discord.Color.blurple(),
        )

        economy_text = (
            "`/balance` - View your token total\n"
            "`/daily` - Claim daily tokens & check progress\n"
            "`/quests` - View active daily and weekly quests\n"
            "`/leaderboard token` - See top token holders\n"
            "`/level` - Check your rank & XP progress\n"
            "`/leaderboard level` - See top server levels\n"
            "`/shop` - Browse the token store\n"
            "`/buy` - Purchase an item from the shop\n"
            "`/redeem` - Claim your purchased rewards\n"
            "`/check-budget` - See remaining monthly reward budget\n"
            "`/redemption-queue` - View your queued redemptions"
        )
        embed.add_field(name="💰 Economy", value=economy_text, inline=False)

        brawler_text = (
            "`/profile` - View your profile, collection progress, and currencies\n"
            "`/brawlers` - View your owned brawlers and their levels\n"
            "`/brawler` - View full details for a specific brawler\n"
            "`/buy-brawler` - Purchase new brawlers using Credits\n"
            "`/upgrade` - Level up your brawlers\n"
            "`/buy-ability` - Buy Gadgets, Star Powers, and Hypercharges\n"
            "`/megabox` - Open a Mega Box\n"
            "`/starrdrop` - Open a random Starr Drop"
        )
        embed.add_field(
            name="🥊 Brawlers Collectible Minigame", value=brawler_text, inline=False
        )

        tourney_text = (
            "`/queue` - Check your position in the support ticket line\n"
            "*(Note: This command only works inside an active tournament ticket)*"
        )
        embed.add_field(name="🎟️ Tournaments", value=tourney_text, inline=False)

        translation_text = (
            "`!t [language]` - Reply to a message to translate it into English (e.g., `!t spanish`)\n"
            "`/translate` - Translate your English text into 53 other languages"
        )
        embed.add_field(name="🌐 Translation", value=translation_text, inline=False)

        counting_text = (
            "Type the next number in the counting channel — a plain number or a "
            "simple math expression like `7*10` both count!\n"
            "*(Off-sequence, repeat-user, or invalid messages are removed; the count keeps going)*"
        )
        embed.add_field(name="🔢 Counting Game", value=counting_text, inline=False)

        story_text = (
            "Build a story one word per message in the story channel while it's active!\n"
            "`/story-see` - View the story so far\n"
            "*(One word per message — no spaces, emojis, or banned words, and you can't go twice in a row)*"
        )
        embed.add_field(name="📖 One-Word Story", value=story_text, inline=False)

        utility_text = (
            "`/booster-perks` - View all Server Booster perks\n"
            "`/convert-time` - Convert a date and time to Discord timestamp formats\n"
            "`/version` - View the bot's current version\n"
            "`/privacy-policy` - See what data the bot stores about you and why"
        )
        embed.add_field(name="🔧 Utility", value=utility_text, inline=False)

        embed.set_footer(text="Staff & Admin commands are hidden from this list.")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="mod-help",
        description="STAFF ONLY: Guide for Moderator economy and security tools.",
    )
    async def mod_help(self, interaction: discord.Interaction):
        # Local Permission Check
        user_role_ids = [role.id for role in interaction.user.roles]
        if not (ADMIN_ROLE_ID in user_role_ids or MODERATOR_ROLE_ID in user_role_ids):
            await interaction.response.send_message(
                "❌ Permission Denied: This command is for Staff only.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🛡️ Moderator Guide | {BOT_VERSION}",
            description="Quick-reference for managing the R7 economy and server security protocols.",
            color=discord.Color.dark_blue(),
        )

        # Economy Oversight
        economy_text = (
            "`/give <user> <type> <amount>` - Manually grant Tokens, XP, or Levels.\n"
            "`/set-balance <user> <amount>` - Directly set a user's token balance.\n"
            "`/redemption-queue-list` - View queued redemptions awaiting budget.\n"
            "`/redemption-queue-remove <entry_id>` - Remove a queued redemption."
        )
        embed.add_field(name="💰 Economy Oversight", value=economy_text, inline=False)

        # Security Protocol
        security_text = (
            "`/hacked <user>` - Times out a user and purges recent messages.\n"
            "`!hacked` (Prefix) - Reply to a message with this to trigger the protocol.\n"
            "`/unhacked <user>` - Removes hacked flag and clears timeout.\n"
            "`/hacked-list` - View all users currently flagged as compromised."
        )
        embed.add_field(name="🚨 Security Protocol", value=security_text, inline=False)

        # Scam Image Detection
        scam_text = (
            "Images are auto-scanned against the scam blacklist — matches are deleted, "
            "the poster gets a 10-min timeout, and an alert with Confirm/Dismiss buttons is posted in mod-logs.\n"
            "`!scam-add` - Reply to an image (or attach one) to blacklist it.\n"
            "`!scam-remove <md5> [md5 ...]` - Remove entries by MD5 prefix.\n"
            "`!scam-list` - View all blacklisted images.\n"
            "`!scam-rename <md5> <name>` - Give an entry a readable name.\n"
            "`!scam-test` - Dry-run detection on an image (no action taken)."
        )
        embed.add_field(name="🖼️ Scam Image Detection", value=scam_text, inline=False)

        # Server Tools
        tools_text = (
            "`/set-count <number>` - Manually set the current count in the counting channel.\n"
            "`!sticky <message>` - Pin a message that reposts whenever others send in that channel.\n"
            "`!unsticky` - Remove the active sticky message from a channel."
        )
        embed.add_field(name="🔧 Server Tools", value=tools_text, inline=False)

        story_text = (
            "`/story-start` - Open a new story (activates the channel).\n"
            "`/story-end` - Publish, archive & close the current story.\n"
            "`/story-reset` - Silently archive & clear the story.\n"
            "`/story-banword add|remove|list` - Manage banned words.\n"
            "`/story-banchar add|remove|list` - Manage banned characters."
        )
        embed.add_field(name="📖 One-Word Story", value=story_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin-help",
        description="ADMIN ONLY: Master reference for high-level bot management.",
    )
    async def admin_help(self, interaction: discord.Interaction):
        # 1. Strict Permission Check (Admins Only)
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ Access Denied: This command is restricted to Administrators.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"👑 Admin Command Manual | {BOT_VERSION}",
            description="Centralized reference for the most powerful bot functions and financial overrides.",
            color=discord.Color.from_rgb(255, 0, 0),  # Bold Red for Admin
        )

        # --- Economy Management ---
        economy_text = (
            "`/drop <amount>` - Manual supply drop in general.\n"
            "`/give <user> <tokens/xp> <amount>` - Grant resources.\n"
            "`/set-balance <user> <amount>` - Hard reset of a user's tokens.\n"
            "`/set-budget <amount>` - Override the monthly reward budget.\n"
            "`/perm <user> <add/remove>` - Manage bot command access."
        )
        embed.add_field(name="💰 Economy Management", value=economy_text, inline=False)

        # --- Event Operations ---
        event_text = (
            "`/event-rewards <message_id>` - Process token distribution from an announcement message.\n"
            "`/poll-rewards <message_id> <answer> <amount>` - Distribute tokens to users who voted a given answer.\n"
            "`/check-stuck-payouts [resolve]` - List (or resolve) event payouts claimed but never confirmed paid.\n"
            "*(Requires formatting: @User 500 for event-rewards)*"
        )
        embed.add_field(name="🏆 Event Operations", value=event_text, inline=False)

        # --- Security & Hacked Protocol ---
        security_text = (
            "`/hacked <user>` - 7-day timeout + global message purge.\n"
            "`/unhacked <user>` - Recover account (clear timeout/flag).\n"
            "`/hacked-list` - View all currently compromised accounts."
        )
        embed.add_field(
            name="🚨 Security & Hacked Protocol", value=security_text, inline=False
        )

        # --- Tournament & Financials ---
        tourney_text = (
            "`/blacklist <add/remove/list>` - Manage tournament-banned users.\n"
            "`/payout-add` - Record group payouts for staff treasury.\n"
            "`/payout-list` - View all pending staff payout totals.\n"
            "`/payout-history` - View audit logs of group payouts.\n"
            "`/payout-reset` - Clear receipts and cash out staff treasury."
        )
        embed.add_field(
            name="⚔️ Tournament & Financials", value=tourney_text, inline=False
        )

        # --- Quest Management ---
        quest_text = "`/reset-quests <user>` - Force-reset a user's quest assignments."
        embed.add_field(name="📜 Quest Management", value=quest_text, inline=False)

        # Ephemeral = True ensures only the Admin sees this menu
        await interaction.response.send_message(embed=embed, ephemeral=True)

    TIMEZONE_ALIASES: dict[str, str] = {
        "ET": "America/New_York",
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "CT": "America/Chicago",
        "CST": "America/Chicago",
        "CDT": "America/Chicago",
        "MT": "America/Denver",
        "MST": "America/Denver",
        "MDT": "America/Denver",
        "PT": "America/Los_Angeles",
        "PST": "America/Los_Angeles",
        "PDT": "America/Los_Angeles",
        "GMT": "Europe/London",
        "BST": "Europe/London",
        "UTC": "UTC",
        "CET": "Europe/Berlin",
        "CEST": "Europe/Berlin",
        "IST": "Asia/Kolkata",
        "JST": "Asia/Tokyo",
        "AEST": "Australia/Sydney",
        "AEDT": "Australia/Sydney",
        "BRT": "America/Sao_Paulo",
    }

    # NOTE: Keep this embed in sync with the actual perks — update it whenever a
    # booster perk is added, modified, or removed anywhere in the bot.
    @app_commands.command(
        name="booster-perks",
        description="View all perks for Server Boosters.",
    )
    async def booster_perks(self, interaction: discord.Interaction):
        general_ch = f"<#{GENERAL_CHANNEL_ID}>"
        booster_ch = f"<#{BOOSTER_CHANNEL_ID}>"

        perks_text = (
            "Boost the server to unlock all of the perks below. "
            "Thank you for supporting R7! 💖\n\n"
            f"🔓 **Exclusive Channel:** Access to {booster_ch} — supply-drop crates "
            "(**10-25 tokens**) land there every ~2 hours on average, first to click claims it.\n"
            f"💰 **Token Bonus:** ~10% more tokens on average in {general_ch} and the booster channel.\n"
            f"✨ **XP Bonus:** 35% chance of +1 bonus XP per message in {general_ch} and the booster channel.\n"
            "📅 **Daily Bonus:** Flat **+20 tokens** on every `/daily` claim.\n"
            "📜 **Easier Quests:** Daily/weekly quest targets reduced by **20%** "
            "*(applies from your next quest cycle after boosting)*.\n"
            "📣 **Booster Shoutout:** A private ticket opens when you boost — write a message "
            "for staff to review and feature in announcements once approved "
            "*(self-promo and similar are not allowed)*. *(Once per calendar month.)*\n"
            "🛒 **Shop Discount:** **10% off** one shop purchase per calendar month via `/buy` "
            "*(unlocks after **14+ consecutive days** of boosting)*."
        )

        embed = discord.Embed(
            title="🚀 **Server Booster Perks**",
            description=perks_text,
            color=discord.Color.fuchsia(),
        )

        embed.set_footer(text="Perks apply while your boost is active.")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="version", description="View the bot's current version.")
    async def version(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description=f"🤖 R7 Bot is running\n# {BOT_VERSION}",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="convert-time",
        description="Convert a date and time to all Discord timestamp formats.",
    )
    @app_commands.describe(
        date="Date in YYYY-MM-DD format (e.g. 2026-03-27)",
        time="Time in H:MM AM/PM format (e.g. 8:13 PM)",
        timezone="Timezone abbreviation (e.g. EST, PT) or IANA name (e.g. America/New_York)",
    )
    async def convert_time(
        self,
        interaction: discord.Interaction,
        date: str,
        time: str,
        timezone: str,
    ):
        tz_key = self.TIMEZONE_ALIASES.get(timezone.upper(), timezone)
        try:
            tz = ZoneInfo(tz_key)
        except (ZoneInfoNotFoundError, KeyError):
            await interaction.response.send_message(
                f"❌ Invalid timezone: `{timezone}`. Use an abbreviation like `EST`, `PT`, `GMT` or an IANA timezone like `America/New_York`.",
                ephemeral=True,
            )
            return

        try:
            dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %I:%M %p")
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid date or time. Use `YYYY-MM-DD` for date and `H:MM AM/PM` for time (e.g. `2026-03-27` and `8:13 PM`).",
                ephemeral=True,
            )
            return

        dt = dt.replace(tzinfo=tz)
        unix = int(dt.timestamp())

        formats = [
            ("F", "Full Date & Time"),
            ("f", "Short Date & Time"),
            ("D", "Full Date"),
            ("d", "Short Date"),
            ("T", "Full Time"),
            ("t", "Short Time"),
            ("R", "Relative"),
        ]

        lines = []
        for fmt, label in formats:
            raw = f"<t:{unix}:{fmt}>"
            lines.append(f"**{label}**\n`{raw}` → {raw}")

        embed = discord.Embed(
            title="Discord Timestamps",
            description="\n\n".join(lines),
            color=discord.Color.blurple(),
        )
        footer = f"Unix: {unix} | {tz_key}"
        if timezone.upper() != tz_key:
            footer += f" (from {timezone.upper()})"
        embed.set_footer(text=footer)

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(General(bot))
