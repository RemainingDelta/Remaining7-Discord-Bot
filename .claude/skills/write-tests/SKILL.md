---
name: write-tests
description: Write pytest tests for the Remaining7 Discord bot by deriving cases from the ticket's acceptance criteria rather than from the code. Covers what a test worth keeping looks like, the bug classes this codebase actually produces, and the discord.py fixtures in tests/conftest.py. Use this whenever adding or changing tests, starting a feature or bug ticket, or when a test gate blocks an edit. Reach for it before implementation begins, since a test derived from finished code proves only that the code agrees with itself.
---

# Write Tests

## Where cases come from

Derive them from the ticket, not from the code.

This matters because a test written from an implementation restates what the implementation does. It passes on day one and keeps passing after a regression, since the behavior it encodes is the behavior it was copied from. A test derived from the Acceptance Criteria is evidence the spec was met.

The practical consequence: read the ticket before writing, and write before implementing. If the implementation already exists, still derive from the ticket rather than reading the code first. Tests that fail against existing code are the valuable ones. That is a bug found, not a broken test.

Acceptance Criteria map to tests close to one-to-one. Take #280:

> - [ ] Messages in `BOT_COMMANDS_CHANNEL_ID` do not earn passive tokens or XP
> - [ ] Messages in `ECONOMY_COMMANDS_CHANNEL_ID` do not earn passive tokens or XP
> - [ ] Messages in all other eligible channels are unaffected

Three criteria, three tests. The third is the one that matters most and the one most often skipped. Restriction tickets are where over-correction hides: blocking the two named channels and accidentally blocking everything looks identical from the first two tests alone. A criterion phrased as "other cases unaffected" is asking for a negative test.

**Criteria that contradict themselves.** #202's acceptance criterion said to source `max_round` from `totalRounds`, and the ticket's own Notes then explained why that was wrong. The Notes approach shipped. Resolve the contradiction before writing, because the test encodes whichever reading you pick.

**Criteria that cannot be verified.** #50 demanded all 98 brawlers be matched 1:1 against the wiki. A test can check the file's shape, that required fields exist, that no placeholder names remain. It cannot check the data against an external source. Say which criteria are untestable rather than writing something that only appears to cover them.

**Criteria that hide several cases.** "Boosters get reduced quest thresholds" is four tests, one per quest type, plus a non-booster control.

## What a test worth keeping looks like

**Assert on behavior, not on rendering.** A balance of 1500 after a purchase is behavior. The embed field being titled "Balance After" is rendering that will change and break the test for nothing. #54 and #299 were both display-formatting bugs, so display is sometimes the behavior under test. Be deliberate about which you are asserting.

**Test the boundary, not the middle.** A 20-second cooldown needs 19 and 21, not 5 and 300. The 5-message `/daily` requirement needs 4 and 5. Off-by-one is the failure mode and the middle of the range never finds it.

**Mock the edges, run the logic.** Mock Discord and Mongo. Do not mock the function under test or the branch you care about. A test that mocks until nothing real executes passes unconditionally, which is the same as no test.

**One reason to fail per test.** When it breaks, the name should say what broke. `test_booster_gets_reduced_quest_threshold` is useful. `test_quests` is not.

**A test that cannot fail is not a test.** Before moving on, break the implementation deliberately and confirm the test catches it. This is the single best check against a test that was accidentally written to agree with the code.

## Bug classes this codebase produces

Cover these when the feature touches them. Each has shipped at least once.

- **Off-by-one and boundary math.** Round numbers inflated by BYEs (#202), API IDs versus visible match numbers (#113), cooldown thresholds, quest targets.
- **Two things that look alike.** The grand final and the consolation match both look final, so winner detection announced third place (#156).
- **Missing or placeholder data.** TBD and BYE slots silently skipped instead of shown as waiting on a prerequisite (#198).
- **Channel and permission gating.** Earning, XP, quests, and daily counting were each gated separately and no longer share rules. Test each independently (#279, #280, #301, #353).
- **The absent user.** Commands failing when the target left the server (#298).
- **Float display.** Balances rendering as `12182.699999999997` (#54, #299).
- **State after a restart.** If something must survive a restart, assert it is written to Mongo rather than held in memory.
- **Duplicate work.** Double listener registration caused double level-up messages (#68); a race produced duplicate dashboards (#128).

## Practicalities

`pytest` with `pytest-asyncio`. Run with `make test`, or `make ci` for the full lint-and-test pass. CI runs the suite on push.

Reuse the fixtures in `tests/conftest.py` rather than building new discord.py mocks. The existing test modules show the patterns: mocked interactions, members with role lists, `guild.get_channel`, async cog listeners, and `aiohttp.ClientSession` mocking for the Gemini and GitHub calls (#233).

There is no live-bot harness. Anything needing a real gateway connection is verified by running with `BOT_MODE=DEV` against the test server, not by a test. Say so plainly instead of writing a test that mocks the whole path and proves nothing.

Name files `tests/test_<module>.py`, matching the module under test.

## Before finishing

- Every Acceptance Criterion has a test, or is explicitly called out as untestable.
- Negative cases covered wherever a restriction was added.
- Boundaries tested at the edge, not the middle.
- Each test fails for exactly one reason and is named for it.
- Each new test was confirmed to fail when the behavior is broken.
- `make ci` clean.