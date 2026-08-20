---
name: new-cog
description: Cover the non-obvious footprint of adding a feature to the Remaining7 Discord bot: paired REAL/TEST config constants, the docs/ guide, the matching in-bot help embed, the ticket router, and the README tables. These surfaces are not reachable by exploring the code, so they get missed. Use this whenever adding a command, listener, background task, or feature area, and also when adding a single config ID, channel, role, or emoji, since those must go in both config branches or the feature silently fails on one server. Reach for this at the start of any new feature ticket, including during planning.
---

# New Cog

Exploring the codebase shows you the cog shape, `main.py` registration, and the `database/mongo.py` helper pattern. Those are discoverable and this skill does not belabor them.

What exploration does not surface is everything a new feature touches that nothing in the code points to, plus a handful of places where the existing code is a bad example.

## The surfaces nothing links to

### `features/config.py`, both branches

Every ID lives twice, once under `REAL` and once under `TEST`. Channels, roles, categories, emojis.

Adding to one branch only is the most common small mistake in this repo. #49 needed the Glowbert emoji in both. A missing value means the feature works on one server and breaks on the other, discovered at the worst time.

No hardcoded IDs in feature files.

### `docs/<AREA>.md`

An implementation guide matching the depth of the existing ones. New feature area means a new file; an extension means editing the existing one.

### The in-bot help embed

These live in code, which is why they get missed. A new command belongs in the help command matching its permission level:

| Command | File |
|---|---|
| `/help`, `/mod-help`, `/admin-help`, `/booster-perks` | `features/general.py` |
| `/economy-help` | `features/economy.py` |
| `/tourney-admin-help` | `features/tourney/tourney_commands.py` |
| `/event-staff-help` | `features/event.py` |

### `features/ticket_command_router.py`

New ticket types only. The router dispatches `!close` / `!delete` / `!reopen` per category and keeps the ticket systems isolated. A new ticket category without a router entry leaves those commands dead in its channels.

### `README.md`

Feature list, command list, plus the collection and background-task tables if the feature adds either.

### `tests/test_<name>.py`

Reuse the fixtures in `tests/conftest.py` rather than building new discord.py mocks. CI runs the suite on push.

## Where the existing code is a bad example

Reading this codebase for patterns will teach some habits worth avoiding. The prevailing pattern is not always the intended one.

**In-memory state.** The admin role's original name (#194), the slow-mode timer (#317), the previous cleanup warning (#318), ticket counters, per-user cooldowns, the support-channel lock timer. All held in memory, all lost on restart, all written up as review notes afterwards. Copying that shape is easy because it is everywhere. If state needs to outlive a restart, it goes in Mongo.

**Synchronous calls in async tasks.** #174 blocked the Discord heartbeat by calling `requests_cache` inside the match refresher. Use async clients, or `run_in_executor` where sync is unavoidable.

**Interactions that do work before deferring.** #3 was a run of `Unknown interaction` (10062) failures. Defer first, then work, then follow up. Plenty of handlers still do not.

**Views that die on restart.** A `discord.ui.View` does not survive a restart and its buttons return "Interaction Failed". #149 fixed this for support panels by reposting on startup; #35 hit the same class on supply drops. Decide explicitly whether a view needs to survive, and handle it if so.

**Members who have left.** #298: `!hacked` failed entirely when the target had left the server. Anything taking a user as input needs that path.

These are checks, not full treatments. Detailed review belongs to the code review pass, which runs after implementation.

## A quirk worth knowing

`get_user_data` self-heals users by force-creating a Brawl Stars starter document. Reading a balance creates a brawl profile. Expect it.

## Branch and workflow

Branch is `<issue-number>-<Type>`, matching the ticket, e.g. `390-Feature`. CI checks the branch number, PR title, and `Closes #N` in the body all agree, and that `pyproject.toml` was bumped on PRs into `main`. Feature branches merge into `dev`; `dev` merges into `main` for release.

`ruff check .` and `ruff format .` are enforced in CI. `make lint` and `make fix` are wired up.

## Before finishing

- Every new ID present in both the `REAL` and `TEST` config branches.
- No hardcoded IDs outside `config.py`.
- No state that needs to survive a restart living only in memory.
- Docs, README, and the relevant help embed updated.
- Router entry added if a new ticket type.
- Tests added; `make ci` clean.