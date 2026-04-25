import json
import os
import re

import aiohttp
import discord
from discord.ext import commands

GEMINI_TOKEN = os.getenv("GEMINI_TOKEN")
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

    return result


class GitHubTickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not re.search(rf"<@!?{self.bot.user.id}>", message.content):
            return

        raw_text = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()

        if not raw_text:
            await message.reply(
                "@ me with a description of your bug, enhancement, or feature"
                " and I'll create a GitHub issue."
            )
            return

        # TODO: Pass raw_text to Gemini integration
        await message.reply(f"Received: {raw_text}")


async def setup(bot):
    await bot.add_cog(GitHubTickets(bot))
