# Privacy System

## Overview
The bot publishes one privacy policy in three places: `PRIVACY_POLICY.md` at the repo root, the `/privacy-policy` slash command, and a channel the bot reposts to on every startup. The wording lives once, as data, in `features/privacy_policy.py` — both Discord surfaces render the same `POLICY_PARTS`, so a change to the policy reaches the command and the channel together.

The same policy is also hosted on the web at <https://remaining7.netlify.app/privacy>, linked at the foot of the last embed for anyone who wants to read or share it outside Discord. The only other reference the policy carries is a mention of the in-server tickets channel, which is how deletion requests and questions arrive.

---

## Where the content lives

`features/privacy_policy.py` holds two frozen dataclasses:

```python
PolicySection(heading, body)          # one "## heading" of the policy
PolicyPart(title, intro, sections)    # a group of sections = one embed
```

`POLICY_PARTS` is the single source of truth: ten sections grouped into three parts.

| Part | Embed title | Sections |
|---|---|---|
| 1 | 🔒 Remaining 7 Bot Privacy Policy | intro, Who we are, What information we collect |
| 2 | 🔒 Privacy Policy — Use & Storage | What we do not collect or store, Why we collect this information, Where your information is stored, When information leaves Discord |
| 3 | 🔒 Privacy Policy — Your Choices | Opt-out and your choices, Age requirement, Changes to this policy, Contact us |

The grouping exists for Discord's limits, not for the reading order. A description caps at **4096 characters** and one message caps at **6000 characters across all its embeds**; the policy renders to roughly 5.2k, so it fits in a single message with headroom. `tests/test_privacy_policy.py` asserts both limits, so a section that grows past them fails the suite rather than the API.

---

## Rendering

```python
build_privacy_embeds(guild_id) -> list[discord.Embed]
```

Each part becomes one embed: `part.intro`, then every section as `## heading` followed by its body. The last embed gets `Last updated: <date>` as its footer.

`guild_id` only shapes the contact line. `tickets_contact_line(guild_id)` builds:

```
Open a ticket in <#OTHER_TICKET_CHANNEL_ID> and select Server Support.
```

The `<#id>` form is a real Discord channel mention, so it renders as the purple `#channel` chip rather than a blue URL link. The channel comes from `OTHER_TICKET_CHANNEL_ID`, which is already split REAL/TEST in `features/config.py`, so the dev server points at its own tickets channel. `guild_id` no longer feeds the mention itself; it is only used to decide guild vs. DM. Called without a guild — a DM, where a bare mention would not resolve to a name — the line degrades to plain text instead.

The `{contact}` placeholder is the only templated text in the policy; every other body is rendered verbatim.

---

## `/privacy-policy`

Ephemeral, no permission gate — the response is visible only to the member who ran it. The channel repost (below) is the everyone-can-see copy. One response containing the whole embed sequence:

```python
await interaction.response.send_message(embeds=build_privacy_embeds(interaction.guild_id), ephemeral=True)
```

Listed in the Utility section of `/help`.

---

## Auto-posted privacy channel

`PRIVACY_CHANNEL_ID` (`features/config.py`, both branches) is the channel that holds the policy. `main.py` calls `repost_privacy_policy(bot)` from `on_ready`, after the cogs and tourney panels and before the command sync.

The flow:

1. If `PRIVACY_CHANNEL_ID` is falsy (`0` = not set up on this server yet), log a warning and return. Startup is never blocked by an unconfigured channel.

2. Resolve the channel; skip if it is missing or not a `TextChannel`.
3. Scan `channel.history(limit=HISTORY_SCAN_LIMIT)` and delete **every** message authored by the bot.
4. Post the fresh sequence with `channel.send(embeds=...)`.

This is the repost-on-restart pattern from `restore_tourney_panels()` (#149). Deleting rather than editing in place matters here: if the policy is later regrouped into a different number of parts, editing would leave orphaned embeds behind, while delete-then-post always leaves exactly one current copy. The whole body is wrapped in `try/except` — a permissions error in one channel must not take down the rest of startup.

The channel should be locked so only the bot can post in it; the delete pass only removes the bot's own messages, so anything a member posts stays and accumulates.

---

## Editing the policy

1. Edit the section body in `features/privacy_policy.py`.
2. Make the same edit in `PRIVACY_POLICY.md`. The two are checked against each other by tests for section coverage and the "Last updated" date, but not word for word — keep them in step by hand.
3. Bump `LAST_UPDATED` in the module and `Last updated:` in the document.
4. Run `make ci`. The character-limit tests are the guard against a section that has grown too long for its embed.
5. Restart the bot. The privacy channel updates itself; nothing needs reposting by hand.

Adding a section means adding a `PolicySection` to whichever part keeps the three roughly balanced, plus the same `## heading` in the document, plus the heading in `POLICY_HEADINGS` in `tests/test_privacy_policy.py` (that list is the ticket's spec, so it is updated deliberately, not to make a test pass).

---

## Tests

`tests/test_privacy_policy.py` covers:

- section list and order against the filed policy
- 2–3 embeds, each description under 4096, the sequence under 6000
- every section body actually rendered, and the last embed carrying the date
- the tickets channel mention present only in the last embed, built from the config channel
- production mode mentioning the production tickets channel (via `importlib.reload` of the config), dev mode never containing the production ID
- the hosted policy site as the only external link in the embeds and in this guide (at the foot of the last embed); the standalone `PRIVACY_POLICY.md` carries none
- the policy text existing in exactly one file under `features/`
- the command responding ephemerally, including for a member with no roles
- the startup repost deleting the bot's messages **before** posting, leaving other authors' messages alone, and skipping a missing, non-text, or unconfigured channel without raising

---

## Related

- `docs/SUPPORT_TICKETS.md` — the tickets channel the contact line points at
- `docs/GITHUB_TICKETS.md` — the Gemini/GitHub path described in "When information leaves Discord"
- `docs/DATABASE.md` — the collections the policy describes
