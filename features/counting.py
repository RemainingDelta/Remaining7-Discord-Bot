import ast
import operator

import discord
from discord import app_commands
from discord.ext import commands

from database.mongo import get_counting_state, update_counting_state
from features.config import (
    ADMIN_ROLE_ID,
    COUNTING_CHANNEL_ID,
    FOUNDER_ROLE_ID,
    MODERATOR_ROLE_ID,
)

COUNTING_MOD_ROLES = {MODERATOR_ROLE_ID, ADMIN_ROLE_ID, FOUNDER_ROLE_ID}

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node):
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](
            _eval_node(node.left), _eval_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


def evaluate_count(content: str) -> int | None:
    """Return the integer value of a bare number or basic arithmetic
    expression (+, -, *, /, parentheses, unary +/-), or None if the content
    isn't a valid whole-number result."""
    content = content.strip()
    if not content:
        return None
    try:
        tree = ast.parse(content, mode="eval")
        result = _eval_node(tree.body)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None
    if isinstance(result, bool):
        return None
    if isinstance(result, float):
        if not result.is_integer():
            return None
        result = int(result)
    if not isinstance(result, int):
        return None
    return result


class Counting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.id != COUNTING_CHANNEL_ID:
            return

        state = await get_counting_state()
        current_count = state["current_count"]
        last_user_id = state["last_user_id"]
        expected = current_count + 1

        if message.author.id == last_user_id:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} You can't count twice in a row!",
                delete_after=5,
            )
            return

        number = evaluate_count(message.content)
        if number is None:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} That's not a valid number or expression! "
                f"Next number is **{expected}**.",
                delete_after=5,
            )
            return

        if number != expected:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} Wrong number! Next number is **{expected}**.",
                delete_after=5,
            )
            return

        await update_counting_state(number, message.author.id)

    @app_commands.command(
        name="set-count", description="Set the current count (staff only)."
    )
    @app_commands.describe(count="The number to set the count to")
    async def set_count(self, interaction: discord.Interaction, count: int):
        if not isinstance(interaction.user, discord.Member) or not any(
            role.id in COUNTING_MOD_ROLES for role in interaction.user.roles
        ):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return

        if interaction.channel_id != COUNTING_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{COUNTING_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await update_counting_state(count, None)
        await interaction.response.send_message(
            f"✅ Count set to **{count}**.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Counting(bot))
