import discord
from discord import app_commands
from discord.ext import commands

# Import Config
from features.config import (
    BOOSTER_CHANNEL_ID,
    BOTS_CATEGORY_ID,
    GENERAL_CHANNEL_ID,
    PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS,
    SERVER_BOOSTER_ROLE_ID,
)

# Import Database Helpers
from database.mongo import (
    init_default_quests,
    get_active_quest,
    assign_random_quest,
    update_quest_progress,
    reset_user_quests,
    get_user_balance,
    update_user_balance,
    get_leveling_data,
    update_leveling_data,
)

# --- DEFAULT QUESTS CONFIGURATION ---
DEFAULT_QUESTS = [
    # Name | Desc | Tokens | XP | Target | Type | Category
    # Daily Message Quests
    ("Daily Chatter", "Send 80 messages today.", 50, 100, 80, "daily", "message"),
    ("Quick Convo", "Send 160 messages today.", 115, 200, 160, "daily", "message"),
    ("Engaged Today", "Send 240 messages today.", 250, 300, 240, "daily", "message"),
    # Daily Megabox Quests
    (
        "Mega Box Maniac",
        "Open 100 Mega Boxes or Starr Drops today.",
        50,
        100,
        100,
        "daily",
        "megabox",
    ),
    # Weekly Message Quests
    (
        "Weekly Regular",
        "Send 500 messages this week.",
        225,
        1000,
        500,
        "weekly",
        "message",
    ),
    (
        "Consistent Contributor",
        "Send 750 messages this week.",
        400,
        2000,
        750,
        "weekly",
        "message",
    ),
    (
        "Server Pillar",
        "Send 1000 messages this week.",
        640,
        3000,
        1000,
        "weekly",
        "message",
    ),
    # Weekly Megabox Quests
    (
        "Mega Box Grinder",
        "Open 500 Mega Boxes or Starr Drops this week.",
        250,
        500,
        500,
        "weekly",
        "megabox",
    ),
]


def _is_booster(member) -> bool:
    """Booster role check; safe against non-Member objects (DMs, None)."""
    get_role = getattr(member, "get_role", None)
    return get_role is not None and get_role(SERVER_BOOSTER_ROLE_ID) is not None


class Quests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Invite cache kept for stability, but unused for quests now
        self.invite_cache = {}

    async def cog_load(self):
        # Initialize default quests in DB on startup
        await init_default_quests(DEFAULT_QUESTS)
        print("✅ Quests System Loaded")

        # Build Invite Cache (Passive tracking only)
        for guild in self.bot.guilds:
            try:
                self.invite_cache[guild.id] = {}
                invites = await guild.invites()
                for invite in invites:
                    self.invite_cache[guild.id][invite.code] = invite.uses
            except Exception:
                pass

    # --- HELPERS ---

    async def process_quest_update(
        self, user_id, channel, action_type="message", member=None
    ):
        """Checks daily/weekly quests for progress."""
        if action_type == "message":
            q_keys = ["daily_message", "weekly_message"]
        elif action_type == "megabox":
            q_keys = ["daily_megabox", "weekly_megabox"]
        else:
            return

        for q_key in q_keys:
            # 1. Get or Assign Quest
            quest = await get_active_quest(user_id, q_key)
            if not quest:
                quest = await assign_random_quest(
                    user_id, q_key, is_booster=_is_booster(member)
                )

            if not quest:
                continue

            # 2. Update Progress
            completed, q_data = await update_quest_progress(user_id, q_key)

            # 4. Handle Completion
            if completed and q_data:
                reward_text = []
                # Give Tokens
                if q_data.get("reward_tokens", 0) > 0:
                    bal = await get_user_balance(user_id)
                    await update_user_balance(user_id, bal + q_data["reward_tokens"])
                    reward_text.append(f"💰 {q_data['reward_tokens']} Tokens")

                # Give XP
                if q_data.get("reward_exp", 0) > 0:
                    lvl, exp = await get_leveling_data(user_id)
                    await update_leveling_data(user_id, lvl, exp + q_data["reward_exp"])
                    reward_text.append(f"⚡ {q_data['reward_exp']} XP")

                # Send Embed
                embed = discord.Embed(
                    title="🎉 Quest Completed!",
                    description=f"**{q_data['name']}**\n{q_data['description']}",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Rewards", value=" + ".join(reward_text))
                if channel:
                    try:
                        await channel.send(f"<@{user_id}>", embed=embed)
                    except discord.Forbidden:
                        pass

    # --- LISTENERS ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Skip quest progress outside general chat and restricted channels
        if message.channel.category and message.channel.category.id == BOTS_CATEGORY_ID:
            return
        if message.channel.id in PASSIVE_REWARD_EXCLUDED_CHANNEL_IDS:
            return
        if message.channel.id not in (GENERAL_CHANNEL_ID, BOOSTER_CHANNEL_ID):
            return

        # Trigger message quest updates
        await self.process_quest_update(
            str(message.author.id), message.channel, "message", member=message.author
        )

    # Kept to prevent errors if main.py expects them, but they do nothing for quests now
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild.id in self.invite_cache:
            self.invite_cache[invite.guild.id][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if guild.id not in self.invite_cache:
            return

        try:
            current_invites = await guild.invites()
            for invite in current_invites:
                code = invite.code
                if code in self.invite_cache[guild.id]:
                    old_uses = self.invite_cache[guild.id][code]
                    if invite.uses > old_uses:
                        self.invite_cache[guild.id][code] = invite.uses
                        break
        except Exception:
            pass

    # --- COMMANDS ---

    @app_commands.command(
        name="quests", description="View your current Daily and Weekly quests."
    )
    async def quests(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        embed = discord.Embed(
            title=f"📜 {interaction.user.display_name}'s Quests",
            color=discord.Color.blue(),
        )

        quest_slots = [
            ("daily_message", "Daily Message Quest"),
            ("weekly_message", "Weekly Message Quest"),
            ("daily_megabox", "Daily Megabox Quest"),
            ("weekly_megabox", "Weekly Megabox Quest"),
        ]

        for q_key, title in quest_slots:
            quest = await get_active_quest(user_id, q_key)
            if not quest:
                quest = await assign_random_quest(
                    user_id, q_key, is_booster=_is_booster(interaction.user)
                )

            if quest:
                # Progress Bar Logic
                prog = quest.get("progress", 0)
                tgt = quest.get("target_count", 100)
                percent = int((prog / tgt) * 100)

                bar_len = 10
                filled = int(bar_len * percent / 100)
                bar = "🟩" * filled + "⬜" * (bar_len - filled)

                status = (
                    "✅ Completed" if quest.get("completed") else f"{bar} {percent}%"
                )

                val = (
                    f"{quest['description']}\n"
                    f"Rewards: Tokens: **{quest['reward_tokens']}** | XP: **{quest['reward_exp']}**\n"
                    f"Progress: `{prog}/{tgt}`\n"
                    f"{status}"
                )
                embed.add_field(name=title, value=val, inline=False)
            else:
                embed.add_field(
                    name=title, value="No active quest available.", inline=False
                )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="reset-quests", description="[STAFF] Reset a user's quest assignments."
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="The user whose quests to reset.")
    async def resetquests(self, interaction: discord.Interaction, user: discord.Member):
        await reset_user_quests(str(user.id))
        await interaction.response.send_message(
            f"✅ Quest assignments reset for {user.mention}. They'll get new quests on next `/quests`.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Quests(bot))
