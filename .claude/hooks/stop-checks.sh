#!/bin/bash
# Stop hook: verify config parity, then restart the bot if anything changed.
#
# These are chained rather than registered as two separate hooks because hooks in
# the same event run in parallel. Run separately, the bot would restart while the
# parity check was still failing, boot with a missing ID, and need a second
# restart after the fix.

set -uo pipefail

input=$(cat)
PROJECT_DIR="${CLAUDE_PROJECT_DIR}"

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

# --- 2. restart the bot ------------------------------------------------------
[ -f /tmp/r7-files-changed ] || exit 0
rm -f /tmp/r7-files-changed
[ -f /tmp/claude-no-restart ] && exit 0

cd "$PROJECT_DIR" || exit 1

[ -f /tmp/r7-bot.pid ] && kill "$(cat /tmp/r7-bot.pid)" 2>/dev/null
rm -f /tmp/r7-bot.pid
sleep 1

nohup .venv/bin/python -u main.py </dev/null >> /tmp/r7-bot.log 2>&1 &
echo $! > /tmp/r7-bot.pid

exit 0