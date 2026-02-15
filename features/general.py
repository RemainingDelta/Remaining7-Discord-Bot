import discord
from discord import app_commands
from discord.ext import commands

from features.config import BOT_VERSION 

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

async def setup(bot):
    await bot.add_cog(General(bot))