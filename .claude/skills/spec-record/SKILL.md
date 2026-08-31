---
name: spec-record
description: Write the as-implemented spec record section in docs/logs/SPECS.md for a release. Reads every issue merged since the last tag, compares each filed spec against the actual diff, and emits the release section with a reviewed verdict per issue. Use this whenever the user is preparing a release, mentions SPECS.md or the spec record, asks to document what shipped in a version, or is about to open a release PR — the SPECS section is written before the release PR opens, so reach for this skill any time a release is being cut, even if SPECS.md is not named directly.
---

# Spec Record

Write a release section for `docs/logs/SPECS.md`.

SPECS.md is a chronological, as-implemented record. It exists so the project's history survives outside GitHub: in a zip export, in an LLM context window, or in front of someone new who has no repo access. The point of the file is not to restate what shipped. Release notes and the CHANGELOG already do that. The point is **divergence tracking**: capturing where what shipped differed from what the ticket asked for, at the moment it happened, so nobody has to reverse-engineer it from a diff two years later.

Original tickets are never edited to match what shipped. As-implemented is the source of truth, and the gap between the two is the record.

## Scope

One invocation covers one release. Work the whole commit range at once, not issue by issue.

Do not write anything until every issue in the range has been read alongside its diff. Relationships between issues are where the best notes come from, and they are invisible one at a time:

- `#68` — the duplicate listener decorator this removed was introduced by the `#45` fix
- `#141` — this removed the capacity-warning system that the `#7` fix introduced in December 2025
- `#274` — this reversed the `#254` bump days later when the release was rescoped as a patch
- `#84` — this also restored production ticket limits, fixing `#69`'s leftover debug values

None of those are visible from a single ticket. Read the range first.

## Gathering the range

1. Find the previous tag and the commit range since it.
2. Scan the range for issue-branch references. Branches follow `<issue-number>-<Type>`, e.g. `377-Bug`, `382-Enhancement`.
3. For each issue number, pull the issue body from GitHub and the commits that closed it.
4. For each issue, read the actual diff. Not the commit message, not the PR description, the diff.

If a number appears in commits but has no matching GitHub issue, do not guess at it. Record it as skipped:

```
- **#108** — referenced by commits in this range but no matching GitHub issue found (possibly a PR number or deleted issue); skipped.
```

## Entry format

Use this exact structure. Note the file uses em dashes in its headers; that is the established format and stays, even though the surrounding prose does not use them.

```
### v<major>.<minor>.<patch> — YYYY-MM-DD

#### #<number> — <issue title verbatim> (<GitHub template type>)

> <issue body, quoted, truncated with …(truncated)>

Implemented in `<sha>`. Files: `path/one.py`, `path/two.py`

<verdict line>

<optional review note>
```

Details that matter:

- The issue title is copied verbatim, including its own `Bug:` / `Feature:` / `Enhancement:` prefix. The parenthetical afterwards is the GitHub template type, which sometimes disagrees with the title. Keep the disagreement. `#114` is filed as `Enhancement: ... (Bug)` and that mismatch is real information.
- Quote enough of the issue body to show what was actually asked for, especially Technical Requirements and Acceptance Criteria. Cut with `…(truncated)` mid-sentence rather than trimming to a clean boundary.
- Multiple commits are comma-separated: ``Implemented in `013339e`, `473cc3b`, `8b72088`.``
- When the closing branch touched no files that survived, write `Files: (none)`.
- If the commit is not yet made, use a placeholder and say so: `` `<pending — set to the 382-Enhancement doc commit sha once committed>` ``.

## Verdicts

Every entry carries exactly one verdict line. Pick from three.

**Matches the spec:**

```
✅ Reviewed against the diff: implementation matches the filed spec.
```

**Diverges.** Use when the shipped behavior differs from what the ticket specified. Name the difference concretely; a reader should not need the diff to understand what changed.

```
⚠️ as-implemented differs from #200: the issue's Notes explicitly said to keep the
description-substring matching pattern "for consistency"; the implementation instead
introduced a proper quest_category schema field and a four-slot quest model
(daily/weekly × message/megabox), eliminating the fragile matching entirely — plus an
unspecced /reset-quests admin command.
```

**Review note.** Attaches to either verdict above. Use for things worth knowing that fall short of a divergence: a spec detail satisfied differently, an accepted edge case, a known limitation, a relationship to another issue.

```
📝 Review note: The timer is in-memory — a bot restart during the hour cancels the auto-disable.
```

### Choosing between ⚠️ and 📝

The question is whether a reader who knew only the ticket would be surprised by the code.

- Scope grew beyond what was filed → ⚠️ (`#7` asked not to crash on close; a whole capacity-management layer shipped)
- A specced feature was silently dropped → ⚠️ (`#82`'s headline latency diagnostic was never implemented)
- The approach changed → ⚠️ (`#69` specced BeautifulSoup scraping; the code hits the JSON API directly)
- The spec was wrong and the code is right → ⚠️ with the reasoning (`#167`: the spec demanded 9 timestamp formats, but only 7 exist in Discord)
- Cosmetic difference from an example in the ticket → 📝 (`#43` shipped 4 items per page where the issue suggested 5)
- Implementation detail the ticket did not constrain → 📝
- Unverifiable acceptance criterion → 📝 (`#50` claims all 98 brawlers were audited; the diff shows ~22 lines changed)

When genuinely unsure, prefer ⚠️. A false divergence costs a sentence. A missed one costs the whole reason the file exists.

Never write a verdict without reading the diff. `✅` asserts a review happened.

## Things to look for

These recur in this codebase and are worth checking every time:

- **In-memory state that dies on restart.** Timers, counters, cached role names, cooldowns. Note it.
- **Synchronous calls inside async tasks.** Blocking the event loop has caused real outages here.
- **Bundled unrelated changes.** A version bump, a rename sweep, or a debug value quietly shipped inside a bug fix. Always a ⚠️.
- **Test or debug values reaching production.** `#69` shipped a 0.6-second cooldown that stood until `#84`.
- **Self-referential entries.** A doc ticket that wrote its own SPECS section should say so.

## Version bumps

Version-bump-only issues get one line, not a full entry. They carry no spec and no divergence, and full entries for them bury the ones that matter. Collapse them:

```
#### #381 — Enhancement: Bump project version to v1.11.1 (Enhancement)

Version bump only. Implemented in `3fce9b0`.
```

If a bump did something else too (reversing an earlier bump, changing where the version is read from), it earns a real entry.

## Before finishing

- Every issue in the commit range has an entry or an explicit skip line.
- Every entry has exactly one verdict.
- Every `⚠️` names the specific difference, not just that one exists.
- Cross-issue relationships in this range are captured.
- The section is appended in chronological order, below the previous release.

SPECS.md is one of several surfaces. The CHANGELOG gets release notes and PR descriptions; the two serve distinct roles and should not be filled with the same text. If the release also needs CHANGELOG entries, that is separate work.