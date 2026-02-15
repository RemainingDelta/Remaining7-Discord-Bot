import discord
from discord import app_commands
from discord.ext import commands

from features.config import ADMIN_ROLE_ID, MODERATOR_ROLE_ID, BOT_VERSION

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="View all available bot commands.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            # 2. Add it right to the title!
            title=f"🤖 **R7 Bot Command Directory | {BOT_VERSION}**", 
            description=(
                "Here is a list of all the commands you can use in the server!\n\n"
                "💡 **Want to know how to get tokens?**\n"
                "Use `/economy_help` for a full guide on earning and spending."
            ),
            color=discord.Color.blurple()
        )

        economy_text = (
            "`/balance` - View your token total\n"
            "`/daily` - Claim daily tokens & check progress\n"
            "`/quests` - View active daily and weekly quests\n"
            "`/leaderboard` - See top token holders\n"
            "`/level` - Check your rank & XP progress\n"
            "`/levels_leaderboard` - See top server levels\n"
            "`/shop` - Browse the token store\n"
            "`/buy` - Purchase an item from the shop\n"
            "`/redeem` - Claim your purchased rewards\n"
            "`/checkbudget` - See remaining monthly reward budget"
        )
        embed.add_field(name="💰 Economy", value=economy_text, inline=False)

        brawler_text = (
            "`/profile` - View your profile, collection progress, and currencies\n"
            "`/brawlers` - View your owned brawlers and their levels\n"
            "`/buy_brawler` - Purchase new brawlers using Credits\n"
            "`/upgrade` - Level up your brawlers\n"
            "`/buy_ability` - Buy Gadgets, Star Powers, and Hypercharges\n"
            "`/megabox` - Open a Mega Box\n"
            "`/starrdrop` - Open a random Starr Drop"
        )
        embed.add_field(name="🥊 Brawlers Collectible Minigame", value=brawler_text, inline=False)
        
        tourney_text = (
            "`/queue` - Check your position in the support ticket line\n"
            "*(Note: This command only works inside an active tournament ticket)*"
        )
        embed.add_field(name="🎟️ Tournaments", value=tourney_text, inline=False)
        
        translation_text = (
            "`!t [language]` - Reply to a message to translate it into English (e.g., `!t spanish`)\n"
            "`/translate` - Translate your English text into 55 other languages"
        )
        embed.add_field(name="🌐 Translation", value=translation_text, inline=False)

        embed.set_footer(text="Staff & Admin commands are hidden from this list.")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="mod-help", description="STAFF ONLY: Guide for Moderator economy and security tools.")
    async def mod_help(self, interaction: discord.Interaction):
        # Local Permission Check
        user_role_ids = [role.id for role in interaction.user.roles]
        if not (ADMIN_ROLE_ID in user_role_ids or MODERATOR_ROLE_ID in user_role_ids):
            await interaction.response.send_message("❌ Permission Denied: This command is for Staff only.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🛡️ Moderator Guide | {BOT_VERSION}",
            description="Quick-reference for managing the R7 economy and server security protocols.",
            color=discord.Color.dark_blue()
        )

        # Economy Oversight
        economy_text = (
            "`/give <user> <type> <amount>` - Manually grant Tokens, XP, or Levels.\n"
            "`/set-balance <user> <amount>` - Directly set a user's token balance."
        )
        embed.add_field(name="💰 Economy Oversight", value=economy_text, inline=False)

        # Security Protocol
        security_text = (
            "`/hacked <user> [days]` - Times out a user and purges recent messages.\n"
            "`!hacked` (Prefix) - Reply to a message with this to trigger the protocol.\n"
            "`/unhacked <user>` - Removes hacked flag and clears timeout.\n"
            "`/hacked-list` - View all users currently flagged as compromised."
        )
        embed.add_field(name="🚨 Security Protocol", value=security_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @app_commands.command(name="admin-help", description="ADMIN ONLY: Master reference for high-level bot management.")
    async def admin_help(self, interaction: discord.Interaction):
        # 1. Strict Permission Check (Admins Only)
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ Access Denied: This command is restricted to Administrators.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"👑 Admin Command Manual | {BOT_VERSION}",
            description="Centralized reference for the most powerful bot functions and financial overrides.",
            color=discord.Color.from_rgb(255, 0, 0) # Bold Red for Admin
        )

        # --- Economy Management ---
        economy_text = (
            "`/drop <amount>` - Manual supply drop in general.\n"
            "`/give <user> <tokens/xp> <amount>` - Grant resources.\n"
            "`/set-balance <user> <amount>` - Hard reset of a user's tokens.\n"
            "`/perm <add/remove> <user>` - Manage bot command access."
        )
        embed.add_field(name="💰 Economy Management", value=economy_text, inline=False)

        # --- Event Operations ---
        event_text = (
            "`/event-rewards <msg_id>` - Process token distribution from an announcement message.\n"
            "*(Requires formatting: @User 500)*"
        )
        embed.add_field(name="🏆 Event Operations", value=event_text, inline=False)

        # --- Security & Hacked Protocol ---
        security_text = (
            "`/hacked <user> [days]` - 7-day timeout + global message purge.\n"
            "`/unhacked <user>` - Recover account (clear timeout/flag).\n"
            "`/hacked-list` - View all currently compromised accounts."
        )
        embed.add_field(name="🚨 Security & Hacked Protocol", value=security_text, inline=False)

        # --- Tournament & Financials ---
        tourney_text = (
            "`/blacklist <add/remove/list>` - Manage tournament-banned users.\n"
            "`/payout-add` - Record group payouts for staff treasury.\n"
            "`/payout-list` - View all pending staff payout totals.\n"
            "`/payout-history` - View audit logs of group payouts.\n"
            "`/payout-reset` - Clear receipts and cash out staff treasury."
        )
        embed.add_field(name="⚔️ Tournament & Financials", value=tourney_text, inline=False)


        # Ephemeral = True ensures only the Admin sees this menu
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))