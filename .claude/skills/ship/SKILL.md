---
name: ship
description: Generate a commit message and PR description together for the current branch
disable-model-invocation: true
---

Generate a commit message and PR description for the current branch. $ARGUMENTS

This skill generates text only — it does NOT commit, push, or open a PR. The one exception is the branch checkout in step 1 below.

## Instructions

1. Run `git branch --show-current` and make sure you are on the ticket branch before generating anything.
   - A ticket branch is named `<number>-<Type>` (e.g. `404-Enhancement`, `390-Bug`), matching the issue being worked on.
   - If already on a ticket branch, continue to step 2.
   - If on a base branch (`dev` or `main`), switch to the ticket branch first, carrying any uncommitted working-tree changes with you:
      - Determine the ticket branch name from the issue/spec being worked on. If it is not clear from context, ask the user for the ticket number and type before proceeding.
      - Pull latest `dev`, then branch from it: `git checkout dev && git pull && git checkout -b <ticket-branch>` (uncommitted changes follow you onto the new branch).
      - Do NOT commit the changes — just move onto the correct branch and leave them in the working tree.

2. Run `git diff --cached --stat` to check if anything is staged.
   - If nothing is staged, fall back to `git diff HEAD` instead.
   - If there are no changes at all, warn the user: "No changes found." and stop.

3. Run `git diff --cached` (or `git diff HEAD` if nothing was staged) to read the diff in full.

4. Output a **commit message** in this exact format (no explanation, no code block):

- `<branch-name>` is the exact branch name
- `<action-verb>` is one present-tense verb: `add`, `fix`, `update`, `remove`, `refactor`, `rename`, `move`, `improve`
- `<short description>` is concise (no period at end)

5. Then output a **PR description** as a markdown code block:
Changes

- <what changed and why, one bullet per logical change>

   Closes #
Rules:
- One bullet per logical change
- Lead with action verb: Fixed, Added, Updated, Removed
- Mention the command, file, or system if it adds clarity
- Keep it short — no headers beyond `### Changes` 
- ALWAYS include `Closes #<number>` at the end

## Example output

**Commit message:**
266-Feature add commit message slash command

**PR description:**
\```
### Changes
* Added `/commit-message` skill that generates a single-line commit message from the current branch name and staged diff

Closes #266
\```