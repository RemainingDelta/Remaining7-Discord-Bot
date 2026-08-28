#!/bin/bash
# SessionStart hook: pin the git hooks path and author identity so commits made
# in any session (local or cloud) carry the right author and run the commit-msg
# backstop. Runs on startup|resume.
git config core.hooksPath .githooks
git config user.name "RemainingDelta"
git config user.email "146774012+RemainingDelta@users.noreply.github.com"
exit 0
