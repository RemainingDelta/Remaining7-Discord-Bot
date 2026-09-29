# GitHub Tickets

## Overview
The GitHub Tickets feature lets the ticket creator turn a Discord message, or a typed description, into a structured GitHub issue. The bot sends the text to the Gemini API with a classification prompt, and posts the result to the GitHub repository via the GitHub REST API.

---

## Trigger

Only the ticket creator (`TICKET_CREATOR_ID`) can file issues. There are two ways in.

### Right-click a message: "Create GitHub Issue" (primary)

Right-click any message, then **Apps → Create GitHub Issue**. A modal opens with one optional field for extra context. On submit, the bot shows an ephemeral Yes/No prompt; on Yes the original message plus the notes go to Gemini for classification and templating.

This is how to turn someone else's bug report, or a runtime error in `#bot-logs`, into an issue. The target message's full content arrives in the interaction payload, so this needs no Message Content Intent (#575).

What gets pulled in:

| From the right-clicked message | Into the issue |
|---|---|
| `content` | Sent to Gemini with the notes, and attached **verbatim** in a collapsible `<details>` block |
| Embeds (title, description, each field) | Same as `content`. An embed-only bot post has empty `content`, so this is where an error report actually lives |
| `.txt` / `.log` attachments under 20 KB (40 KB across all of them) | Inlined **verbatim** in a collapsible `<details>` block |
| Image attachments | Filename only |
| (always) | A permanent `jump_url` link back to the Discord message |

The attachments go in the `### Screenshots/Logs` section for every ticket type. The enhancement and feature templates have no such section, so it is added just above `### Branch`.

Notes on why it works this way:

- **Logs are inlined, not linked.** Discord attachment URLs are signed and expire within about a day, so a linked log is dead by the time anyone reads the issue.
- **The original message is appended after Gemini returns**, not only passed through it. `call_gemini` authors the entire body, so anything routed through it comes back paraphrased rather than verbatim.
- **The branch placeholder is renamed before artifacts are appended**, so a log containing something like `-Bug` cannot be rewritten by the substitution.
- **Empty sections are omitted** rather than filled with a placeholder.
- Notes are optional; the right-clicked message alone is enough. A message with no text, embeds or attachments and no notes is refused.
- The command is hidden from members without Administrator, and `TICKET_CREATOR_ID` is still checked on `interaction.user.id`.

### @mention (fallback)

@-mention the bot with a description of a bug, enhancement, or feature. The bot replies with a confirm/cancel prompt; on confirm the description goes to Gemini. The mentioning message is exempt from Message Content Intent.

A replied-to message is **not** read. The mention exemption covers only the mentioning message, so without the intent the message it replies to arrives empty. To file from another message, right-click it instead.

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
- Message context is collected by `context_from_message()`; artifacts are attached by `append_context()`
- Logic lives in `features/github_tickets.py`
- Tested in `tests/test_github_tickets.py`

---

## Source File
`features/github_tickets.py`
