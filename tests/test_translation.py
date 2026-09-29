"""Tests for features/translation.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

from features import translate_client
from features.translation import (
    BUSY_MESSAGE,
    SourceLanguageModal,
    TranslateResultView,
    Translation,
)


def make_cog():
    return Translation(MagicMock())


def make_message(content):
    message = MagicMock(spec=discord.Message)
    message.content = content
    return message


def patch_translator(translated="Hello friend", error=None):
    """Patch the shared translate client to return `translated` or raise `error`."""
    translate = AsyncMock(return_value=translated, side_effect=error)
    return patch("features.translation.translate_client.translate", new=translate)


def sent_embed(interaction):
    return interaction.followup.send.call_args.kwargs["embed"]


def embed_text(embed):
    parts = [embed.title or ""]
    for field in embed.fields:
        parts.append(field.name)
        parts.append(field.value)
    return "\n".join(parts)


# --- "Translate" message command (#564) ---


async def test_translate_message_replies_with_original_and_translation(
    mock_interaction,
):
    cog = make_cog()
    with (
        patch("features.translation.detect", return_value="es"),
        patch_translator("Hello friend"),
    ):
        await cog.translate_message(mock_interaction, make_message("Hola amigo"))

    text = embed_text(sent_embed(mock_interaction))
    assert "Hola amigo" in text
    assert "Hello friend" in text
    assert "Spanish" in text


async def test_translate_message_with_no_text_errors_without_translating(
    mock_interaction,
):
    cog = make_cog()
    with patch_translator() as translate:
        await cog.translate_message(mock_interaction, make_message("   "))

    translate.assert_not_awaited()
    mock_interaction.response.send_message.assert_awaited_once()
    assert mock_interaction.response.send_message.call_args.kwargs["ephemeral"]
    mock_interaction.followup.send.assert_not_called()


async def test_translate_message_translator_error_is_ephemeral(mock_interaction):
    cog = make_cog()
    with (
        patch("features.translation.detect", return_value="es"),
        patch_translator(error=RuntimeError("service down")),
    ):
        await cog.translate_message(mock_interaction, make_message("Hola amigo"))

    mock_interaction.followup.send.assert_awaited_once()
    assert mock_interaction.followup.send.call_args.kwargs["ephemeral"]
    assert "embed" not in mock_interaction.followup.send.call_args.kwargs


async def test_translate_message_when_providers_unavailable_shows_busy(
    mock_interaction,
):
    cog = make_cog()
    with (
        patch("features.translation.detect", return_value="es"),
        patch_translator(error=translate_client.TranslationUnavailable()),
    ):
        await cog.translate_message(mock_interaction, make_message("Hola amigo"))

    mock_interaction.followup.send.assert_awaited_once_with(
        BUSY_MESSAGE, ephemeral=True
    )


async def test_translate_message_unmapped_language_code_is_upper_cased(
    mock_interaction,
):
    cog = make_cog()
    with (
        patch("features.translation.detect", return_value="xx"),
        patch_translator("Hello"),
    ):
        await cog.translate_message(mock_interaction, make_message("blah"))

    assert "XX" in sent_embed(mock_interaction).title


# --- "Wrong language?" override (restores `!t <language>`) ---


async def translated_view(mock_interaction, text="Hola amigo"):
    """Run the Translate command and return the result view it attached."""
    cog = make_cog()
    with (
        patch("features.translation.detect", return_value="es"),
        patch_translator("Hello friend"),
    ):
        await cog.translate_message(mock_interaction, make_message(text))
    return mock_interaction.followup.send.call_args.kwargs["view"]


def make_button_interaction(user_id=987654321):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = user_id
    interaction.user.display_name = "TestUser"
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


async def submit_language(view, value):
    modal = SourceLanguageModal(view)
    modal.language._value = value
    interaction = make_button_interaction()
    await modal.on_submit(interaction)
    return interaction


async def test_result_has_a_wrong_language_button(mock_interaction):
    view = await translated_view(mock_interaction)

    assert isinstance(view, TranslateResultView)
    labels = [c.label for c in view.children if isinstance(c, discord.ui.Button)]
    assert labels == ["Wrong language?"]


async def test_wrong_language_button_opens_the_language_modal(mock_interaction):
    view = await translated_view(mock_interaction)
    interaction = make_button_interaction()

    await view.wrong_language.callback(interaction)

    modal = interaction.response.send_modal.call_args.args[0]
    assert isinstance(modal, SourceLanguageModal)


async def test_only_the_requester_can_use_the_button(mock_interaction):
    view = await translated_view(mock_interaction)

    assert await view.interaction_check(make_button_interaction()) is True
    other = make_button_interaction(user_id=1)
    assert await view.interaction_check(other) is False
    assert other.response.send_message.call_args.kwargs["ephemeral"]


async def test_language_name_retranslates_with_that_source(mock_interaction):
    view = await translated_view(mock_interaction, text="namaste dost")

    with patch_translator("hello friend") as translate:
        interaction = await submit_language(view, "Hindi")

    translate.assert_awaited_once_with("namaste dost", source="hi", target="en")
    embed = interaction.edit_original_response.call_args.kwargs["embed"]
    assert "Hindi" in embed.title
    assert embed.author.name == "Manual Language Override"
    assert "hello friend" in embed_text(embed)


async def test_language_code_also_works(mock_interaction):
    view = await translated_view(mock_interaction)

    with patch_translator("hello") as translate:
        await submit_language(view, "hi")

    assert translate.await_args.kwargs["source"] == "hi"


async def test_unknown_language_is_rejected_without_translating(mock_interaction):
    view = await translated_view(mock_interaction)

    with patch_translator() as translate:
        interaction = await submit_language(view, "klingon")

    translate.assert_not_awaited()
    assert interaction.response.send_message.call_args.kwargs["ephemeral"]
    interaction.edit_original_response.assert_not_awaited()


async def test_override_when_providers_unavailable_shows_busy(mock_interaction):
    view = await translated_view(mock_interaction)

    with patch_translator(error=translate_client.TranslationUnavailable()):
        interaction = await submit_language(view, "hindi")

    interaction.followup.send.assert_awaited_once_with(BUSY_MESSAGE, ephemeral=True)
    interaction.edit_original_response.assert_not_awaited()


async def test_button_is_disabled_on_timeout(mock_interaction):
    view = await translated_view(mock_interaction)
    view.message = AsyncMock()

    await view.on_timeout()

    assert all(c.disabled for c in view.children)
    view.message.edit.assert_awaited_once()


# --- get_language_code ---


def test_get_language_code_by_full_name():
    assert make_cog().get_language_code("Spanish") == "es"


def test_get_language_code_by_code_directly():
    assert make_cog().get_language_code("es") == "es"


def test_get_language_code_case_insensitive_name():
    assert make_cog().get_language_code("ENGLISH") == "en"
    assert make_cog().get_language_code("english") == "en"


def test_get_language_code_case_insensitive_code():
    assert make_cog().get_language_code("ES") == "es"


def test_get_language_code_unknown_returns_none():
    assert make_cog().get_language_code("klingon") is None


def test_get_language_code_whitespace_only_returns_none():
    assert make_cog().get_language_code("   ") is None


# --- registration ---


def test_no_translate_prefix_command_is_registered():
    names = set()
    for command in make_cog().get_commands():
        names.add(command.name)
        names.update(command.aliases)
    assert "translate" not in names
    assert "t" not in names


async def test_cog_load_registers_translate_message_command():
    bot = MagicMock()
    cog = Translation(bot)

    await cog.cog_load()

    menu = bot.tree.add_command.call_args.args[0]
    assert isinstance(menu, app_commands.ContextMenu)
    assert menu.name == "Translate"
    assert menu.type is discord.AppCommandType.message


async def test_cog_unload_removes_translate_message_command():
    bot = MagicMock()
    bot.tree.remove_command = MagicMock()
    cog = Translation(bot)

    await cog.cog_unload()

    bot.tree.remove_command.assert_called_once_with(
        "Translate", type=discord.AppCommandType.message
    )


def test_translate_slash_command_is_still_registered():
    names = [c.name for c in make_cog().get_app_commands()]
    assert "translate" in names


# --- language_autocomplete ---


async def test_language_autocomplete_filters_by_name(mock_interaction):
    cog = make_cog()
    results = await cog.language_autocomplete(mock_interaction, "span")
    names = [r.name for r in results]
    assert "Spanish" in names


async def test_language_autocomplete_empty_returns_up_to_25(mock_interaction):
    cog = make_cog()
    results = await cog.language_autocomplete(mock_interaction, "")
    assert len(results) <= 25


async def test_language_autocomplete_no_match_returns_empty(mock_interaction):
    cog = make_cog()
    results = await cog.language_autocomplete(mock_interaction, "zzzzzznonexistent")
    assert results == []
