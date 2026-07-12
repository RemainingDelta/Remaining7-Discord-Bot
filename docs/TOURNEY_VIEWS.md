# Tournament Views (UI Components)

## Overview
`features/tourney/tourney_views.py` defines all Discord UI components for the tournament system: the modals members fill out when opening a ticket, the panel buttons that trigger those modals, and the staff action buttons that appear after closing a ticket. All views use `timeout=None` so they persist across bot restarts.

---

## Component Map

```
Panel button clicked
    └── TourneyOpenTicketView (button) → TourneyReportModal (modal) → create_tourney_ticket_channel()
    └── PreTourneyOpenTicketView (button) → PreTourneyReportModal (modal) → create_pre_tourney_ticket_channel()

Ticket closed (!close)
    └── DeleteTicketView (2 buttons: Delete / Reopen)
```

---

## `TourneyReportModal`

The modal that appears when a member clicks "Open Tourney Ticket" during a live tournament.

**Fields**:
| Field | Label | Required | Max Length | Notes |
|-------|-------|----------|-----------|-------|
| `team_name` | Matcherino Team Name | Yes | 100 | Used for fuzzy matching |
| `bracket` | Match No. | Yes | 50 | Parsed as `int`; if non-integer, falls back to team name lookup |
| `issue` | Issue / Report | Yes | 1000 | Paragraph style (`discord.TextStyle.paragraph`) |

**`on_submit` logic** (the most complex part of the views file):

1. Calls `create_tourney_ticket_channel()` to create the private channel
2. Increments `tourney_queue` in the active session document
3. If a Matcherino ID is set (`get_matcherino_id_from_active()`), immediately fetches live match data and posts it in the new channel:
   - Tries `fetch_ticket_context(bracket_url, int(bracket), topic_team_name)` first
   - If `bracket` is not a valid integer → `ValueError` is caught, falls back to `find_match_by_team_name(bracket_url, team_name)`
   - If the match number is valid but team name mismatches → auto-attempts `find_match_by_team_name()` to correct it
   - If match number not found in bracket → `find_match_by_team_name()` fallback
   - On successful correction, persists the resolved match number back into the channel topic via `channel.edit(topic=...)`
4. Posts the live match embed in the new ticket channel (gold for clean match, red for mismatch)

**Auto-correction note**: The modal is the only place where all three fallback paths run synchronously (not in the 1-minute refresher). This means the ticket opens with accurate match data immediately, even if the member entered the wrong match number — as long as the team name is close enough for fuzzy matching to resolve it.

---

## `TourneyOpenTicketView`

The panel button that triggers `TourneyReportModal`. Posted to `TOURNEY_SUPPORT_CHANNEL_ID` by `!starttourney`.

```python
class TourneyOpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persists across restarts

    @discord.ui.button(
        label="Open Tourney Ticket ⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="tourney_open_ticket",  # Stable ID for persistence
    )
    async def open_ticket(self, interaction, button):
        await interaction.response.send_modal(TourneyReportModal())
```

The `custom_id` is what allows Discord to re-attach the button callback after a bot restart. Without a stable `custom_id`, the button becomes dead after a restart.

---

## `PreTourneyReportModal`

The modal for pre-tournament support tickets. Simpler than `TourneyReportModal` — team name is optional and there is no match number field.

**Fields**:
| Field | Label | Required | Max Length |
|-------|-------|----------|-----------|
| `team_name` | Team Name (Optional) | No | 100 |
| `issue` | Issue / Question | Yes | 1000 |

**`on_submit`**: Calls `create_pre_tourney_ticket_channel()` directly. No Matcherino lookup is performed (no bracket data exists pre-tournament). Also increments the tourney queue counter.

---

## `PreTourneyOpenTicketView`

Panel button for `PRE_TOURNEY_SUPPORT_CHANNEL_ID`. Uses `custom_id="pretourney_open_ticket"`.

```python
@discord.ui.button(
    label="Contact Support 📩",
    style=discord.ButtonStyle.primary,
    custom_id="pretourney_open_ticket",
)
async def open_ticket(self, interaction, button):
    await interaction.response.send_modal(PreTourneyReportModal())
```

---

## `DeleteTicketView`

Attached to the close message sent by `!close`. Gives staff two post-close actions without needing to type a command.

**Buttons**:

| Button | Label | Style | `custom_id` | Action |
|--------|-------|-------|-------------|--------|
| Delete | "Delete Ticket" | Danger (red) | `tourney_delete_ticket` | Calls `delete_tourney_ticket(interaction)` → saves transcript + deletes channel |
| Reopen | "Reopen Ticket" | Success (green) | `tourney_reopen_ticket` | Calls `reopen_tourney_ticket(interaction)` → moves back to active category |

Both callbacks import their handler from `tourney_utils` lazily (inside the function) to avoid circular imports at module load time.

---

## Persistence Across Bot Restarts

All views use `timeout=None`. For button callbacks to survive a restart, the bot must re-register the view on startup. This is done in `restore_tourney_panels()` called from `main.py`:

```python
await restore_tourney_panels(bot)
```

This function adds the persistent views back to the bot's view store so Discord can match incoming button interactions to their handlers by `custom_id`.

If you don't call this, buttons on old panel messages become non-functional after a restart.

---

## Porting Checklist

When porting to a new bot, these are the things to change in this file:

- [ ] Modal field labels/placeholders — change tournament-specific language
- [ ] `TourneyReportModal.on_submit` — replace `get_matcherino_id_from_active()` and Matcherino fetch logic if the new bot uses a different bracket provider
- [ ] Button labels in `TourneyOpenTicketView` and `PreTourneyOpenTicketView`
- [ ] `custom_id` values — must be unique per bot if running multiple bots in the same server
- [ ] Ensure `restore_tourney_panels()` is updated to re-add all persistent views on startup

---

## Source File
`features/tourney/tourney_views.py`
