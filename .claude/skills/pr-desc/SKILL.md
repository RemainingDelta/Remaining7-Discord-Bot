---
name: pr-desc
description: Draft a PR description for merging a branch into main
disable-model-invocation: true
---

Draft a PR description based on: $ARGUMENTS

## Instructions

1. Read the PR description guide at `references/pr-guide.md` for the exact format.

2. Gather change info from the user's input. Expect either:
   - A list of what changed, OR
   - A request to look at the branch diff

3. If the user asks you to look at the diff, run:
   - `git log main..HEAD --oneline` to see commits on the current branch
   - `git diff main --stat` to see files changed
   - Read changed files if needed for context

4. Build the PR description following the format:
   ```
   ### Changes
   * <what changed and why, one bullet per logical change>

   Closes #<branch number, ex. for 279-Bug, it would be Closes #279>
   ```

5. Rules:
   - VERY IMPORTANT:Don't forget the "Closes #" at the end 
   - One bullet per ticket/branch merged
   - Lead with the action verb: Fixed, Added, Updated, Removed
   - Mention the command, file, or system affected if it adds clarity
   - Keep it short — no overviews, no headers beyond `### Changes`
   - Output as a markdown code snippet wrapped in triple backticks
