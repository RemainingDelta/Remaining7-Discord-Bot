import json
import os
import re
from typing import NamedTuple
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from features.config import GITHUB_REPO, TICKET_CREATOR_ID

GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO_URL = f"https://api.github.com/repos/{GITHUB_REPO}"
GITHUB_API_URL = f"{GITHUB_REPO_URL}/issues"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

BUG_TEMPLATE = """\
Bug: <Small desc of the bug>

### Overview
Provide a clear and concise description of the bug. Include any relevant background information.

### Acceptance Criteria
How do we know it's done?
- [ ] [criteria #1]
- [ ] [criteria #2]

### Steps to Reproduce Bug
- [ ] [Step #1]
- [ ] [Step #2]
- [ ] [Step #3]

### Impact
Describe how this affects users, performance, or other parts of the system.

### Screenshots/Logs
Attach screenshots, error logs, or any relevant artifacts.

### Branch
```
-Bug
```"""

ENHANCEMENT_TEMPLATE = """\
Enhancement: <small desc of the enhancement>

### Overview
1-2 sentences describing the improvement and which existing feature it modifies.

### Current Behavior
Describe how the feature currently functions or the limitation that exists.

### Proposed Behavior
Describe the desired improvement, optimization, or UI change.

### Technical Requirements
- [ ] [Specific change or refactor #1]
- [ ] [Specific change or refactor #2]

### Acceptance Criteria
- [ ] [criteria #1]
- [ ] [criteria #2]

### Benefit/Impact
Why is this improvement necessary? (e.g., Better UX, improved performance, cleaner code).

### Branch
```
-Enhancement
```"""

FEATURE_TEMPLATE = """\
Feature: <small desc of the feature>

### Overview

1-2 sentences describing what this sub-issue accomplishes and how it contributes to the user story

### Technical Requirements

- [ ] [Specific implementation detail 1]

- [ ] [Specific implementation detail 2]

### Acceptance Criteria

- [ ] [criteria #1]

- [ ] [criteria #2]

### Notes

Any additional context, links, or questions.

### Branch
```
-Feature
```"""

GEMINI_PROMPT = """\
You are a GitHub issue writer for a Discord bot project. Given a user's description, \
determine whether it is a bug report, an enhancement to an existing feature, or a new \
feature request. Then generate a GitHub issue using the matching template below.

TEMPLATES:
--- BUG ---
{bug}

--- ENHANCEMENT ---
{enhancement}

--- FEATURE ---
{feature}

RULES:
- Return ONLY a raw JSON object with exactly three keys: "type", "title", "body"
- "type" must be one of: "bug", "enhancement", "feature"
- "title" must be a concise issue title (under 80 characters)
- "body" must be the filled-in template as a single string (use \\n for newlines)
- Fill in template sections with reasonable detail based on the description
- Use placeholder checkboxes for acceptance criteria and steps
- Do NOT hallucinate specifics beyond what the description provides
- Do NOT wrap the JSON in markdown code fences or add any preamble/explanation
{references}
USER DESCRIPTION:
{description}"""

REFERENCES_BLOCK = """
REFERENCED ISSUES (context only; follow them where the description asks, e.g. \
"like #512", but write a new issue rather than a copy, and never reuse their \
numbers in the branch):
{issues}
"""

EDIT_PROMPT = """\
You update an existing GitHub issue for a Discord bot project. The user wants \
issue #{number} changed. Decide which of the allowed changes carry out their \
request, and nothing more.

ALLOWED CHANGES:
- {{"action": "comment", "body": "<markdown comment>"}}
- {{"action": "add_labels", "labels": ["<label>", ...]}}
- {{"action": "remove_labels", "labels": ["<label>", ...]}}
- {{"action": "close", "state_reason": "completed" | "not_planned"}}
- {{"action": "reopen"}}

RULES:
- Return ONLY a raw JSON object: {{"changes": [ ... ]}}
- Use only labels from AVAILABLE LABELS
- The title and description cannot be edited. If the user asks for that, write a \
comment describing the requested change instead
- Comments are concise and written for the issue's readers, not addressed to the user
- Do NOT hallucinate specifics beyond what the request provides
- Do NOT wrap the JSON in markdown code fences or add any preamble/explanation

ISSUE #{number} ({state}): {title}
Labels: {labels}
{body}

AVAILABLE LABELS: {available}
{references}
USER REQUEST:
{request}"""

# Keeps prompts small when an issue body carries long logs.
MAX_REFERENCE_BODY_CHARS = 2_000
MAX_REFERENCES = 3


# --- CONTEXT FROM THE RIGHT-CLICKED MESSAGE (#522, #575) ---

# GitHub rejects an issue body over this length, and the body is written in a
# second call after the issue already exists — so overshooting leaves the issue
# created with its branch placeholder unrenamed and its log missing.
GITHUB_BODY_LIMIT = 65_536

# Budgeted well under that to leave room for the template itself. The total is
# what matters: several logs that each pass a per-file check still overflow.
MAX_INLINE_LOG_BYTES = 20_000
MAX_TOTAL_LOG_BYTES = 40_000

TEXT_ATTACHMENT_SUFFIXES = (".txt", ".log")
LOG_SECTION_HEADING = "### Screenshots/Logs"


class ReferencedContext(NamedTuple):
    """What the right-clicked message contributes to a ticket."""

    text: str
    logs: tuple[str, ...]
    attachment_names: tuple[str, ...]
    jump_url: str


def embed_to_text(embed: discord.Embed) -> str:
    """Flatten an embed into plain text.

    A message that is only an embed has an empty ``content``, so for the bot's
    own error posts the embed holds everything worth reading.
    """
    parts = [embed.title, embed.description]
    parts += [f"{field.name}: {field.value}" for field in embed.fields]
    return "\n".join(part for part in parts if part)


def _is_inlinable_log(attachment: discord.Attachment) -> bool:
    """Whether this attachment is a log small enough to paste into an issue."""
    if not attachment.filename.lower().endswith(TEXT_ATTACHMENT_SUFFIXES):
        return False
    return attachment.size <= MAX_INLINE_LOG_BYTES


async def _read_log_attachment(attachment: discord.Attachment) -> str | None:
    """Return an attachment's text, or None if it could not be read."""
    try:
        raw = await attachment.read()
    except (discord.HTTPException, discord.NotFound):
        return None
    return raw.decode("utf-8", errors="replace")


async def context_from_message(message: discord.Message) -> ReferencedContext:
    """Read the message a ticket is being filed from.

    The message comes from a "GitHub Issue" interaction, whose payload
    carries its full content without Message Content Intent (#575). A message
    replied to by an @mention does not: the mention exemption covers only the
    mentioning message, so the replied-to one would arrive empty.

    Logs are inlined rather than linked: Discord attachment URLs are signed and
    expire within about a day, so a linked log is dead by the time anyone reads
    the issue. Images cannot be inlined, so only their names are kept.
    """
    parts = [message.content] if message.content else []
    parts += [embed_to_text(embed) for embed in message.embeds]

    logs: list[str] = []
    attachment_names: list[str] = []
    budget = MAX_TOTAL_LOG_BYTES
    for attachment in message.attachments:
        if _is_inlinable_log(attachment) and attachment.size <= budget:
            log = await _read_log_attachment(attachment)
            if log is not None:
                logs.append(log)
                budget -= attachment.size
                continue
        attachment_names.append(attachment.filename)

    return ReferencedContext(
        text="\n".join(part for part in parts if part),
        logs=tuple(logs),
        attachment_names=tuple(attachment_names),
        jump_url=message.jump_url,
    )


def build_description(notes: str, context: ReferencedContext | None) -> str:
    """Compose what Gemini classifies from: the notes plus the quoted context."""
    if context is None or not context.text:
        return notes
    quoted = context.text
    if not notes:
        return quoted
    return f"{notes}\n\nContext from the original message:\n{quoted}"


def _code_block(text: str) -> str:
    """Fence text verbatim, with a fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _collapsible(summary: str, text: str) -> str:
    return (
        f"<details>\n<summary>{summary}</summary>\n\n{_code_block(text)}\n\n</details>"
    )


def _render_artifacts(context: ReferencedContext | None) -> str | None:
    """The Screenshots/Logs body for this ticket, or None if there is nothing.

    Attached for every ticket type (#575): the message the ticket was filed
    from is its log, whether Gemini calls it a bug, enhancement, or feature.
    """
    if context is None:
        return None

    parts: list[str] = []
    if context.text:
        parts.append(_collapsible("Original message", context.text))
    for log in context.logs:
        parts.append(_collapsible("Attached log", log))
    if context.attachment_names:
        parts.append("Attached in Discord: " + ", ".join(context.attachment_names))
    parts.append(f"[Original Discord message]({context.jump_url})")
    return "\n\n".join(parts)


def append_context(body: str, context: ReferencedContext | None) -> str:
    """Put the real artifacts in the Screenshots/Logs section of a Gemini body.

    Written in after ``call_gemini`` rather than passed through it: Gemini
    authors the whole body, so a traceback routed through it comes back
    paraphrased instead of verbatim. The section is replaced rather than
    appended to, so its placeholder prose cannot survive alongside the real
    thing, and it is removed outright when there is nothing to put there. The
    enhancement and feature templates have no such section, so it is added
    just above ``### Branch``.
    """
    artifacts = _render_artifacts(context)
    section = re.compile(
        rf"^{re.escape(LOG_SECTION_HEADING)}[^\n]*\n.*?(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if artifacts is None:
        return section.sub("", body, count=1).rstrip() + "\n"
    replacement = f"{LOG_SECTION_HEADING}\n{artifacts}\n\n"
    if section.search(body):
        return section.sub(lambda _: replacement, body, count=1)
    branch = re.search(r"^### Branch", body, re.MULTILINE)
    if branch:
        return body[: branch.start()] + replacement + body[branch.start() :]
    return f"{body.rstrip()}\n\n{replacement}"


# --- ISSUE REFERENCES (#252) ---

# "<#123>" is a Discord channel mention and "&#123;" an HTML entity, not issues.
_HASH_REF = re.compile(r"(?<![\w/&<])#(\d+)\b")
_URL_REF = re.compile(
    rf"github\.com/{re.escape(GITHUB_REPO)}/issues/(\d+)", re.IGNORECASE
)


def extract_issue_refs(text: str) -> list[int]:
    """Issue numbers in the text, in order of appearance, without duplicates."""
    found = [(m.start(), int(m.group(1))) for m in _HASH_REF.finditer(text)]
    found += [(m.start(), int(m.group(1))) for m in _URL_REF.finditer(text)]
    refs: list[int] = []
    for _, number in sorted(found):
        if number not in refs:
            refs.append(number)
    return refs


def _format_references(references) -> str:
    if not references:
        return ""
    issues = "\n\n".join(
        f"#{ref['number']} [{ref['state']}] {ref['title']}\n"
        f"{ref['body'][:MAX_REFERENCE_BODY_CHARS]}"
        for ref in references
    )
    return REFERENCES_BLOCK.format(issues=issues)


async def _gemini_json(prompt: str) -> dict:
    """Send a prompt to Gemini and parse its reply as a JSON object."""
    if not GEMINI_TOKEN:
        raise RuntimeError("GEMINI_TOKEN environment variable is not set.")

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            GEMINI_API_URL,
            params={"key": GEMINI_TOKEN},
            json=payload,
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(
                    f"Gemini API returned status {resp.status}: {error_text}"
                )

            data = await resp.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response structure: {e}") from e

    # Strip markdown fences if Gemini returns them despite instructions
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {e}\nRaw: {text}") from e
    if not isinstance(result, dict):
        raise RuntimeError(f"Gemini returned JSON that is not an object: {text}")
    return result


async def call_gemini(raw_text: str, references=()) -> dict:
    """Call Gemini to classify and structure a new GitHub issue.

    ``references`` are existing issues the description points at ("like
    #512"). They are context for the new issue and are never modified.
    """
    prompt = GEMINI_PROMPT.format(
        bug=BUG_TEMPLATE,
        enhancement=ENHANCEMENT_TEMPLATE,
        feature=FEATURE_TEMPLATE,
        references=_format_references(references),
        description=raw_text,
    )
    result = await _gemini_json(prompt)

    for key in ("type", "title", "body"):
        if key not in result:
            raise RuntimeError(f"Gemini response missing required key: '{key}'")

    if result["type"] not in ("bug", "enhancement", "feature"):
        raise RuntimeError(f"Gemini returned invalid type: '{result['type']}'")

    # Fix 1: Extract first line as title, body starts from ### Overview
    body = result["body"]
    lines = body.split("\n")
    if lines and lines[0].strip().startswith(("Bug:", "Enhancement:", "Feature:")):
        result["title"] = lines[0].strip().rstrip(".")
        for i, line in enumerate(lines[1:], start=1):
            if line.strip().startswith("### "):
                body = "\n".join(lines[i:])
                break

    # Fix 3: Collapse double newlines between consecutive checklist items
    body = re.sub(r"(- \[[ x]\] [^\n]+)\n\n(- \[[ x]\])", r"\1\n\2", body)
    result["body"] = body

    return result


class IssueLookupError(Exception):
    """An issue number that cannot be edited: missing, or a pull request."""


def _github_headers() -> dict:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set.")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _github_request(method: str, url: str, expected: int, **kwargs):
    """Send one GitHub REST call and return its JSON (or None for no body)."""
    async with aiohttp.ClientSession() as session:
        request = getattr(session, method)
        async with request(url, headers=_github_headers(), **kwargs) as resp:
            if resp.status != expected:
                error_text = await resp.text()
                raise RuntimeError(
                    f"GitHub API returned status {resp.status}: {error_text}"
                )
            return await resp.json() if expected != 204 else None


async def create_github_issue(title: str, body: str, label: str) -> dict:
    """Create a GitHub issue via the REST API."""
    data = await _github_request(
        "post",
        GITHUB_API_URL,
        201,
        json={"title": title, "body": body, "labels": [label]},
    )
    return {"number": data["number"], "html_url": data["html_url"]}


async def update_github_issue(issue_number: int, body: str) -> None:
    """Patch an existing GitHub issue to update its body."""
    await _github_request(
        "patch", f"{GITHUB_API_URL}/{issue_number}", 200, json={"body": body}
    )


async def fetch_issue(issue_number: int) -> dict:
    """Read an issue's number, title, body, state, label names and URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{GITHUB_API_URL}/{issue_number}", headers=_github_headers()
        ) as resp:
            if resp.status in (404, 410):
                raise IssueLookupError(f"Issue #{issue_number} does not exist.")
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(
                    f"GitHub API GET returned status {resp.status}: {error_text}"
                )
            data = await resp.json()

    # The issues endpoint also serves pull requests.
    if "pull_request" in data:
        raise IssueLookupError(f"#{issue_number} is a pull request, not an issue.")
    return {
        "number": data["number"],
        "title": data["title"],
        "body": data.get("body") or "",
        "state": data["state"],
        "labels": [label["name"] for label in data.get("labels", [])],
        "html_url": data["html_url"],
    }


async def fetch_repo_labels() -> list[str]:
    """Every label defined in the repository."""
    data = await _github_request(
        "get", f"{GITHUB_REPO_URL}/labels", 200, params={"per_page": 100}
    )
    return [label["name"] for label in data]


async def add_issue_comment(issue_number: int, body: str) -> None:
    await _github_request(
        "post", f"{GITHUB_API_URL}/{issue_number}/comments", 201, json={"body": body}
    )


async def add_issue_labels(issue_number: int, labels: list[str]) -> None:
    await _github_request(
        "post",
        f"{GITHUB_API_URL}/{issue_number}/labels",
        200,
        json={"labels": labels},
    )


async def remove_issue_label(issue_number: int, label: str) -> None:
    await _github_request(
        "delete",
        f"{GITHUB_API_URL}/{issue_number}/labels/{quote(label, safe='')}",
        200,
    )


async def set_issue_state(issue_number: int, state: str, reason: str) -> None:
    await _github_request(
        "patch",
        f"{GITHUB_API_URL}/{issue_number}",
        200,
        json={"state": state, "state_reason": reason},
    )


# --- EDITING AN EXISTING ISSUE (#252) ---

EDIT_ACTIONS = ("comment", "add_labels", "remove_labels", "close", "reopen")
CLOSE_REASONS = ("completed", "not_planned")


async def call_gemini_edit(
    raw_text: str, issue: dict, repo_labels: list[str], references=()
) -> list[dict]:
    """Ask Gemini which changes to ``issue`` carry out the request.

    The reply is untrusted: ``validate_changes`` filters it before anything
    is shown or applied.
    """
    prompt = EDIT_PROMPT.format(
        number=issue["number"],
        state=issue["state"],
        title=issue["title"],
        labels=", ".join(issue["labels"]) or "(none)",
        body=issue["body"][:MAX_REFERENCE_BODY_CHARS],
        available=", ".join(repo_labels),
        references=_format_references(references),
        request=raw_text,
    )
    result = await _gemini_json(prompt)
    changes = result.get("changes")
    if not isinstance(changes, list):
        raise RuntimeError("Gemini edit response is missing a 'changes' list")
    return [change for change in changes if isinstance(change, dict)]


def validate_changes(
    changes: list[dict], issue: dict, repo_labels: list[str]
) -> list[dict]:
    """Keep only the changes that are allowed and would actually do something.

    Labels must exist in the repo (matched case-insensitively and returned in
    the repo's spelling), a label is only added if missing and only removed if
    present, and a state change must differ from the current state. At most
    one change of each kind is kept.
    """
    canonical = {name.lower(): name for name in repo_labels}
    current = {name.lower() for name in issue["labels"]}
    kept: dict[str, dict] = {}

    for change in changes:
        action = change.get("action")
        if action not in EDIT_ACTIONS or action in kept:
            continue

        if action == "comment":
            body = change.get("body")
            if isinstance(body, str) and body.strip():
                kept[action] = {"action": action, "body": body.strip()}

        elif action in ("add_labels", "remove_labels"):
            wanted = change.get("labels")
            if not isinstance(wanted, list):
                continue
            labels: list[str] = []
            for name in wanted:
                key = str(name).lower()
                if key not in canonical or canonical[key] in labels:
                    continue
                if (key in current) == (action == "remove_labels"):
                    labels.append(canonical[key])
            if labels:
                kept[action] = {"action": action, "labels": labels}

        elif action == "close" and issue["state"] == "open":
            reason = change.get("state_reason")
            if reason not in CLOSE_REASONS:
                reason = "completed"
            kept[action] = {"action": action, "state_reason": reason}

        elif action == "reopen" and issue["state"] == "closed":
            kept[action] = {"action": action}

    return [kept[action] for action in EDIT_ACTIONS if action in kept]


# Keeps the preview under Discord's 2,000-character message limit.
MAX_PREVIEW_COMMENT_CHARS = 1_200


def describe_change(change: dict, attaches_context: bool = False) -> str:
    action = change["action"]
    if action == "comment":
        text = change["body"]
        if len(text) > MAX_PREVIEW_COMMENT_CHARS:
            text = text[:MAX_PREVIEW_COMMENT_CHARS] + "..."
        if attaches_context:
            text = f"{text}\n(original message attached)".strip()
        quoted = "\n".join(f"> {line}" for line in text.splitlines())
        return f"• Comment:\n{quoted}"
    if action == "add_labels":
        return "• Add labels: " + ", ".join(change["labels"])
    if action == "remove_labels":
        return "• Remove labels: " + ", ".join(change["labels"])
    if action == "close":
        return f"• Close ({change['state_reason']})"
    return "• Reopen"


def _comment_body(text: str, context: ReferencedContext | None) -> str:
    """The comment text plus, from a right-click, the verbatim artifacts."""
    return "\n\n".join(part for part in (text, _render_artifacts(context)) if part)


async def apply_changes(
    issue_number: int, changes: list[dict], context: ReferencedContext | None
) -> None:
    """Apply validated changes: comment, then labels, then the state change."""
    for change in changes:
        action = change["action"]
        if action == "comment":
            body = _comment_body(change["body"], context)
            await add_issue_comment(issue_number, body)
        elif action == "add_labels":
            await add_issue_labels(issue_number, change["labels"])
        elif action == "remove_labels":
            for label in change["labels"]:
                await remove_issue_label(issue_number, label)
        elif action == "close":
            await set_issue_state(issue_number, "closed", change["state_reason"])
        elif action == "reopen":
            await set_issue_state(issue_number, "open", "reopened")


async def _fetch_references(numbers: list[int]) -> list[dict]:
    """Read referenced issues for prompt context, skipping any that fail."""
    references = []
    for number in numbers[:MAX_REFERENCES]:
        try:
            references.append(await fetch_issue(number))
        except (IssueLookupError, RuntimeError, aiohttp.ClientError):
            continue
    return references


def _user_error(e: Exception, verb: str) -> str:
    """Map an exception to the message shown in Discord."""
    error_str = str(e)
    if "503" in error_str or "UNAVAILABLE" in error_str:
        return "The AI service is currently experiencing high demand. Please try again later."
    if "429" in error_str:
        return "The AI service rate limit has been reached. Please try again later."
    if "Gemini" in error_str:
        return "The AI service returned an unexpected response. Please try again."
    if "GitHub" in error_str:
        return f"Failed to {verb} the GitHub issue via GitHub API. Please try again."
    return "An unexpected error occurred. Please try again."


class _OwnerView(discord.ui.View):
    """A view only its author can press, disabled when it times out."""

    message: discord.Message | None = None

    def __init__(self, author_id: int, timeout: float):
        super().__init__(timeout=timeout)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)


async def run_create(
    interaction: discord.Interaction,
    raw_text: str,
    context: ReferencedContext | None,
) -> None:
    """Create a new issue; referenced #N issues are read as context only."""
    try:
        references = await _fetch_references(extract_issue_refs(raw_text))
        ticket = await call_gemini(raw_text, references)

        label_map = {
            "bug": "Bug",
            "enhancement": "Enhancement",
            "feature": "Feature",
        }
        label = label_map[ticket["type"]]

        issue = await create_github_issue(ticket["title"], ticket["body"], label)

        branch = f"{issue['number']}-{label}"
        # Rename the branch placeholder before appending artifacts, so a log
        # that happens to contain "-Bug" cannot be rewritten by the replace.
        updated_body = ticket["body"].replace(f"-{label}", branch)
        updated_body = append_context(updated_body, context)
        await update_github_issue(issue["number"], updated_body)

        await interaction.edit_original_response(
            content=f"Created issue #{issue['number']}: <{issue['html_url']}>\nBranch: `{branch}`",
        )
    except Exception as e:
        await interaction.edit_original_response(
            content=f"Failed to create GitHub issue: {_user_error(e, 'create')}",
        )


EDIT_NEEDS_NUMBER = (
    'Editing needs an issue number in the message, e.g. "@me close #540".'
)


async def run_edit(
    interaction: discord.Interaction,
    raw_text: str,
    context: ReferencedContext | None,
    author_id: int,
) -> None:
    """Plan an edit to the first #N and show it for approval. Writes nothing."""
    refs = extract_issue_refs(raw_text)
    if not refs:
        await interaction.edit_original_response(content=EDIT_NEEDS_NUMBER)
        return

    try:
        issue = await fetch_issue(refs[0])
        references = await _fetch_references(refs[1:])
        repo_labels = await fetch_repo_labels()
        proposed = await call_gemini_edit(raw_text, issue, repo_labels, references)
    except IssueLookupError as e:
        await interaction.edit_original_response(content=str(e))
        return
    except Exception as e:
        await interaction.edit_original_response(
            content=f"Failed to plan the edit: {_user_error(e, 'read')}",
        )
        return

    changes = validate_changes(proposed, issue, repo_labels)
    if not changes:
        await interaction.edit_original_response(
            content=f"Nothing to change on #{issue['number']} for that request."
        )
        return
    # A right-click files the message against the issue, so it always lands
    # in a comment even when the request itself only relabels or closes.
    if context is not None and changes[0]["action"] != "comment":
        changes.insert(0, {"action": "comment", "body": ""})

    view = EditPreviewView(issue, changes, author_id, context)
    await interaction.edit_original_response(content=view.preview(), view=view)
    view.message = await interaction.original_response()


class ChoiceView(_OwnerView):
    """Create a new issue or edit an existing one; each runs its own prompt."""

    def __init__(
        self,
        raw_text: str,
        author_id: int,
        context: ReferencedContext | None = None,
    ):
        super().__init__(author_id, timeout=60)
        self.raw_text = raw_text
        self.context = context

    @discord.ui.button(label="Create new issue", style=discord.ButtonStyle.green)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Creating GitHub issue...", view=None
        )
        await run_create(interaction, self.raw_text, self.context)

    @discord.ui.button(label="Edit existing issue", style=discord.ButtonStyle.blurple)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Reading the issue...", view=None
        )
        await run_edit(interaction, self.raw_text, self.context, self.author_id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled", view=None)


class EditPreviewView(_OwnerView):
    """Shows exactly what will change on the issue; Apply makes the calls."""

    def __init__(
        self,
        issue: dict,
        changes: list[dict],
        author_id: int,
        context: ReferencedContext | None = None,
    ):
        super().__init__(author_id, timeout=120)
        self.issue = issue
        self.changes = changes
        self.context = context

    def _lines(self) -> str:
        return "\n".join(
            describe_change(change, attaches_context=self.context is not None)
            for change in self.changes
        )

    def preview(self) -> str:
        issue = self.issue
        return (
            f'Edit #{issue["number"]} "{issue["title"]}" ({issue["state"]}):\n'
            f"{self._lines()}"
        )

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.green)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        number = self.issue["number"]
        await interaction.response.edit_message(
            content=f"Updating #{number}...", view=None
        )
        try:
            await apply_changes(number, self.changes, self.context)
        except Exception as e:
            await interaction.edit_original_response(
                content=f"Failed to update #{number}: {_user_error(e, 'update')}",
            )
            return
        await interaction.edit_original_response(
            content=f"Updated #{number}: <{self.issue['html_url']}>\n{self._lines()}",
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled", view=None)


CHOICE_PROMPT = (
    "Create a new GitHub issue, or edit an existing one?"
    " (Editing needs an issue number like #540.)"
)


class IssueNotesModal(discord.ui.Modal, title="GitHub Issue"):
    notes = discord.ui.TextInput(
        label="Extra context (optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
        placeholder="Anything to add to the message you right-clicked",
    )

    def __init__(self, target: discord.Message):
        super().__init__()
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        # Reading log attachments can outlast the 3-second response window.
        await interaction.response.defer(ephemeral=False, thinking=True)

        context = await context_from_message(self.target)
        raw_text = build_description(self.notes.value.strip(), context)
        if not raw_text:
            await interaction.followup.send(
                "That message has no text to file, and no notes were added.",
                ephemeral=False,
            )
            return

        view = ChoiceView(raw_text, interaction.user.id, context)
        view.message = await interaction.followup.send(
            CHOICE_PROMPT, view=view, ephemeral=False, wait=True
        )


class GitHubTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Context menus can't be declared as cog methods, so the "GitHub Issue"
        # message command is built here and registered in cog_load.
        self.create_issue_menu = app_commands.ContextMenu(
            name="GitHub Issue", callback=self.create_issue_from_message
        )
        # Hidden from regular members; TICKET_CREATOR_ID is still enforced below.
        self.create_issue_menu.default_permissions = discord.Permissions(
            administrator=True
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.create_issue_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.create_issue_menu.name, type=self.create_issue_menu.type
        )

    async def create_issue_from_message(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        if interaction.user.id != TICKET_CREATOR_ID:
            await interaction.response.send_message(
                "❌ You can't create GitHub issues.", ephemeral=False
            )
            return
        await interaction.response.send_modal(IssueNotesModal(message))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not re.search(rf"<@!?{self.bot.user.id}>", message.content):
            return

        if message.author.id != TICKET_CREATOR_ID:
            return

        # A replied-to message is deliberately not read: without Message
        # Content Intent it arrives empty (#575). Right-click it instead.
        raw_text = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()

        if not raw_text:
            await message.reply(
                "@ me with a description of your bug, enhancement, or feature"
                " to create a GitHub issue, or with an issue number (e.g. #540)"
                " and what to change to edit that one. To use someone else's"
                " message, right-click it → Apps → GitHub Issue.",
                mention_author=True,
            )
            return

        view = ChoiceView(raw_text, message.author.id)
        reply = await message.reply(CHOICE_PROMPT, view=view, mention_author=True)
        view.message = reply


async def setup(bot):
    await bot.add_cog(GitHubTickets(bot))
