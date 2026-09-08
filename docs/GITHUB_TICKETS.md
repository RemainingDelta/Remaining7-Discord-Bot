# GitHub Tickets

## Overview
The GitHub Tickets feature lets staff generate a structured GitHub issue directly from a Discord support or tourney ticket. The bot reads the ticket's message history, sends it to the Gemini API with a classification prompt, and posts the result to the GitHub repository via the GitHub REST API.

---

## Trigger

The ticket creator (`TICKET_CREATOR_ID`) @-mentions the bot with a description of a bug, enhancement, or feature. The bot replies with a confirm/cancel prompt; on confirm the description goes to Gemini for classification and templating.

### Replying to a message

If the mention is a **reply**, the bot also reads the message being replied to and folds its contents into the ticket. This exists so a runtime error posted in `#bot-logs` can become an issue in one step, but it works on any message — reply to a bug report in `#general` and the ticket carries the reporter's own words.

What gets pulled in:

| From the replied-to message | Into the issue |
|---|---|
| `content` | Quoted as context for Gemini to classify from |
| Embeds (title, description, each field) | Same — an embed-only bot post has empty `content`, so this is where an error report actually lives |
| `.txt` / `.log` attachments under 20 KB (40 KB across all of them) | Inlined **verbatim** in a collapsible `<details>` block, bug tickets only |
| Image attachments | Filename only |
| — | A permanent `jump_url` link back to the Discord message |

Notes on why it works this way:

- **Logs are inlined, not linked.** Discord attachment URLs are signed and expire within about a day, so a linked log is dead by the time anyone reads the issue.
- **The traceback is appended after Gemini returns**, not passed through it. `call_gemini` authors the entire body, so anything routed through it comes back paraphrased rather than verbatim.
- **The branch placeholder is renamed before artifacts are appended**, so a log containing something like `-Bug` cannot be rewritten by the substitution.
- **Empty sections are omitted** rather than filled with a placeholder. This is also why the `Screenshots/Logs` heading no longer carries an `[if applicable]` marker — the section is simply absent when there is nothing to attach.
- A bare mention on a reply is enough; the replied-to message supplies the description.

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
- Reply context is collected by `collect_referenced_context()`; artifacts are attached by `append_context()`
- A deleted or unfetchable replied-to message is not fatal — the ticket is created from the typed notes alone
- Logic lives in `features/github_tickets.py`
- Tested in `tests/test_github_tickets.py`

---

## Source File
`features/github_tickets.py`
