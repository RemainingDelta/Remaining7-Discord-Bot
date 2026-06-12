import json
import os
import re

import aiohttp
import discord
from discord.ext import commands

from features.config import GITHUB_REPO, TICKET_CREATOR_ID

GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
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

### Screenshots/Logs [if applicable]
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

USER DESCRIPTION:
{description}"""


async def call_gemini(raw_text: str) -> dict:
    """Call Gemini 2.0 Flash API to classify and structure a GitHub issue."""
    if not GEMINI_TOKEN:
        raise RuntimeError("GEMINI_TOKEN environment variable is not set.")

    prompt = GEMINI_PROMPT.format(
        bug=BUG_TEMPLATE,
        enhancement=ENHANCEMENT_TEMPLATE,
        feature=FEATURE_TEMPLATE,
        description=raw_text,
    )

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


async def create_github_issue(title: str, body: str, label: str) -> dict:
    """Create a GitHub issue via the REST API."""
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set.")

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            GITHUB_API_URL,
            headers=headers,
            json={"title": title, "body": body, "labels": [label]},
        ) as resp:
            if resp.status != 201:
                error_text = await resp.text()
                raise RuntimeError(
                    f"GitHub API returned status {resp.status}: {error_text}"
                )

            data = await resp.json()

    return {"number": data["number"], "html_url": data["html_url"]}


async def update_github_issue(issue_number: int, body: str) -> None:
    """Patch an existing GitHub issue to update its body."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with aiohttp.ClientSession() as session:
        async with session.patch(
            f"{GITHUB_API_URL}/{issue_number}",
            headers=headers,
            json={"body": body},
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(
                    f"GitHub API PATCH returned status {resp.status}: {error_text}"
                )


class ConfirmView(discord.ui.View):
    def __init__(self, raw_text: str, author_id: int):
        super().__init__(timeout=60)
        self.raw_text = raw_text
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.stop()
        await interaction.response.edit_message(
            content="Creating GitHub issue...", view=None
        )

        try:
            ticket = await call_gemini(self.raw_text)

            label_map = {
                "bug": "Bug",
                "enhancement": "Enhancement",
                "feature": "Feature",
            }
            label = label_map[ticket["type"]]

            issue = await create_github_issue(ticket["title"], ticket["body"], label)

            branch = f"{issue['number']}-{label}"
            updated_body = ticket["body"].replace(f"-{label}", branch)
            await update_github_issue(issue["number"], updated_body)

            await interaction.edit_original_response(
                content=f"Created issue #{issue['number']}: <{issue['html_url']}>\nBranch: `{branch}`",
            )
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str:
                user_msg = "The AI service is currently experiencing high demand. Please try again later."
            elif "429" in error_str:
                user_msg = "The AI service rate limit has been reached. Please try again later."
            elif "Gemini" in error_str:
                user_msg = (
                    "The AI service returned an unexpected response. Please try again."
                )
            elif "GitHub" in error_str:
                user_msg = "Failed to create the GitHub issue via GitHub API. Please try again."
            else:
                user_msg = "An unexpected error occurred. Please try again."
            await interaction.edit_original_response(
                content=f"Failed to create GitHub issue: {user_msg}",
            )

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled", view=None)


class GitHubTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not re.search(rf"<@!?{self.bot.user.id}>", message.content):
            return

        if message.author.id != TICKET_CREATOR_ID:
            return

        raw_text = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()

        if not raw_text:
            await message.reply(
                "@ me with a description of your bug, enhancement, or feature"
                " and I'll create a GitHub issue.",
                mention_author=True,
            )
            return

        view = ConfirmView(raw_text, message.author.id)
        reply = await message.reply(
            "Create a GitHub issue?", view=view, mention_author=True
        )
        view.message = reply


async def setup(bot):
    await bot.add_cog(GitHubTickets(bot))
