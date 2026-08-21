#!/bin/bash
# Stop hook: verify config parity, apply lint autofixes, restart the bot.
#
# These are chained rather than registered as two separate hooks because hooks in
# the same event run in parallel. Run separately, the bot would restart while the
# parity check was still failing, boot with a missing ID, and need a second
# restart after the fix.

set -uo pipefail

input=$(cat)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# --- 1. config parity --------------------------------------------------------
# Blocks the stop on an unpaired REAL/TEST entry. No restart happens, so the bot
# keeps running the last known-good config while Claude fixes the gap.
if [ -x "$PROJECT_DIR/.claude/hooks/check-config-parity.py" ]; then
  parity_err=$(printf '%s' "$input" | "$PROJECT_DIR/.claude/hooks/check-config-parity.py" 2>&1 >/dev/null)
  parity_code=$?
  if [ "$parity_code" -eq 2 ]; then
    printf '%s\n' "$parity_err" >&2
    exit 2
  fi
fi

# --- 2. lint autofix ---------------------------------------------------------
# `ruff check --fix` lives here rather than in the PostToolUse hook: it deletes
# unused imports, which mid-edit-sequence means deleting an import that the next
# edit was about to use (#351). By the time the turn ends the edits are done, so
# this is the safe moment to run it. Non-blocking; violations ruff cannot fix
# automatically are surfaced but do not hold up the stop.
#
# `ruff check --fix` and not `make fix`: make fix also runs `ruff format .` over
# the whole tree, and ruff formats Python blocks inside markdown, so it would
# rewrite unrelated docs/ files on every turn. Formatting is already handled
# per-file by the PostToolUse hook, scoped to what was actually edited.
cd "$PROJECT_DIR" || exit 1

if [ -f /tmp/r7-files-changed ]; then
  fix_out=$(ruff check --fix -q . 2>&1) || printf '%s\n' "$fix_out" >&2
fi

# --- 3. restart the bot ------------------------------------------------------
# Check the opt-out before consuming the marker, so a no-restart session leaves
# the "files changed" signal intact for the next turn instead of swallowing it.
[ -f /tmp/claude-no-restart ] && exit 0
[ -f /tmp/r7-files-changed ] || exit 0
rm -f /tmp/r7-files-changed

[ -f /tmp/r7-bot.pid ] && kill "$(cat /tmp/r7-bot.pid)" 2>/dev/null
rm -f /tmp/r7-bot.pid
sleep 1

nohup .venv/bin/python -u main.py </dev/null >> /tmp/r7-bot.log 2>&1 &
echo $! > /tmp/r7-bot.pid

exit 0