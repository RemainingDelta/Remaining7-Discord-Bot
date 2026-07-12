# GitHub Tickets

## Overview
The GitHub Tickets feature lets staff generate a structured GitHub issue directly from a Discord support or tourney ticket. The bot reads the ticket's message history, sends it to the Gemini API with a classification prompt, and posts the result to the GitHub repository via the GitHub REST API.

---

## Trigger

A staff member runs a command (slash or prefix) inside an active ticket channel. The bot reads the full channel message history, formats it as a conversation log, and sends it to Gemini for classification and summarization.

---

## Gemini Classification

The bot sends a prompt to Gemini that includes the raw conversation and asks it to:
1. Classify the issue type: **Bug**, **Enhancement**, or **Feature**
2. Fill in the appropriate template

### Bug Template Fields
- Title
- Acceptance criteria (what "fixed" looks like)
- Steps to reproduce
- Expected vs actual behavior
- Impact level (Low / Medium / High / Critical)
- Labels: `bug`

### Enhancement Template Fields
- Title
- Current behavior
- Proposed behavior
- Technical requirements
- Labels: `enhancement`

### Feature Template Fields
- Title
- Overview (1-paragraph summary)
- Full description
- Labels: `feature`

Gemini returns structured text that the bot parses into a GitHub issue body.

---

## GitHub Issue Creation

Once Gemini returns the structured issue content, the bot POSTs to the GitHub API:

```
POST https://api.github.com/repos/{GITHUB_REPO}/issues
Authorization: Bearer {GITHUB_TOKEN}
Content-Type: application/json

{
  "title": "...",
  "body": "...",
  "labels": ["bug"]
}
```

On success, the bot replies in the ticket with the URL to the created issue.

---

## Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_TOKEN` | Gemini API key for AI summarization |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` scope |
| `GITHUB_REPO` | Repository in `owner/repo` format |

---

## Notes
- The bot must have permission to create issues on the target repository
- The `GITHUB_TOKEN` needs `repo` scope (not just `public_repo`) if the repo is private
- If Gemini classification fails or the issue type is ambiguous, the bot falls back to a generic template
- Logic lives in `features/github_tickets.py`
- Tested in `tests/test_github_tickets.py`

---

## Source File
`features/github_tickets.py`
