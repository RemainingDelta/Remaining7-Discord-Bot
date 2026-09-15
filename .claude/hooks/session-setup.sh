#!/bin/bash
# SessionStart hook: pin the git hooks path and the git author identity so that
# commits made in any session (local or cloud) run the .githooks commit-msg
# backstop and are authored by RemainingDelta rather than the container default.
# Runs on startup|resume.
git config core.hooksPath .githooks
git config user.name "RemainingDelta"
git config user.email "146774012+RemainingDelta@users.noreply.github.com"
exit 0
