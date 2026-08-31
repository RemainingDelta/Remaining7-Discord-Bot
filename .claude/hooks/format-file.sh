#!/bin/bash
# PostToolUse: format the Python file that was just written, and mark the tree
# dirty so the Stop hook knows to restart the bot.
#
# Deliberately `ruff format` and not `make fix`. `ruff check --fix` removes
# unused imports, and mid-edit-sequence an import is routinely written one edit
# before the line that uses it, so autofix deletes it and breaks the next edit
# (#351). Formatting is idempotent and safe to run on a half-written file;
# autofix is not. `ruff check --fix` runs from the Stop hook instead, once the
# edits are actually finished.

set -uo pipefail

file_path=$(jq -r '.tool_input.file_path // empty')

# Not a Python edit. Nothing to format, and the bot does not need a restart.
[[ "$file_path" == *.py ]] || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

touch /tmp/r7-files-changed
ruff format --quiet "$file_path"
