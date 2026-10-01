"""Tests for the leveling curve in features/economy.py (issue #461).

Derived from the Acceptance Criteria: the /level display and the on_message
level-up loop must agree on "XP required for level N", sourced from a single
helper, at every level — including above the old level-20 curve cutoff.
"""

from unittest.mock import AsyncMock, MagicMock

import discord

from features.economy import Economy, _exp_required_for_level


# --- _exp_required_for_level (single source of truth) ---


def test_exp_required_is_pure_exponential_at_every_level():
    # This is exactly the formula the on_message level-up loop checks against.
    for level in [1, 2, 10, 19, 20, 21, 25, 40]:
        assert _exp_required_for_level(level) == int(100 * (1.5 ** (level - 1)))


def test_exp_required_has_no_linear_phase_past_level_20():
    # The old display used a linear phase beyond level 20; the real requirement
    # keeps growing exponentially, so level 25 is ~1.68M, not ~247k.
    assert _exp_required_for_level(25) == 1683411
    old_linear = int(100 * (1.5**19)) + 5000 * (25 - 20)
    assert _exp_required_for_level(25) != old_linear


def test_exp_required_strictly_increasing():
    values = [_exp_required_for_level(n) for n in range(1, 41)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


# --- /level command display ---


def _make_level_interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 987654321
    interaction.user.display_name = "TestUser"
    interaction.user.display_avatar = MagicMock()
    interaction.user.display_avatar.url = "http://avatar"
    return interaction


async def _run_level(monkeypatch, level, exp):
    monkeypatch.setattr(
        "features.economy.get_leveling_data", AsyncMock(return_value=(level, exp))
    )
    cog = Economy.__new__(Economy)  # skip __init__ so task loops don't start
    interaction = _make_level_interaction()
    await Economy.level.callback(cog, interaction)
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    return {field.name: field.value for field in embed.fields}


async def test_level_display_matches_loop_requirement_past_level_20(monkeypatch):
    # AC: for a user above level 20, the shown next_level_exp equals the value
    # the on_message loop actually requires for that level.
    fields = await _run_level(monkeypatch, level=25, exp=200000)
    exp_field = next(v for k, v in fields.items() if "EXP" in k)
    required = _exp_required_for_level(25)
    assert exp_field == f"200000/{required}"


async def test_progress_bar_not_misleadingly_full_past_level_20(monkeypatch):
    # AC: the bar reaches 100% only within one message's XP of leveling up.
    # At level 25 with 200k XP the user is nowhere close (~12%), not ~81% as the
    # old linear display showed.
    fields = await _run_level(monkeypatch, level=25, exp=200000)
    progress_field = next(v for k, v in fields.items() if "Progress" in k)
    percent = float(progress_field.split("`")[1].rstrip("%"))
    assert percent < 20.0
    assert "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩" not in progress_field


async def test_progress_bar_full_only_within_one_message(monkeypatch):
    # One message (10 XP) short of leveling up at level 25 -> ~100%.
    required = _exp_required_for_level(25)
    fields = await _run_level(monkeypatch, level=25, exp=required - 5)
    progress_field = next(v for k, v in fields.items() if "Progress" in k)
    percent = float(progress_field.split("`")[1].rstrip("%"))
    assert percent >= 99.9


async def test_level_display_matches_loop_below_cutoff(monkeypatch):
    # The two phases already agreed below level 20; that must still hold.
    fields = await _run_level(monkeypatch, level=10, exp=500)
    exp_field = next(v for k, v in fields.items() if "EXP" in k)
    assert exp_field == f"500/{_exp_required_for_level(10)}"
