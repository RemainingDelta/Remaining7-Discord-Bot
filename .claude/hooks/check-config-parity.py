#!/usr/bin/env python3
"""Stop hook: fail the turn if features/config.py has unpaired REAL/TEST entries.

Every ID in this project lives twice, once for the production server and once for
the dev server. Adding it to only one branch is the most common small mistake in
the repo (#49 needed the Glowbert emoji in both). The failure is silent: the
feature works on one server and breaks on the other.

This runs when Claude finishes a turn rather than before an edit, so it never
interrupts work in progress. If it finds a gap it blocks the stop and hands the
message back so Claude fixes it before returning control.

Fails open: if the file cannot be parsed or the expected structure is not found,
it exits quietly rather than blocking every turn.
"""

import ast
import json
import os
import sys

CONFIG_PATH = "features/config.py"


def branch_names(node):
    """Names assigned directly inside an if/else arm."""
    names = set()
    for stmt in node:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
    return names


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = {}

    # Do not re-block a turn that is already the result of this hook blocking.
    if payload.get("stop_hook_active"):
        sys.exit(0)

    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    path = os.path.join(root, CONFIG_PATH)
    if not os.path.exists(path):
        sys.exit(0)

    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, OSError):
        sys.exit(0)

    problems = []

    # The top-level if/else splitting production and dev constants.
    for node in tree.body:
        if isinstance(node, ast.If) and node.orelse:
            a, b = branch_names(node.body), branch_names(node.orelse)
            if len(a) < 3 and len(b) < 3:
                continue  # too small to be the config split
            only_a, only_b = sorted(a - b), sorted(b - a)
            for name in only_a:
                problems.append(f"{name}: set in the first branch only")
            for name in only_b:
                problems.append(f"{name}: set in the second branch only")

    if not problems:
        sys.exit(0)

    shown = problems[:20]
    more = len(problems) - len(shown)

    print("Unpaired entries in features/config.py:", file=sys.stderr)
    for p in shown:
        print(f"  - {p}", file=sys.stderr)
    if more:
        print(f"  ... and {more} more", file=sys.stderr)
    print(
        "\nEvery ID needs a value in both the production and dev branches. "
        "A missing counterpart means the feature works on one server and "
        "breaks on the other, usually discovered during a live tournament.\n"
        "\nAdd the missing values, or if an entry is genuinely single-branch, "
        "say so and the check can be adjusted.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
