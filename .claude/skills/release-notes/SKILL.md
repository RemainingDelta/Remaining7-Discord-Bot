---
name: release-notes
description: Draft release notes for a new version using the project's release notes format
disable-model-invocation: true
---

Draft release notes based on: $ARGUMENTS

## Instructions

1. Read the release notes guide at `references/release-guide.md` for the exact format and conventions.

2. Gather the version info from the user's input. Expect either:
   - A version number and list of changes, OR
   - A request to look at recent commits/PRs to determine changes

3. If the user asks you to look at commits, use `git log` between the previous tag and HEAD to gather changes. Identify the previous tag with `git describe --tags --abbrev=0`.

4. Build the release notes following the template format:
   - Title: `# 🚀 Release Notes v<version>`
   - Use only the sections that apply — drop empty sections entirely
   - 🎯 Features should highlight the most impactful changes first
   - Bug fixes: describe what was wrong and what was done, in plain language
   - End with the Full Changelog comparison link using the repo URL and previous tag → new tag

5. Determine the correct version bump from `references/release-guide.md`:
   - Patch: bug fixes, small enhancements
   - Minor: new features or meaningful additions
   - Major: large rewrites or breaking changes

6. Remind the user to bump `BOT_VERSION` in `features/config.py` if they haven't already.

7. Output the release notes as a markdown code snippet wrapped in triple backticks.