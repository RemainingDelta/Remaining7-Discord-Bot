"""Privacy policy: the policy text, its embeds, `/privacy-policy`, and the
startup repost that keeps the privacy channel current (#490).

The policy lives here once, as data. Both Discord surfaces — the command and the
auto-posted channel — render the same `POLICY_PARTS`, so an edit to the wording
lands in both without a second copy to keep in sync. `PRIVACY_POLICY.md` at the
repo root carries the same policy for readers outside Discord; the tests assert
the two agree on sections and the "Last updated" date.

Grouping into parts is what keeps the sequence inside Discord's limits: 4096
characters per embed description, 6000 across every embed in one message.
"""

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from features.config import OTHER_TICKET_CHANNEL_ID, PRIVACY_CHANNEL_ID

POLICY_TITLE = "Remaining 7 Bot Privacy Policy"
LAST_UPDATED = "August 28, 2026"

# The same policy, hosted on the web. Linked at the foot of the last embed for
# anyone who wants to read or share it outside Discord. This is the one external
# link the embeds carry (the footer itself can't hold a link, so the link sits
# as the last line of the description, just above the footer).
POLICY_URL = "https://remaining7.netlify.app/privacy"
WEB_LINK_LINE = f"[Read this policy on our website]({POLICY_URL})"

# How far back the startup repost looks for its own previous copy. The channel
# holds nothing but this policy, so a handful of messages is plenty.
HISTORY_SCAN_LIMIT = 50

# Rendered into the contact section. In a guild #tickets is shown as a real
# channel mention — the purple #channel chip — which Discord renders from the
# `<#id>` form. Outside a guild (a DM) that mention would not resolve to a name,
# so the plain wording is used instead.
CONTACT_LINK = "Open a ticket in {mention} and select Server Support."
CONTACT_PLAIN = "Open a ticket in the tickets channel and select Server Support."


@dataclass(frozen=True)
class PolicySection:
    """One `## heading` of the policy."""

    heading: str
    body: str


@dataclass(frozen=True)
class PolicyPart:
    """A group of sections rendered as a single embed."""

    title: str
    intro: str
    sections: tuple[PolicySection, ...]


POLICY_PARTS: tuple[PolicyPart, ...] = (
    PolicyPart(
        title=f"🔒 {POLICY_TITLE}",
        intro=(
            "This policy explains what information Remaining 7 Bot collects "
            "when you use it in the Remaining 7 Discord server, how that "
            "information is used, and how it is protected. "
            "This policy applies only to the bot's own data practices and is "
            "separate from Discord's own Privacy Policy, which governs the "
            "Discord platform itself."
        ),
        sections=(
            PolicySection(
                heading="Who we are",
                body=(
                    "Remaining 7 Bot is operated by Remaining 7, a Brawl Stars "
                    "esports organization, for use within its own Discord "
                    "server. This is a private bot built for a single "
                    "community and is not available for other servers to add."
                ),
            ),
            PolicySection(
                heading="What information we collect",
                body=(
                    "When you interact with the bot, we may collect and store "
                    "the following:\n"
                    "- Your Discord user ID, used to identify your account "
                    "across all bot features\n"
                    "- Token and XP balances, and level, tracked as part of "
                    "the server's economy system\n"
                    "- Quest progress, including which quests are assigned to "
                    "you and your completion status\n"
                    "- Redemption and ticket history, including items "
                    "purchased, tickets opened, and which staff member "
                    "fulfilled a request\n"
                    "- Account-security flags, if your account is ever marked "
                    'as compromised through the bot\'s "hacked" protocol (this '
                    "record contains your user ID and a fixed reason label, "
                    "not the content of any flagged messages)\n"
                    "- Sticky message text, if a staff member sets a sticky "
                    "message in a channel using the bot\n"
                    "- Booster status markers, a simple monthly marker used to "
                    "track whether you've used a booster perk (such as a shop "
                    "discount) in the current month"
                ),
            ),
        ),
    ),
    PolicyPart(
        title="🔒 Privacy Policy — Use & Storage",
        intro="",
        sections=(
            PolicySection(
                heading="What we do not collect or store",
                body=(
                    "- We do not store your Discord roles, nickname, or other "
                    "full profile information\n"
                    "- We do not store your raw Discord boost start date; we "
                    "only store a monthly marker used for perk eligibility\n"
                    "- We do not use Discord's Presence intent, so we never "
                    "see your online status or activity\n"
                    "- We do not store the content of your everyday messages. "
                    "Message content is read live to power features like "
                    "commands, quests, and moderation, but it is not saved, "
                    "with the single exception of sticky message text "
                    "described above"
                ),
            ),
            PolicySection(
                heading="Why we collect this information",
                body=(
                    "All information collected is necessary to operate the "
                    "bot's features, including:\n"
                    "- The token and XP economy, leveling, and daily rewards\n"
                    "- Quest assignment and tracking\n"
                    "- The shop, redemption, and ticket systems\n"
                    "- Tournament ticket management\n"
                    '- The account-security ("hacked") protocol, used to '
                    "protect compromised accounts\n"
                    "- Sticky messages and other staff moderation tools\n\n"
                    "We do not use this information for advertising, "
                    "profiling, or any purpose unrelated to operating these "
                    "features."
                ),
            ),
            PolicySection(
                heading="Where your information is stored",
                body=(
                    "All data is stored in our own MongoDB Atlas database. It "
                    "is encrypted at rest and encrypted in transit between the "
                    "bot and the database. We do not share, sell, or license "
                    "this information to any third party, data broker, or "
                    "advertising service."
                ),
            ),
            PolicySection(
                heading="When information leaves Discord",
                body=(
                    "In a small number of cases, information generated by the "
                    "bot is sent outside of Discord:\n"
                    "- Ticket transcripts. When a support or tournament ticket "
                    "is closed, the bot generates a text file containing that "
                    "ticket's message history. This file is sent to the person "
                    "who opened the ticket via direct message and is archived "
                    "in a staff-only log channel.\n"
                    "- GitHub issue creation. A single authorized staff member "
                    "can @mention the bot to convert a bug report or feature "
                    "request into a GitHub issue. When this happens, that "
                    "staff member's message is sent to Google's Gemini API for "
                    "classification and to GitHub, where the resulting issue "
                    "is created and publicly visible in our project "
                    "repository. This feature is restricted to one authorized "
                    "user and is not available to general members."
                ),
            ),
        ),
    ),
    PolicyPart(
        title="🔒 Privacy Policy — Your Choices",
        intro="",
        sections=(
            PolicySection(
                heading="Opt-out and your choices",
                body=(
                    "There is currently no opt-out mechanism for passive data "
                    "collection, such as token/XP earning or quest tracking, "
                    "while you remain a member of the server. Leaving the "
                    "server stops any further collection going forward but "
                    "does not automatically delete existing records.\n\n"
                    "If you would like your data deleted, you can contact us "
                    "using the information below and we will remove your "
                    "stored records upon request, except where retention is "
                    "required to preserve the integrity of shared records "
                    "(such as a ticket transcript already shared with another "
                    "user)."
                ),
            ),
            PolicySection(
                heading="Age requirement",
                body=(
                    "This bot and the server it operates in are not directed "
                    "at children. In line with Discord's own Terms of Service, "
                    "you must be at least 13 years old, or the minimum age "
                    "required in your country, to use Discord and this bot."
                ),
            ),
            PolicySection(
                heading="Changes to this policy",
                body=(
                    "We may update this policy from time to time as the bot's "
                    'features change. The "Last updated" date at the top of '
                    "this page will reflect the most recent revision."
                ),
            ),
            PolicySection(
                heading="Contact us",
                body=(
                    "If you have questions about this policy or want to "
                    "request that your data be deleted, you can reach us in "
                    "the server.\n{contact}"
                ),
            ),
        ),
    ),
)


def tickets_contact_line(guild_id: int | None) -> str:
    """The contact line, showing #tickets as a channel mention chip in a guild.

    A bare `<#id>` mention only renders as the channel chip where Discord can
    resolve it, so outside a guild (a DM) the plain wording is used instead. The
    channel ID comes from the config split, so the dev server points at its own
    tickets channel rather than the production one.
    """
    if not guild_id:
        return CONTACT_PLAIN
    return CONTACT_LINK.format(mention=f"<#{OTHER_TICKET_CHANNEL_ID}>")


def _render(section: PolicySection, guild_id: int | None) -> str:
    body = section.body
    if "{contact}" in body:
        body = body.format(contact=tickets_contact_line(guild_id))
    return f"## {section.heading}\n{body}"


def build_privacy_embeds(guild_id: int | None) -> list[discord.Embed]:
    """Render the policy as the embed sequence both surfaces post.

    `guild_id` is the server the embeds will be read in — it only shapes the
    tickets link in the contact section.
    """
    embeds = []
    for part in POLICY_PARTS:
        blocks = [part.intro] if part.intro else []
        blocks.extend(_render(section, guild_id) for section in part.sections)
        embeds.append(
            discord.Embed(
                title=part.title,
                description="\n\n".join(blocks),
                color=discord.Color.blurple(),
            )
        )

    embeds[-1].description += f"\n\n{WEB_LINK_LINE}"
    embeds[-1].set_footer(text=f"Last updated: {LAST_UPDATED}")
    return embeds


class PrivacyPolicy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="privacy-policy",
        description="View what data R7 Bot collects about you, and why.",
    )
    async def privacy_policy(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embeds=build_privacy_embeds(interaction.guild_id), ephemeral=True
        )


async def repost_privacy_policy(bot: commands.Bot):
    """On startup, replace the bot's copy of the policy in the privacy channel.

    Same shape as the support-panel repost (#149): the channel is meant to hold
    the current policy and nothing else, so the old copy is deleted before the
    new one is posted rather than edited in place. Deleting first also means a
    policy that has since been split into a different number of embeds does not
    leave orphaned messages behind.
    """
    if not PRIVACY_CHANNEL_ID:
        print("⚠️ PRIVACY_CHANNEL_ID is not set — skipping the privacy policy post")
        return

    channel = bot.get_channel(PRIVACY_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        print(f"⚠️ Privacy channel {PRIVACY_CHANNEL_ID} not found — policy not posted")
        return

    try:
        async for message in channel.history(limit=HISTORY_SCAN_LIMIT):
            if message.author == bot.user:
                await message.delete()

        await channel.send(embeds=build_privacy_embeds(channel.guild.id))
        print(f"✅ Posted the privacy policy in #{channel.name}")
    except Exception as e:
        print(f"⚠️ Could not post the privacy policy: {e}")


async def setup(bot):
    await bot.add_cog(PrivacyPolicy(bot))
