---
name: docs-sync
description: Update every documentation surface after a feature, fix, or behavior change in the Remaining7 Discord bot. Covers README.md, the docs/ implementation guides, and the in-bot help command embeds, which all restate the same facts and drift apart. Use this whenever a change alters user-facing behavior, adds or removes a command, changes prices, thresholds, cooldowns, permissions, or channel restrictions, and whenever preparing a release or someone mentions updating docs, the README, or the help commands. Also use it when only one surface was updated, since the others almost certainly still hold the old value.
---

# Docs Sync

One fact lives in five places in this repo. When it changes, four of them keep the old value.

This has been filed as a ticket six times (#163, #173, #292, #325, #370, #382) and shipped wrong anyway. The pattern is always the same: the code changed, one surface got updated, and the rest kept restating a behavior that no longer exists.

## The core rule

**Read the code, not the existing docs.**

Every one of those six tickets propagated an error that was already written down. Docs were used as the source, so a stale line was copied into a new place rather than corrected. When a doc and the code disagree, the code wins with no exceptions, and the doc is wrong even if it has been there for six releases.

Verify by opening the file that actually implements the behavior. A grep for the old value is not enough, because the same fact appears in prose in three different phrasings.

## The surfaces

Any behavior change touches some subset of these. Check all of them; skip the ones that genuinely do not apply.

### 1. `README.md`

The top-level feature list. Holds the version string, command lists per feature area, the database collection table, the background task table, and the permission hierarchy. Anything added or removed shows up here.

### 2. `docs/<AREA>.md`

Implementation guides, one per feature area. The current set:

| Area | Files |
|---|---|
| Economy | `TOKEN_SYSTEM.md`, `ECONOMY_SHOP.md`, `XP_AND_LEVELING.md`, `QUEST_SYSTEM.md` |
| Brawl | `BRAWL_COLLECTION.md`, `BRAWL_DROPS.md`, `BRAWL_PROGRESSION.md` |
| Tourney | `TOURNEY_OVERVIEW.md`, `TOURNEY_TICKETS.md`, `TOURNEY_MATCHERINO.md`, `TOURNEY_PROGRESS.md`, `TOURNEY_REPORTS.md`, `TOURNEY_BLACKLIST.md`, `TOURNEY_VIEWS.md` |
| Tickets | `SUPPORT_TICKETS.md`, `TICKET_ROUTER.md`, `BOOSTER_SHOUTOUT.md` |
| Moderation | `HACKED_SYSTEM.md`, `SCAM_DETECTION.md`, `MESSAGE_MIRROR.md` |
| Other features | `COUNTING_GAME.md`, `STICKY_MESSAGES.md`, `TRANSLATION.md`, `TIME_CONVERSION.md`, `EVENT_MANAGEMENT.md`, `GITHUB_TICKETS.md`, `PAYOUT_SYSTEM.md` |
| Infrastructure | `SETUP.md`, `CONFIG_SYSTEM.md`, `DATABASE.md` |

Confirm the list against the directory before relying on this table. Files get added with new features.

A change often hits more than one. A booster perk touches `TOKEN_SYSTEM.md` and `XP_AND_LEVELING.md` and `QUEST_SYSTEM.md` and `ECONOMY_SHOP.md`, because the perk shows up in each system.

### 3. In-bot help command embeds

These live in code, not in markdown, which is why they get missed.

| Command | File |
|---|---|
| `/help` | `features/general.py` |
| `/mod-help` | `features/general.py` |
| `/admin-help` | `features/general.py` |
| `/booster-perks` | `features/general.py` |
| `/economy-help` | `features/economy.py` |
| `/tourney-admin-help` | `features/tourney/tourney_commands.py` |
| `/event-staff-help` | `features/event.py` |

A new command needs to appear in whichever help embed matches its permission level. A removed one needs deleting from all of them.

### 4. `docs/logs/SPECS.md` and `docs/logs/CHANGELOG.md`

Separate work with separate rules. SPECS gets the as-implemented record with divergence verdicts; CHANGELOG gets release notes and PR descriptions. Do not paste the same text into both, and do not treat a docs pass as covering them.

### 5. Version string

Source of truth is `pyproject.toml` since #188. `README.md` carries a display copy that has to match.

## How past passes went wrong

Each of these shipped. They are the failure modes to check for.

**Documented a behavior that does not exist.** #325 had `/help` claim a wrong number resets the counting game. It does not; the wrong message is just deleted. Nobody ran the code path.

**Documented the wrong invocation.** #325 wrote `!sticky <message>` when the command is reply-based. The signature was assumed rather than read.

**Described the wrong trigger.** #292 called the GitHub issue creator ticket-driven when it is mention-triggered. Plausible, and wrong.

**Left figures behind after a repricing.** #366 changed shop prices; #370 existed solely to fix the examples in `ECONOMY_SHOP.md` that still showed the old ones. Worked examples with embedded numbers go stale silently.

**Trusted the ticket about where a value lives.** #366's issue said the USD values were in `SHOP_DATA`. They were in `REDEMPTION_BUDGET_COSTS` in `features/economy.py`. The ticket was wrong; the code was checked, and the fix landed correctly. Do this every time.

**Documented an unimplemented feature.** #55's `/economy-help` asserted the budget resets monthly while #16 was still open and it did not. Aspiration got written as fact.

## Working through a change

1. Identify what actually changed. Read the diff, not the ticket.
2. Determine which feature areas the change touches. Behavior often crosses areas, especially anything involving boosters, channel restrictions, or the ticket lifecycle.
3. Grep for the old value across `README.md`, `docs/`, and the help command files. This finds the numeric occurrences.
4. Read the prose around each hit. The same fact gets restated in wording that grep will not match, and those restatements are where errors survive.
5. Update each hit against the code.
6. For anything you write about a command, read that command's implementation. Signature, permission gate, whether it is a slash or prefix command, and what it actually does on the failure path.

## Watch for

- **Numbers in worked examples.** Prices, thresholds, percentages, cooldowns. Prose gets updated and the example below it does not.
- **Percentages that shifted more than once.** The booster passive bonus has been 2%, then 5%, then ~10%. Old figures survive in places nobody looked.
- **Channel restrictions.** Token earning, XP, quest progress, and daily message counting have each been gated and un-gated repeatedly. They no longer share identical rules, so state each one from its own code.
- **Permission gates.** Several commands ship broader or narrower than their ticket specified. Document what the check does, not what the ticket asked for.
- **Removed commands.** `!lock` and `!unlock` were removed in #333 but survive as internal helpers. Not user-facing, so they belong in `docs/` if anywhere, never in a help embed.

## Before finishing

- Every changed fact updated on every surface that states it.
- Every command mentioned verified against its implementation.
- No worked example still carrying a superseded number.
- Version string matching between `pyproject.toml` and `README.md`.
- Nothing documented that is not actually implemented.