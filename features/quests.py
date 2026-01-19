import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

# Import Database Helpers
from database.mongo import (
    init_default_quests, get_active_quest, assign_random_quest, 
    update_quest_progress, get_user_balance, update_user_balance,
    get_leveling_data, update_leveling_data
)

# --- DEFAULT QUESTS CONFIGURATION ---
DEFAULT_QUESTS = [
    # Daily Quests
    # Name | Desc | Tokens | XP | Target | Type
    ("Daily Chatter", "Send 80 messages today.", 50, 200, 80, 'daily'),
    ("Quick Convo", "Send 160 messages today.", 75, 250, 160, 'daily'),
    ("Engaged Today", "Send 240 messages today.", 100, 300, 240, 'daily'),
    
    # Weekly Quests
    ("Weekly Regular", "Send 500 messages this week.", 250, 1000, 500, 'weekly'),
    ("Consistent Contributor", "Send 750 messages this week.", 400, 2500, 750, 'weekly'),
    ("Server Pillar", "Send 1000 messages this week.", 600, 3000, 1000, 'weekly'),
]

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
            except:
                pass

    # --- HELPERS ---
    
    async def process_quest_update(self, user_id, channel, action_type="message"):
        """Checks daily/weekly quests for progress."""
        for q_type in ['daily', 'weekly']:
            # 1. Get or Assign Quest
            quest = await get_active_quest(user_id, q_type)
            if not quest:
                quest = await assign_random_quest(user_id, q_type)
            
            if not quest: continue 

            # 2. Filter: Only process message updates since invite quests are gone
            if action_type == "message" and "message" not in quest['description'].lower(): continue
            if action_type == "invite": continue # Explicitly ignore invites

            # 3. Update Progress
            completed, q_data = await update_quest_progress(user_id, q_type)
            
            # 4. Handle Completion
            if completed and q_data:
                reward_text = []
                # Give Tokens
                if q_data.get('reward_tokens', 0) > 0:
                    bal = await get_user_balance(user_id)
                    await update_user_balance(user_id, bal + q_data['reward_tokens'])
                    reward_text.append(f"💰 {q_data['reward_tokens']} Tokens")
                
                # Give XP
                if q_data.get('reward_exp', 0) > 0:
                    lvl, exp = await get_leveling_data(user_id)
                    await update_leveling_data(user_id, lvl, exp + q_data['reward_exp'])
                    reward_text.append(f"⚡ {q_data['reward_exp']} XP")
                
                # Send Embed
                embed = discord.Embed(
                    title="🎉 Quest Completed!",
                    description=f"**{q_data['name']}**\n{q_data['description']}",
                    color=discord.Color.green()
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
        if message.author.bot: return
        # Trigger message quest updates
        await self.process_quest_update(str(message.author.id), message.channel, "message")

    # Kept to prevent errors if main.py expects them, but they do nothing for quests now
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild.id in self.invite_cache:
            self.invite_cache[invite.guild.id][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if guild.id not in self.invite_cache: return

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

    @app_commands.command(name="quests", description="View your current Daily and Weekly quests.")
    async def quests(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        embed = discord.Embed(title=f"📜 {interaction.user.display_name}'s Quests", color=discord.Color.blue())
        
        for q_type in ['daily', 'weekly']:
            quest = await get_active_quest(user_id, q_type)
            if not quest:
                quest = await assign_random_quest(user_id, q_type)
            
            title = f"{q_type.capitalize()} Quest"
            if quest:
                # Progress Bar Logic
                prog = quest.get('progress', 0)
                tgt = quest.get('target_count', 100)
                percent = int((prog / tgt) * 100)
                
                bar_len = 10
                filled = int(bar_len * percent / 100)
                bar = "🟩" * filled + "⬜" * (bar_len - filled)
                
                status = "✅ Completed" if quest.get('completed') else f"{bar} {percent}%"
                
                val = (f"{quest['description']}\n"
                       f"Rewards: Tokens: **{quest['reward_tokens']}** | XP: **{quest['reward_exp']}**\n"
                       f"Progress: `{prog}/{tgt}`\n"
                       f"{status}")
                embed.add_field(name=title, value=val, inline=False)
            else:
                embed.add_field(name=title, value="No active quest available.", inline=False)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Quests(bot))