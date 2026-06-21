"""Tests for TIMEZONE_ALIASES and convert_time command in features/general.py."""

from features.general import General


# --- TIMEZONE_ALIASES ---


def test_alias_est_resolves_to_new_york():
    assert General.TIMEZONE_ALIASES["EST"] == "America/New_York"


def test_alias_pt_resolves_to_los_angeles():
    assert General.TIMEZONE_ALIASES["PT"] == "America/Los_Angeles"


def test_alias_utc_resolves_to_utc():
    assert General.TIMEZONE_ALIASES["UTC"] == "UTC"


def test_alias_ist_resolves_to_kolkata():
    assert General.TIMEZONE_ALIASES["IST"] == "Asia/Kolkata"


def test_alias_jst_resolves_to_tokyo():
    assert General.TIMEZONE_ALIASES["JST"] == "Asia/Tokyo"


def test_alias_gmt_resolves_to_london():
    assert General.TIMEZONE_ALIASES["GMT"] == "Europe/London"


def test_alias_cet_resolves_to_berlin():
    assert General.TIMEZONE_ALIASES["CET"] == "Europe/Berlin"


# --- convert_time command ---


async def test_convert_time_valid_input_sends_embed(mock_bot, mock_interaction):
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "2025-01-01", "12:00 PM", "UTC"
    )

    mock_interaction.response.send_message.assert_called_once()
    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert "embed" in kwargs


async def test_convert_time_embed_contains_discord_timestamp(
    mock_bot, mock_interaction
):
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "2025-01-01", "12:00 PM", "UTC"
    )

    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    assert "<t:" in embed.description


async def test_convert_time_alias_works(mock_bot, mock_interaction):
    """EST alias should resolve and return an embed, not an error."""
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "2025-06-15", "3:00 PM", "EST"
    )

    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert "embed" in kwargs


async def test_convert_time_iana_timezone_works(mock_bot, mock_interaction):
    """Direct IANA timezone name should be accepted."""
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "2025-06-15", "3:00 PM", "America/New_York"
    )

    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert "embed" in kwargs


async def test_convert_time_invalid_timezone_sends_ephemeral_error(
    mock_bot, mock_interaction
):
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "2025-01-01", "12:00 PM", "FAKETZ"
    )

    mock_interaction.response.send_message.assert_called_once()
    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_convert_time_invalid_date_sends_ephemeral_error(
    mock_bot, mock_interaction
):
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "not-a-date", "12:00 PM", "UTC"
    )

    mock_interaction.response.send_message.assert_called_once()
    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_convert_time_invalid_time_format_sends_ephemeral_error(
    mock_bot, mock_interaction
):
    cog = General(mock_bot)
    await cog.convert_time.callback(cog, mock_interaction, "2025-01-01", "25:99", "UTC")

    mock_interaction.response.send_message.assert_called_once()
    kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert kwargs.get("ephemeral") is True


async def test_convert_time_footer_shows_alias_expansion(mock_bot, mock_interaction):
    """Footer should note the alias expansion when an abbreviation is used."""
    cog = General(mock_bot)
    await cog.convert_time.callback(
        cog, mock_interaction, "2025-01-01", "12:00 PM", "EST"
    )

    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    assert "from EST" in embed.footer.text
