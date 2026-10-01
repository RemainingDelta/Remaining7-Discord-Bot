import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from langdetect import detect
from typing import List

from features import translate_client

# Complete dictionary of 55 languages
LANG_MAP = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sq": "Albanian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
}

BUSY_MESSAGE = (
    "⚠️ The translation service is busy right now. Please try again in a minute."
)


def build_translation_embed(
    text: str,
    translated: str,
    source_name: str,
    requester: discord.abc.User,
    override: bool = False,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🌐 Translated from {source_name}", color=discord.Color.blue()
    )
    if override:
        embed.set_author(name="Manual Language Override")
    embed.add_field(name="Original Message", value=f"> {text}", inline=False)
    embed.add_field(name="English Translation", value=f"**{translated}**", inline=False)
    embed.set_footer(
        text=f"Requested by {requester.display_name}",
        icon_url=requester.display_avatar.url,
    )
    return embed


class SourceLanguageModal(discord.ui.Modal, title="Wrong language?"):
    language = discord.ui.TextInput(
        label="Language the message is written in",
        placeholder="e.g. hindi or hi",
        max_length=30,
    )

    def __init__(self, view: "TranslateResultView"):
        super().__init__()
        self.result_view = view

    async def on_submit(self, interaction: discord.Interaction):
        view = self.result_view
        code = view.cog.get_language_code(self.language.value)
        if code is None:
            await interaction.response.send_message(
                f"❌ Unknown language: `{self.language.value}`. Try something like `hindi` or `es`.",
                ephemeral=True,
            )
            return

        # The shared client can wait on throttling and retries.
        await interaction.response.defer()
        try:
            translated = await translate_client.translate(
                view.text, source=code, target="en"
            )
        except translate_client.TranslationUnavailable:
            await interaction.followup.send(BUSY_MESSAGE, ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            return

        embed = build_translation_embed(
            view.text, translated, LANG_MAP[code], interaction.user, override=True
        )
        await interaction.edit_original_response(embed=embed, view=view)


class TranslateResultView(discord.ui.View):
    """Lets the requester correct a misdetected source language (was `!t <language>`)."""

    def __init__(self, cog: "Translation", text: str, requester_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.text = text
        self.requester_id = requester_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "❌ Only the person who asked for this translation can change its language.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Wrong language?", style=discord.ButtonStyle.secondary)
    async def wrong_language(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(SourceLanguageModal(self))


class Translation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Context menus can't be declared as cog methods, so the "Translate"
        # message command is built here and registered on the tree in cog_load.
        self.translate_menu = app_commands.ContextMenu(
            name="Translate", callback=self.translate_message
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.translate_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.translate_menu.name, type=self.translate_menu.type
        )

    # --- AUTOCOMPLETE HANDLER ---
    async def language_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Filters the 55 languages based on user input."""
        choices = [
            app_commands.Choice(name=name, value=code)
            for code, name in LANG_MAP.items()
            if current.lower() in name.lower()
        ]
        # Discord only allows returning up to 25 choices at a time
        return choices[:25]

    def get_language_code(self, user_input: str) -> str | None:
        """Matches a language name or code (e.g. 'hindi' or 'hi') to a LANG_MAP code."""
        user_input = user_input.lower().strip()
        if user_input in LANG_MAP:
            return user_input
        for code, name in LANG_MAP.items():
            if name.lower() == user_input:
                return code
        return None

    # --- MESSAGE COMMAND (right-click > Apps > Translate) ---
    async def translate_message(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        text = (message.content or "").strip()
        if not text:
            await interaction.response.send_message(
                "❌ No text to translate.", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            detected_code = await asyncio.to_thread(detect, text)
            display_name = LANG_MAP.get(detected_code, detected_code.upper())

            translated = await translate_client.translate(
                text, source="auto", target="en"
            )

            embed = build_translation_embed(
                text, translated, display_name, interaction.user
            )
            view = TranslateResultView(self, text, interaction.user.id)
            view.message = await interaction.followup.send(
                embed=embed, view=view, wait=True
            )
        except translate_client.TranslationUnavailable:
            await interaction.followup.send(BUSY_MESSAGE, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    # --- SLASH COMMAND (/translate) ---
    @app_commands.command(
        name="translate", description="Translate English text into another language."
    )
    @app_commands.describe(
        language="Search and select the language to translate INTO",
        phrase="The English text you want to translate",
    )
    @app_commands.autocomplete(language=language_autocomplete)
    async def translate_slash(
        self, interaction: discord.Interaction, language: str, phrase: str
    ):
        await interaction.response.defer()

        try:
            # Check if the code provided exists in our map
            target_lang_name = LANG_MAP.get(language, language.upper())

            translated = await translate_client.translate(
                phrase, source="en", target=language
            )

            embed = discord.Embed(
                title=f"🌐 Translated to {target_lang_name}",
                color=discord.Color.green(),
            )
            embed.add_field(
                name=f"{target_lang_name} Translation",
                value=f"**{translated}**",
                inline=False,
            )
            embed.add_field(name="Original English", value=f"> {phrase}", inline=False)

            embed.set_footer(
                text=f"Requested by {interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url,
            )

            await interaction.followup.send(embed=embed)

        except translate_client.TranslationUnavailable:
            await interaction.followup.send(BUSY_MESSAGE, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"❌ An error occurred: `{e}`", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Translation(bot))
