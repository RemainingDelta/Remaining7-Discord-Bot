import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from deep_translator import GoogleTranslator
from langdetect import detect, LangDetectException
from typing import List

# Complete dictionary of 55 languages
LANG_MAP = {
    'af': 'Afrikaans', 'ar': 'Arabic', 'bg': 'Bulgarian', 'bn': 'Bengali',
    'ca': 'Catalan', 'cs': 'Czech', 'cy': 'Welsh', 'da': 'Danish',
    'de': 'German', 'el': 'Greek', 'en': 'English', 'es': 'Spanish',
    'et': 'Estonian', 'fa': 'Persian', 'fi': 'Finnish', 'fr': 'French',
    'gu': 'Gujarati', 'he': 'Hebrew', 'hi': 'Hindi', 'hr': 'Croatian',
    'hu': 'Hungarian', 'id': 'Indonesian', 'it': 'Italian', 'ja': 'Japanese',
    'kn': 'Kannada', 'ko': 'Korean', 'lt': 'Lithuanian', 'lv': 'Latvian',
    'mk': 'Macedonian', 'ml': 'Malayalam', 'mr': 'Marathi', 'ne': 'Nepali',
    'nl': 'Dutch', 'no': 'Norwegian', 'pa': 'Punjabi', 'pl': 'Polish',
    'pt': 'Portuguese', 'ro': 'Romanian', 'ru': 'Russian', 'sk': 'Slovak',
    'sl': 'Slovenian', 'sq': 'Albanian', 'sv': 'Swedish', 'sw': 'Swahili',
    'ta': 'Tamil', 'te': 'Telugu', 'th': 'Thai', 'tl': 'Tagalog',
    'tr': 'Turkish', 'uk': 'Ukrainian', 'ur': 'Urdu', 'vi': 'Vietnamese',
    'zh-cn': 'Simplified Chinese', 'zh-tw': 'Traditional Chinese'
}

class Translation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- AUTOCOMPLETE HANDLER ---
    async def language_autocomplete(
        self, 
        interaction: discord.Interaction, 
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Filters the 55 languages based on user input."""
        choices = [
            app_commands.Choice(name=name, value=code)
            for code, name in LANG_MAP.items()
            if current.lower() in name.lower()
        ]
        # Discord only allows returning up to 25 choices at a time
        return choices[:25]
    
    def get_language_code(self, user_input: str) -> str:
        """Matches user input to a language code from LANG_MAP."""
        user_input = user_input.lower().strip()
        
        # Check if they provided the code directly (e.g., 'es')
        if user_input in LANG_MAP:
            return user_input
            
        # Check if they provided the full name (e.g., 'spanish')
        for code, name in LANG_MAP.items():
            if name.lower() == user_input:
                return code
        
        return None

    # --- PREFIX COMMAND (!translate) ---
    @commands.command(name="translate", aliases=["t"])
    async def translate_prefix(self, ctx: commands.Context, source_input: str = None):
        if not ctx.message.reference:
            await ctx.reply("❌ Please reply to a message to translate it.")
            return

        try:
            original_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        except:
            await ctx.reply("❌ Could not find the message.")
            return

        text = original_msg.content.strip()
        if not text:
            await ctx.reply("❌ No text to translate.")
            return

        # Handle Source Language Selection
        source_code = "auto" # Default to auto-detect
        display_name = "Auto-Detected"

        if source_input:
            # Try to match user input (e.g., "hindi" or "hi") to our LANG_MAP
            match_code = self.get_language_code(source_input)
            if match_code:
                source_code = match_code
                display_name = LANG_MAP[match_code]
            else:
                await ctx.reply(f"❌ Unknown language: `{source_input}`. Try something like `hindi` or `es`.")
                return

        try:
            # If auto-detecting, we still want to know what it found for the embed title
            if source_code == "auto":
                detected_code = await asyncio.to_thread(detect, text)
                display_name = LANG_MAP.get(detected_code, detected_code.upper())

            translated = await asyncio.to_thread(
                GoogleTranslator(source=source_code, target='en').translate, 
                text
            )
            
            embed = discord.Embed(title=f"🌐 Translated from {display_name}", color=discord.Color.blue())
            
            # Add a small note if it was forced manually
            if source_input:
                embed.set_author(name="Manual Language Override")

            embed.add_field(name="Original Message", value=f"> {text}", inline=False)
            embed.add_field(name="English Translation", value=f"**{translated}**", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
            await ctx.reply(embed=embed)
        except Exception as e:
            await ctx.reply(f"❌ Error: {e}")

    # --- SLASH COMMAND (/translate) ---
    @app_commands.command(name="translate", description="Translate English text into another language.")
    @app_commands.describe(
        language="Search and select the language to translate INTO",
        phrase="The English text you want to translate"
    )
    @app_commands.autocomplete(language=language_autocomplete)
    async def translate_slash(self, interaction: discord.Interaction, language: str, phrase: str):
        await interaction.response.defer()
        
        try:
            # Check if the code provided exists in our map
            target_lang_name = LANG_MAP.get(language, language.upper())
            
            translated = await asyncio.to_thread(
                GoogleTranslator(source='en', target=language).translate, 
                phrase
            )

            embed = discord.Embed(
                title=f"🌐 Translated to {target_lang_name}",
                color=discord.Color.green()
            )
            embed.add_field(name=f"{target_lang_name} Translation", value=f"**{translated}**", inline=False)
            embed.add_field(name="Original English", value=f"> {phrase}", inline=False)
            
            embed.set_footer(
                text=f"Requested by {interaction.user.display_name}", 
                icon_url=interaction.user.display_avatar.url
            )
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: `{e}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Translation(bot))