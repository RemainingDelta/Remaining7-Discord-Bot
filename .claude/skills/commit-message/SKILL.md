---
name: commit-message
description: Generate a single-line commit message based on the current branch and staged changes
disable-model-invocation: true
---

Generate a commit message for the current staged changes.

## Instructions

1. Run `git branch --show-current` to get the current branch name.

2. Run `git diff --cached --stat` to check if anything is staged.
   - If nothing is staged, fall back to `git diff HEAD` instead.
   - If there are no changes at all (neither staged nor unstaged vs HEAD), warn the user: "No changes found." and stop.

3. Run `git diff --cached` (or `git diff HEAD` if nothing was staged) to read the diff in full.

4. Generate a single-line commit message in this exact format:
   ```
   <branch-name> <action-verb> <short description>
   ```
   - `<branch-name>` is the exact branch name from step 1
   - `<action-verb>` is one present-tense verb: `add`, `fix`, `update`, `remove`, `refactor`, `rename`, `move`, `improve`
   - `<short description>` is a concise description of what changed (no period at end)

5. Output only the commit message — no explanation, no prose, no code block wrapping.

## Example output
```
266-Feature add commit message slash command
```
