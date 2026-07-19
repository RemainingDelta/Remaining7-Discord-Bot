#!/usr/bin/env python3
"""Generate Part 3 of logs/SPECS.md and PR-description sections of logs/CHANGELOG.md.

Pulls releases, walks the commit range of each release to find issue-branch
references (e.g. "42-Bug", "42-Enhancement"), fetches each issue's spec from
GitHub, diffs the fixing commits, and flags file-level divergences between the
issue text and what the implementation actually touched.

Appends only: the Part 3 stub in SPECS.md is filled in, and PR descriptions
are inserted into existing CHANGELOG.md release sections. Nothing already
written is removed. Safe to re-run: aborts if output already present.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS_PATH = ROOT / "logs" / "SPECS.md"
CHANGELOG_PATH = ROOT / "logs" / "CHANGELOG.md"

PART3_STUB = "*(To be filled in.)*"
PART3_HEADING = "## Part 3 — Tracked (January 31, 2026 onwards)"

# Branch-name convention: <issue>-<Type>, appearing in commit subjects and
# merge-commit branch refs ("Merge pull request #36 from Org/35-Bug").
ISSUE_PAT = re.compile(r"\b(\d{1,4})-(Bug|Enhancement|Feature)\b", re.IGNORECASE)

# Files whose presence in a fix commit is routine and never worth flagging.
ANCILLARY_EXACT = {
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    "Makefile",
    ".gitignore",
    "pytest.ini",
    "CLAUDE.md",
}
ANCILLARY_PREFIXES = ("docs/", "tests/", ".github/", "logs/", "scripts/")

# Feature-file aliases: a touched file counts as "mentioned" in the issue if
# any of its keywords appear in the issue title/body.
FILE_KEYWORDS = {
    "economy": [
        "token",
        "shop",
        "balance",
        "daily",
        "budget",
        "redeem",
        "buy",
        "leaderboard",
        "drop",
        "economy",
        "xp",
        "level",
    ],
    "mongo": ["database", "mongo", "db", "collection", "schema"],
    "security": ["hacked", "security", "timeout", "purge", "scam"],
    "quests": ["quest"],
    "event": ["event", "cleanup", "clear-", "poll"],
    "config": ["config", "channel", "role", "price", "id"],
    "general": [
        "help",
        "version",
        "translate",
        "sticky",
        "count",
        "convert-time",
        "booster",
        "repost",
        "general",
    ],
    "translation": ["translate", "translation", "language"],
    "main": ["startup", "load", "cog", "main"],
}
TOURNEY_KEYWORDS = [
    "tourney",
    "ticket",
    "tournament",
    "matcherino",
    "bracket",
    "payout",
    "blacklist",
    "queue",
    "match",
    "transcript",
    "panel",
    "close",
    "reopen",
    "sticky",
    "milestone",
]
BRAWL_KEYWORDS = [
    "brawl",
    "megabox",
    "mega box",
    "starr",
    "brawler",
    "gadget",
    "star power",
    "hypercharge",
    "credits",
]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def fetch_releases() -> list[dict]:
    res = run(
        ["gh", "release", "list", "--limit", "50", "--json", "tagName,publishedAt,name"]
    )
    if res.returncode != 0:
        sys.exit(f"gh release list failed: {res.stderr}")
    releases = json.loads(res.stdout)
    releases.sort(key=lambda r: r["publishedAt"])
    return releases


def fetch_all_issues() -> dict[int, dict]:
    """One bulk fetch instead of per-issue gh calls; only real issues returned."""
    res = run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,title,body,state",
        ]
    )
    if res.returncode != 0:
        sys.exit(f"gh issue list failed: {res.stderr}")
    return {i["number"]: i for i in json.loads(res.stdout)}


def fetch_main_prs() -> list[dict]:
    res = run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--base",
            "main",
            "--limit",
            "200",
            "--json",
            "number,title,body,mergedAt",
        ]
    )
    if res.returncode != 0:
        sys.exit(f"gh pr list failed: {res.stderr}")
    prs = json.loads(res.stdout)
    prs.sort(key=lambda p: p["mergedAt"])
    return prs


def commits_in_range(prev_tag: str | None, tag: str) -> list[tuple[str, str]]:
    ref = f"{prev_tag}..{tag}" if prev_tag else tag
    res = run(["git", "log", ref, "--oneline", "--no-color"])
    out = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        out.append((sha, subject))
    return out


def files_touched(sha: str) -> list[str]:
    res = run(["git", "show", sha, "--name-only", "--format="])
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]


def diff_stat(sha: str) -> str:
    res = run(["git", "show", sha, "--stat", "--format=", "--no-color"])
    return res.stdout.strip()


def keywords_for(path: str) -> list[str]:
    stem = Path(path).stem.lower()
    if path.startswith("features/tourney/"):
        return TOURNEY_KEYWORDS
    if path.startswith("features/brawl/"):
        return BRAWL_KEYWORDS
    return FILE_KEYWORDS.get(stem, [stem])


def find_divergences(issue_text: str, files: list[str]) -> list[str]:
    """File-level heuristic: code files the fix touched that the issue never
    references (directly or via feature keywords)."""
    text = issue_text.lower()
    flagged = []
    for f in files:
        if f in ANCILLARY_EXACT or f.startswith(ANCILLARY_PREFIXES):
            continue
        if f.endswith(".md"):
            continue
        if any(kw in text for kw in keywords_for(f)):
            continue
        flagged.append(f)
    return flagged


def clean_body(body: str, limit: int = 700) -> str:
    body = body or "(no body)"
    body = re.sub(r"<img[^>]*>", "[image]", body)
    body = re.sub(r"```.*?```", "[code block omitted]", body, flags=re.DOTALL)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > limit:
        body = body[:limit].rstrip() + " …(truncated)"
    return body


def build_part3(releases, issues_by_num) -> tuple[str, int, int]:
    lines = ["<!-- generated:part3 by scripts/generate_specs.py -->", ""]
    lines.append(
        "This part is generated from GitHub data by `scripts/generate_specs.py`: "
        "for each release, the commit range since the previous tag is scanned for "
        "issue-branch references, each issue's filed spec is quoted, and the fixing "
        "commits' file lists are compared against the issue text. Divergence flags "
        "are file-level heuristics — a flagged file means the implementation touched "
        "code the issue never mentioned, which may warrant a closer manual look."
    )
    lines.append("")

    issues_processed = 0
    divergences_flagged = 0
    prev_tag = None

    for rel in releases:
        tag = rel["tagName"]
        date = rel["publishedAt"][:10]
        lines.append(f"### {tag} — {date}")
        lines.append("")

        if prev_tag is None:
            lines.append(
                "Catch-up tag over the full pre-release history. Issues fixed "
                "before this release are covered narratively in Part 2 and are "
                "not re-listed here."
            )
            lines.append("")
            prev_tag = tag
            continue

        commits = commits_in_range(prev_tag, tag)
        issue_commits: dict[int, list[tuple[str, str]]] = {}
        issue_types: dict[int, str] = {}
        for sha, subject in commits:
            for m in ISSUE_PAT.finditer(subject):
                num = int(m.group(1))
                issue_types.setdefault(num, m.group(2).capitalize())
                # Merge commits reference the branch; prefer real work commits
                # for diffing but keep merges as fallback.
                issue_commits.setdefault(num, []).append((sha, subject))

        if not issue_commits:
            lines.append(
                "No issue-tracked changes detected in this release's commit range."
            )
            lines.append("")
            prev_tag = tag
            continue

        for num in sorted(issue_commits):
            issue = issues_by_num.get(num)
            if issue is None:
                lines.append(
                    f"- **#{num}** — referenced by commits in this range but no "
                    f"matching GitHub issue found (possibly a PR number or "
                    f"deleted issue); skipped."
                )
                lines.append("")
                continue

            issues_processed += 1
            itype = issue_types.get(num, "")
            work = [
                (s, subj)
                for s, subj in issue_commits[num]
                if not subj.startswith("Merge ")
            ]
            chosen = work or issue_commits[num]

            all_files: list[str] = []
            for sha, _ in chosen:
                for f in files_touched(sha):
                    if f not in all_files:
                        all_files.append(f)

            shas = ", ".join(f"`{s}`" for s, _ in chosen)
            lines.append(f"#### #{num} — {issue['title']} ({itype})")
            lines.append("")
            for quoted in clean_body(issue["body"]).splitlines():
                lines.append(f"> {quoted}" if quoted else ">")
            lines.append("")
            lines.append(
                f"Implemented in {shas}. Files: "
                + (", ".join(f"`{f}`" for f in all_files) or "(none)")
            )

            issue_text = f"{issue['title']}\n{issue['body'] or ''}"
            flagged = find_divergences(issue_text, all_files)
            if flagged:
                divergences_flagged += 1
                flist = ", ".join(f"`{f}`" for f in flagged)
                lines.append("")
                lines.append(
                    f"⚠️ as-implemented differs from #{num}: the fix touches "
                    f"{flist}, not referenced in the issue."
                )
            lines.append("")

        prev_tag = tag

    return "\n".join(lines), issues_processed, divergences_flagged


def build_changelog_insertions(releases, prs) -> dict[str, str]:
    """tag -> markdown block of PR descriptions merged in that release window."""
    insertions: dict[str, str] = {}
    prev_pub = None
    for rel in releases:
        tag = rel["tagName"]
        pub = rel["publishedAt"]
        window = [
            p
            for p in prs
            if (prev_pub is None or p["mergedAt"] > prev_pub) and p["mergedAt"] <= pub
        ]
        prev_pub = pub
        if not window:
            continue
        parts = ["", "### PR Descriptions", ""]
        for p in window:
            parts.append(
                f"#### PR #{p['number']} — {p['title']} (merged {p['mergedAt'][:10]})"
            )
            parts.append("")
            body = (p["body"] or "").replace("\r\n", "\n").strip()
            parts.append(body if body else "*(no description)*")
            parts.append("")
        insertions[tag] = "\n".join(parts)
    return insertions


def apply_specs(part3_md: str) -> None:
    text = SPECS_PATH.read_text(encoding="utf-8")
    if "generated:part3" in text:
        sys.exit(
            "SPECS.md already contains generated Part 3 — aborting to avoid duplication."
        )
    stub_block = f"{PART3_HEADING}\n\n{PART3_STUB}"
    if stub_block not in text:
        sys.exit(
            "Part 3 stub not found in SPECS.md — refusing to guess where to append."
        )
    text = text.replace(stub_block, f"{PART3_HEADING}\n\n{part3_md}", 1)
    SPECS_PATH.write_text(text, encoding="utf-8")


def apply_changelog(insertions: dict[str, str]) -> int:
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    if "### PR Descriptions" in text:
        sys.exit(
            "CHANGELOG.md already contains PR Descriptions — aborting to avoid duplication."
        )

    header_pat = re.compile(r"^## (v[\d.]+) — ", re.MULTILINE)
    headers = list(header_pat.finditer(text))
    inserted = 0
    # Walk backwards so earlier insert positions stay valid.
    for i in range(len(headers) - 1, -1, -1):
        tag = headers[i].group(1)
        block = insertions.get(tag)
        if not block:
            continue
        start = headers[i].start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[start:end]
        # The section's trailing divider is the last "\n---" before the next header.
        div = section.rfind("\n---")
        if div == -1:
            insert_at = end
        else:
            insert_at = start + div
        text = text[:insert_at] + "\n" + block + text[insert_at:]
        inserted += 1
    CHANGELOG_PATH.write_text(text, encoding="utf-8")
    return inserted


def main() -> None:
    releases = fetch_releases()
    issues_by_num = fetch_all_issues()
    prs = fetch_main_prs()

    part3_md, n_issues, n_div = build_part3(releases, issues_by_num)
    apply_specs(part3_md)

    insertions = build_changelog_insertions(releases, prs)
    n_sections = apply_changelog(insertions)

    print(f"Releases scanned:        {len(releases)}")
    print(f"Issues processed:        {n_issues}")
    print(f"Divergences flagged:     {n_div}")
    print(
        f"PRs assigned:            {sum(len(v.splitlines()) and 1 for v in insertions.values())} release windows, "
        f"{len([p for p in prs])} PRs fetched"
    )
    print(f"CHANGELOG sections updated: {n_sections}")


if __name__ == "__main__":
    main()
