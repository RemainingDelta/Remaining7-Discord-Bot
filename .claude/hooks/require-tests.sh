#!/bin/bash
# PreToolUse gate: block edits to implementation files until the branch has test changes.
#
# Rationale: tests written after the implementation are written *from* the
# implementation. They restate what the code does and pass regardless of whether
# the behavior is correct. This hook forces the order.
#
# Bypass for a single session: SKIP_TEST_GATE=1 claude

set -uo pipefail

# --- read hook input ---------------------------------------------------------
input=$(cat)
file_path=$(jq -r '.tool_input.file_path // empty' <<<"$input")

# Not a file edit we care about. Stay silent; normal permission flow applies.
[[ -z "$file_path" ]] && exit 0

# --- escape hatches ----------------------------------------------------------
[[ "${SKIP_TEST_GATE:-}" == "1" ]] && exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Make the path relative to the project root so the patterns below match.
rel_path="${file_path#"$PWD"/}"

# --- which files are gated ---------------------------------------------------
# Implementation code only. Everything else passes untouched.
case "$rel_path" in
  features/config.py)  exit 0 ;;  # IDs and constants, nothing to test
  features/*|database/*) ;;       # gated
  *) exit 0 ;;                    # docs, tests, scripts, workflows, main.py
esac

# --- branch checks -----------------------------------------------------------
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0

# Not on a feature branch. Release and hotfix work on dev/main is out of scope.
case "$branch" in
  dev|main|HEAD) exit 0 ;;
esac

# Only gate ticket branches (392-Bug, 349-Feature, 382-Enhancement).
[[ "$branch" =~ ^[0-9]+-(Bug|Feature|Enhancement)$ ]] || exit 0

# --- does this branch touch tests? -------------------------------------------
base=$(git merge-base dev HEAD 2>/dev/null)

if [[ -n "$base" ]]; then
  committed=$(git diff --name-only "$base"...HEAD 2>/dev/null)
else
  committed=""
fi
staged=$(git diff --cached --name-only 2>/dev/null)
unstaged=$(git diff --name-only 2>/dev/null)
untracked=$(git ls-files --others --exclude-standard 2>/dev/null)

if printf '%s\n%s\n%s\n%s\n' "$committed" "$staged" "$unstaged" "$untracked" \
   | grep -qE '^tests/test_.*\.py$'; then
  exit 0
fi

# --- block -------------------------------------------------------------------
cat >&2 << 'MSG'
Blocked: no test changes on this branch yet.

Write the tests before the implementation. A test written afterwards is derived
from the code rather than from the ticket, so it passes whether or not the
behavior is correct.

Do this first:
  1. Read the ticket's Acceptance Criteria. That is the test list.
  2. Add or edit a file under tests/ (tests/test_<module>.py).
  3. Confirm the new tests fail.
  4. Then implement until they pass.

The write-tests skill covers deriving cases from a spec and the fixtures in
tests/conftest.py.

If tests genuinely do not apply here, restart with SKIP_TEST_GATE=1.
MSG
exit 2