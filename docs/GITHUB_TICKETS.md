# GitHub Tickets

## Overview
The GitHub Tickets feature lets the ticket creator turn a Discord message, or a typed description, into a structured GitHub issue, or into an update to an existing one (#252). After a trigger the bot asks which it should be, with three buttons:

| Button | What happens |
|---|---|
| **Create new issue** | The text goes to Gemini's create prompt, and the issue is created (see [Gemini Classification](#gemini-classification)) |
| **Edit existing issue** | The first `#N` in the text is the target. Gemini's edit prompt proposes changes, and the bot previews them before writing anything (see [Editing an Existing Issue](#editing-an-existing-issue)) |
| **Cancel** | Nothing is sent to Gemini or GitHub |

The user picks, not the AI, so there is no guessing whether a message is a new ticket or an edit, and each prompt only has one job. No Gemini or GitHub call is made until a button is pressed. Only the ticket creator can press the buttons.

---

## Trigger

Only the ticket creator (`TICKET_CREATOR_ID`) can file issues. There are two ways in.

### Right-click a message: "GitHub Issue" (primary)

Right-click any message, then **Apps → GitHub Issue**. A modal opens with one optional field for extra context. On submit, the bot posts the Create / Edit / Cancel choice publicly in the channel. To edit, put the issue number in the notes (e.g. "this is #540 again"). The notes come first in the text, so their `#N` wins over any number inside the message.

This is how to turn someone else's bug report, or a runtime error in `#bot-logs`, into an issue, or attach it to the issue it belongs to. The target message's full content arrives in the interaction payload, so this needs no Message Content Intent (#575).

What gets pulled in:

| From the right-clicked message | Into the issue |
|---|---|
| `content` | Sent to Gemini with the notes, and attached **verbatim** in a collapsible `<details>` block |
| Embeds (title, description, each field) | Same as `content`. An embed-only bot post has empty `content`, so this is where an error report actually lives |
| `.txt` / `.log` attachments under 20 KB (40 KB across all of them) | Inlined **verbatim** in a collapsible `<details>` block |
| Image attachments | Filename only |
| (always) | A permanent `jump_url` link back to the Discord message |

On **Create**, the attachments go in the `### Screenshots/Logs` section for every ticket type. The enhancement and feature templates have no such section, so it is added just above `### Branch`. On **Edit**, the same blocks are appended to the comment. A right-click edit always posts a comment, even if the request only relabels or closes, so the message is never lost.

Notes on why it works this way:

- **Logs are inlined, not linked.** Discord attachment URLs are signed and expire within about a day, so a linked log is dead by the time anyone reads the issue.
- **The original message is appended after Gemini returns**, not only passed through it. `call_gemini` authors the entire body, so anything routed through it comes back paraphrased rather than verbatim.
- **The branch placeholder is renamed before artifacts are appended**, so a log containing something like `-Bug` cannot be rewritten by the substitution.
- **Empty sections are omitted** rather than filled with a placeholder.
- Notes are optional; the right-clicked message alone is enough. A message with no text, embeds or attachments and no notes is refused.
- The command is hidden from members without Administrator, and `TICKET_CREATOR_ID` is still checked on `interaction.user.id`.

### @mention (fallback)

@-mention the bot with a description in the same message, e.g. `@bot the shop crashes on refund` or `@bot close #540, fixed in v2.3`. The bot replies with the Create / Edit / Cancel choice. A bare mention gets a usage hint. The mentioning message is exempt from Message Content Intent.

A replied-to message is **not** read. The mention exemption covers only the mentioning message, so without the intent the message it replies to arrives empty. To file from another message, right-click it instead.

---

## Gemini Classification

On **Create**, the bot sends `GEMINI_PROMPT` with the description and asks it to:
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

### Referenced issues

A create request can point at existing issues, e.g. "a new enhancement that bumps the version like #512". Every `#N` (or `github.com/<repo>/issues/N` URL) in the text is read with `fetch_issue()`, up to 3, and added to the prompt as a `REFERENCED ISSUES` block (title, state, and the first 2,000 characters of the body). They are context only. Nothing is written to them, and a reference that cannot be read is skipped.

`extract_issue_refs()` ignores Discord channel mentions (`<#123...>`) and HTML entities (`&#123;`).

---

## Editing an Existing Issue

**Edit** needs an issue number. The first `#N` or issue URL in the text is the target. Any others are passed to the prompt as references (e.g. "mark #540 as a duplicate of #12"). With no number, the bot replies with a hint and calls nothing.

1. `fetch_issue(N)` reads the title, body, state and labels. A missing issue or a pull request gets a plain message ("Issue #999 does not exist.") and stops there.
2. `fetch_repo_labels()` reads the repo's labels.
3. `call_gemini_edit()` sends `EDIT_PROMPT` and gets back `{"changes": [...]}`.
4. `validate_changes()` filters that list (below).
5. The bot shows a preview with **Apply** / **Cancel**:
   ```
   Edit #540 "Bug: shop refund crash" (open):
   • Comment:
   > Fixed in v2.3
   • Add labels: High Priority
   • Close (completed)
   ```
6. **Apply** runs `apply_changes()` (comment, then labels, then state) and edits the message to `Updated #540: <link>` with the list of changes. **Cancel** writes nothing. The preview times out after 120 seconds.

### Allowed changes

| Change | GitHub call |
|---|---|
| `comment` | `POST /issues/{n}/comments` |
| `add_labels` | `POST /issues/{n}/labels` |
| `remove_labels` | `DELETE /issues/{n}/labels/{name}`, once per label |
| `close` (`completed` or `not_planned`) | `PATCH /issues/{n}` with `state` and `state_reason` |
| `reopen` | `PATCH /issues/{n}` with `state: open`, `state_reason: reopened` |

The title and description are never edited. Gemini would paraphrase the body and could drop checklists or the verbatim logs written by `append_context()`. If the user asks for a title or description change, the prompt tells Gemini to write a comment describing it instead.

### Validation

Gemini's reply is untrusted. `validate_changes()` keeps only changes that are allowed and would actually do something:

- Unknown actions are dropped.
- Labels must exist in the repo. They are matched case-insensitively and applied in the repo's spelling.
- A label is only added if the issue lacks it, and only removed if the issue has it.
- `close` only on an open issue, `reopen` only on a closed one. An unrecognised close reason becomes `completed`.
- Empty comments are dropped, and at most one change of each kind is kept.

If nothing survives, the bot says "Nothing to change on #N for that request." and shows no buttons.

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

On success, the bot edits its message to the created issue's URL and branch name.

---

## Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_TOKEN` | Gemini API key for AI summarization |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` scope (or a fine-grained token with Issues read/write) |
| `GITHUB_REPO` | Repository in `owner/repo` format |

---

## Notes
- The bot must have permission to create, comment on, label, and close issues on the target repository
- The `GITHUB_TOKEN` needs `repo` scope (not just `public_repo`) if the repo is private
- If Gemini fails or returns something unusable, the bot reports it in the channel and nothing is written. There is no fallback template
- Message context is collected by `context_from_message()`; artifacts are attached by `append_context()` (create) or `_comment_body()` (edit)
- Logic lives in `features/github_tickets.py`
- Tested in `tests/test_github_tickets.py`

---

## Source File
`features/github_tickets.py`
