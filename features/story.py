import asyncio
import re

import discord
from discord import app_commands
from discord.ext import commands

from database.mongo import (
    add_story_banlist_item,
    append_story_word,
    get_story_banlist,
    get_story_state,
    remove_story_banlist_item,
    reset_story,
    seed_default_banned_words,
    set_story_active,
)
from features.config import STORY_CHANNEL_ID, STORY_MOD_ROLES

# Discord custom emojis render as <:name:id> / <a:name:id> in message content.
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")
# Main Unicode emoji ranges (pictographs, emoticons, symbols, flags, etc.).
_UNICODE_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, supplemental, extended-A
    "\U00002600-\U000027bf"  # misc symbols + dingbats
    "\U00002300-\U000023ff"  # misc technical (⌚ ⏰ ⌛ …)
    "\U00002b00-\U00002bff"  # misc symbols & arrows (⭐ …)
    "\U0001f1e6-\U0001f1ff"  # regional indicator flags
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # zero-width joiner (emoji sequences)
    "]"
)


def _contains_emoji(text: str) -> bool:
    return bool(_CUSTOM_EMOJI_RE.search(text) or _UNICODE_EMOJI_RE.search(text))


# Common leet substitutions folded to letters before banned-word matching.
_LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "9": "g",
        "@": "a",
        "$": "s",
        "!": "i",
    }
)


def normalize_for_match(word: str) -> str:
    """Fold a word to a canonical form for banned-word matching: lowercase,
    apply leet substitutions, drop non-letters, and collapse any run of 3+
    identical letters to one (so "shiiiit" -> "shit", "f4ggot" -> "faggot").
    Normal double letters are preserved so "as" never collapses to match "ass"."""
    word = word.lower().translate(_LEET_MAP)
    word = re.sub(r"[^a-z]", "", word)
    word = re.sub(r"(.)\1{2,}", r"\1", word)
    return word


# Discord embed descriptions cap at 4096 characters.
_STORY_EMBED_LIMIT = 4096
# Leave a little headroom when chunking a long story across multiple embeds.
_STORY_CHUNK_LIMIT = 4000


# A contribution ends a sentence if it ends with one of these (trailing quotes
# and brackets are ignored, so `word."` or `word!)` still count).
_SENTENCE_ENDINGS = (".", "!", "?")


def render_story_words(words: list[str]) -> list[str]:
    """Return the words normalized for display: everything lowercased, with the
    first letter of each sentence capitalized (the first word, and any word
    following one that ended a sentence)."""
    rendered: list[str] = []
    start_of_sentence = True
    for word in words:
        display = word.lower()
        if start_of_sentence:
            for i, ch in enumerate(display):
                if ch.isalpha():
                    display = display[:i] + ch.upper() + display[i + 1 :]
                    break
        rendered.append(display)
        trimmed = word.rstrip("\"')]}")
        start_of_sentence = trimmed.endswith(_SENTENCE_ENDINGS)
    return rendered


# Tokens starting with one of these attach to the previous word with no space,
# so a standalone "." renders as "noob." rather than "noob .".
_ATTACH_LEFT = frozenset(".,;:!?)]}")


def glue_punctuation(words: list[str]) -> list[str]:
    """Merge punctuation-leading tokens onto the preceding word so they render
    without a leading space. `["noob", ".", "But"]` -> `["noob.", "But"]`."""
    glued: list[str] = []
    for word in words:
        if glued and word and word[0] in _ATTACH_LEFT:
            glued[-1] += word
        else:
            glued.append(word)
    return glued


def display_story_units(words: list[str]) -> list[str]:
    """Full display pipeline: apply sentence casing, then glue punctuation.
    The result is a list of space-separated display units."""
    return glue_punctuation(render_story_words(words))


def chunk_story_words(words: list[str], limit: int = _STORY_CHUNK_LIMIT) -> list[str]:
    """Join words into space-separated chunks, each at most ``limit`` chars,
    never splitting a word across chunks."""
    chunks: list[str] = []
    current = ""
    for word in words:
        piece = f"{current} {word}" if current else word
        if current and len(piece) > limit:
            chunks.append(current)
            current = word
        else:
            current = piece
    if current:
        chunks.append(current)
    return chunks


def validate_story_word(
    content: str, banned_words: list[str], banned_chars: list[str]
) -> tuple[str | None, str | None]:
    """Validate a single story contribution.

    Returns ``(word, None)`` on success (preserving the original casing) or
    ``(None, reason)`` on rejection, where reason is one of
    ``"empty"``, ``"multiword"``, ``"emoji"``, ``"banned_char"``,
    ``"banned_word"``.
    Kept free of Discord/Mongo so it can be unit-tested in isolation.
    """
    word = content.strip()
    if not word:
        return None, "empty"
    if any(ch.isspace() for ch in word):
        return None, "multiword"
    if _contains_emoji(word):
        return None, "emoji"

    lowered = word.lower()
    banned_char_set = {c.lower() for c in banned_chars}
    if any(ch in banned_char_set for ch in lowered):
        return None, "banned_char"

    normalized = normalize_for_match(word)
    banned_normalized = {normalize_for_match(w) for w in banned_words}
    banned_normalized.discard("")
    if normalized and normalized in banned_normalized:
        return None, "banned_word"

    return word, None


_REJECTION_MESSAGES = {
    "empty": "Your message didn't contain a word.",
    "multiword": "One word at a time! Your message can't contain spaces.",
    "emoji": "Emojis aren't allowed in the story.",
    "banned_char": "That word contains a character that isn't allowed here.",
    "banned_word": "That word is on the banned list.",
}


class Story(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # One-time: fetch the default banned-words list into the DB if it's not
        # already there. Run in the background so a slow/unreachable fetch never
        # blocks startup; it's a no-op on later restarts and never clobbers
        # staff edits. Keep a reference so the task isn't garbage-collected.
        self._seed_task = asyncio.create_task(seed_default_banned_words())

    def _is_staff(self, user) -> bool:
        return isinstance(user, discord.Member) and any(
            role.id in STORY_MOD_ROLES for role in user.roles
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.id != STORY_CHANNEL_ID:
            return

        state = await get_story_state()

        # No active story → ignore silently. The absence of a ✅ reaction is
        # the signal to contributors that the story isn't currently running.
        if not state["active"]:
            return

        if message.author.id == state["last_user_id"]:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} You can't add two words in a row!",
                delete_after=5,
            )
            return

        banned_words = await get_story_banlist("banned_words")
        banned_chars = await get_story_banlist("banned_chars")
        word, reason = validate_story_word(message.content, banned_words, banned_chars)
        if word is None:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} {_REJECTION_MESSAGES[reason]}",
                delete_after=5,
            )
            return

        await append_story_word(word, message.author.id)
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            # Missing "Add Reactions" permission or the message vanished — the
            # word is already recorded, so don't let a failed reaction bubble up.
            pass

    @app_commands.command(
        name="story-see", description="View the current collaborative story."
    )
    async def story_see(self, interaction: discord.Interaction):
        if interaction.channel_id != STORY_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{STORY_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        state = await get_story_state()
        words = state["words"]
        if not words:
            await interaction.response.send_message(
                "📖 The story is empty. Add the first word!", ephemeral=True
            )
            return

        story = " ".join(display_story_units(words))
        if len(story) > _STORY_EMBED_LIMIT:
            story = "…" + story[-(_STORY_EMBED_LIMIT - 1) :]
        embed = discord.Embed(
            title="📖 The story so far",
            description=story,
            color=discord.Color.blurple(),
        )
        status = "active" if state["active"] else "closed"
        embed.set_footer(text=f"{len(words)} words • {status}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="story-start",
        description="Archive the current story and begin a new one (staff only).",
    )
    async def story_start(self, interaction: discord.Interaction):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        if interaction.channel_id != STORY_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{STORY_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await reset_story()
        await set_story_active(True)
        await interaction.response.send_message(
            "✅ Started a new story.", ephemeral=True
        )
        await interaction.channel.send(
            "📖 **A new story begins!** Add one word to keep it going — "
            "one word per message, and you can't go twice in a row. "
            "Each accepted word gets a ✅."
        )

    @app_commands.command(
        name="story-reset",
        description="Archive and clear the current story (staff only).",
    )
    async def story_reset(self, interaction: discord.Interaction):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        if interaction.channel_id != STORY_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{STORY_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await reset_story()
        await set_story_active(False)
        await interaction.response.send_message(
            "✅ The story has been reset and archived.", ephemeral=True
        )

    @app_commands.command(
        name="story-end",
        description="Publish the finished story, then archive and clear it "
        "(staff only).",
    )
    async def story_end(self, interaction: discord.Interaction):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        if interaction.channel_id != STORY_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{STORY_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        state = await get_story_state()
        words = state["words"]
        if not words:
            await interaction.response.send_message(
                "ℹ️ There's no story to end yet.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ Story ended and archived.", ephemeral=True
        )
        chunks = chunk_story_words(display_story_units(words))
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title="📖 The End!" if i == 0 else None,
                description=chunk,
                color=discord.Color.blurple(),
            )
            if i == len(chunks) - 1:
                embed.set_footer(text=f"{len(words)} words")
            await interaction.channel.send(embed=embed)
        await reset_story()
        await set_story_active(False)

    # --- Banned word management (staff only) ---

    banword_group = app_commands.Group(
        name="story-banword", description="Manage the story banned-word list."
    )

    @banword_group.command(name="add", description="Ban a word from the story.")
    @app_commands.describe(word="The word to ban")
    async def banword_add(self, interaction: discord.Interaction, word: str):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        normalized = word.strip().lower()
        if not normalized:
            await interaction.response.send_message(
                "❌ Provide a word to ban.", ephemeral=True
            )
            return
        added = await add_story_banlist_item("banned_words", normalized)
        if added:
            await interaction.response.send_message(
                f"✅ Banned the word **{normalized}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ **{normalized}** is already banned.", ephemeral=True
            )

    @banword_group.command(name="remove", description="Unban a word.")
    @app_commands.describe(word="The word to unban")
    async def banword_remove(self, interaction: discord.Interaction, word: str):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        normalized = word.strip().lower()
        removed = await remove_story_banlist_item("banned_words", normalized)
        if removed:
            await interaction.response.send_message(
                f"✅ Unbanned the word **{normalized}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ **{normalized}** wasn't on the banned list.", ephemeral=True
            )

    @banword_group.command(name="list", description="List all banned words.")
    async def banword_list(self, interaction: discord.Interaction):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        items = await get_story_banlist("banned_words")
        if not items:
            await interaction.response.send_message(
                "ℹ️ No words are banned.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🚫 **Banned words:** " + ", ".join(f"`{w}`" for w in items),
            ephemeral=True,
        )

    # --- Banned character management (staff only) ---

    banchar_group = app_commands.Group(
        name="story-banchar", description="Manage the story banned-character list."
    )

    @banchar_group.command(
        name="add", description="Ban a single character from story words."
    )
    @app_commands.describe(character="The single character to ban")
    async def banchar_add(self, interaction: discord.Interaction, character: str):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        char = character.strip()
        if len(char) != 1:
            await interaction.response.send_message(
                "❌ Provide exactly one character to ban.", ephemeral=True
            )
            return
        added = await add_story_banlist_item("banned_chars", char)
        if added:
            await interaction.response.send_message(
                f"✅ Banned the character `{char}`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ `{char}` is already banned.", ephemeral=True
            )

    @banchar_group.command(name="remove", description="Unban a character.")
    @app_commands.describe(character="The character to unban")
    async def banchar_remove(self, interaction: discord.Interaction, character: str):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        char = character.strip()
        removed = await remove_story_banlist_item("banned_chars", char)
        if removed:
            await interaction.response.send_message(
                f"✅ Unbanned the character `{char}`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ `{char}` wasn't on the banned list.", ephemeral=True
            )

    @banchar_group.command(name="list", description="List all banned characters.")
    async def banchar_list(self, interaction: discord.Interaction):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return
        items = await get_story_banlist("banned_chars")
        if not items:
            await interaction.response.send_message(
                "ℹ️ No characters are banned.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🚫 **Banned characters:** " + ", ".join(f"`{c}`" for c in items),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Story(bot))
