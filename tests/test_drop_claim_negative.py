"""Regression tests for issue #579.

`/drop` with a negative amount raised a ValueError because the persistent
`DropClaimButton` template only matched `\\d+`, so a custom_id like
`drop_claim:-100` failed the template check in discord.py's DynamicItem.

Cases are derived from the issue's Acceptance Criteria:
- the command successfully processes negative numeric amounts for drop claims
- no ValueError related to custom_id 'drop_claim:-100' occurs
"""

import pytest

from features.economy import DropClaimButton, build_drop_view


def test_drop_claim_button_accepts_negative_amount():
    """Constructing the button with a negative amount must not raise ValueError."""
    button = DropClaimButton(-100)
    assert button.amount == -100
    assert button.item.custom_id == "drop_claim:-100"


def test_build_drop_view_accepts_negative_amount():
    """build_drop_view(-100) is the path that threw in the reported traceback."""
    view = build_drop_view(-100)
    claim_buttons = [c for c in view.children if isinstance(c, DropClaimButton)]
    assert len(claim_buttons) == 1
    assert claim_buttons[0].amount == -100
    assert claim_buttons[0].item.custom_id == "drop_claim:-100"


def test_template_matches_negative_custom_id():
    """The compiled template must match a negative custom_id so discord.py can
    rebuild the persistent button after a restart."""
    match = DropClaimButton.__discord_ui_compiled_template__.match("drop_claim:-100")
    assert match is not None
    assert int(match["amount"]) == -100


@pytest.mark.asyncio
async def test_from_custom_id_round_trips_negative_amount():
    """from_custom_id reconstructs the button with the negative amount intact."""
    template = DropClaimButton.__discord_ui_compiled_template__
    match = template.match("drop_claim:-100")
    button = await DropClaimButton.from_custom_id(None, None, match)
    assert button.amount == -100
    assert button.item.custom_id == "drop_claim:-100"


def test_positive_amount_still_works():
    """Regression guard: the common positive case keeps working unchanged."""
    button = DropClaimButton(250)
    assert button.amount == 250
    assert button.item.custom_id == "drop_claim:250"
    match = DropClaimButton.__discord_ui_compiled_template__.match("drop_claim:250")
    assert match is not None
    assert int(match["amount"]) == 250
