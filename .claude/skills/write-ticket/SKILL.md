---
name: write-ticket
description: Draft a GitHub issue ticket (bug, enhancement, or feature) using the project's templates
disable-model-invocation: true
---

Draft a GitHub issue ticket based on: $ARGUMENTS

## Instructions

1. Determine the ticket type from the user's description:
   - **Bug** — something that is broken or behaving incorrectly
   - **Enhancement** — an improvement to an existing feature
   - **Feature** — a new capability that doesn't exist yet
   - If unclear, ask the user which type before proceeding.

2. Read the matching template from this skill's `references/` folder:
   - `references/bug-template.md`
   - `references/enhancement-template.md`
   - `references/feature-template.md`

3. Fill in the template using the user's description. Follow these rules:
   - Keep it concise and practical — no filler text
   - Do NOT mention the bot name in bug tickets
   - Bug tickets describe broken existing behavior; enhancement tickets describe new/improved behavior — do not mix these up
   - The branch name at the bottom should be a short kebab-case descriptor (e.g., `fix-ticket-close-error`)
   - Output the completed ticket as a markdown code snippet wrapped in triple backticks

4. If the user provides minimal context, fill in what you can and mark anything uncertain with `[TODO]` so they can fill it in.