import asyncio
import json
import os
import random

import discord
from discord import app_commands, Interaction, Embed
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput

from utils.economy import get_balance, remove_currency, add_currency
from utils.casino_cooldown import cooldown_remaining_seconds, set_last_casino_play


CASINO_CONFIG_FILE = "casino_config.json"  # shared with blackjack/slots


def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def get_blackjack_cooldown_seconds(guild_id: str | None) -> int:
    if not guild_id:
        return 15
    cfg = _load_json(CASINO_CONFIG_FILE)
    g = cfg.get(str(guild_id), {}) if isinstance(cfg, dict) else {}
    if not isinstance(g, dict):
        return 15
    try:
        sec = int(g.get("blackjack_cooldown", 15))
    except Exception:
        sec = 15
    return max(10, sec)


def normalize_pick(pick: str) -> str:
    return (pick or "").strip().lower()


def parse_pocket(pick: str) -> tuple[str, str] | None:
    """Return (bet_type, value) where bet_type in {color, number}."""
    p = normalize_pick(pick)
    if p in {"red", "black", "green"}:
        return ("color", p)
    # number: accept 0, 00, 1-36
    if p == "00":
        return ("number", "00")
    if p.isdigit():
        try:
            n = int(p)
        except Exception:
            return None
        if n == 0:
            return ("number", "0")
        if 1 <= n <= 36:
            return ("number", str(n))
    return None


def pocket_color(pocket: str) -> str:
    """Return 'green', 'red', or 'black' for a pocket string."""
    if pocket in {"0", "00"}:
        return "green"
    try:
        n = int(pocket)
    except Exception:
        return "green"
    # Standard American roulette coloring for 1–36
    red = {
        1, 3, 5, 7, 9,
        12, 14, 16, 18,
        19, 21, 23, 25, 27,
        30, 32, 34, 36,
    }
    return "red" if n in red else "black"


def spin_result() -> str:
    """Spin an American 38-pocket wheel: 0, 00, 1–36."""
    pockets = ["0", "00"] + [str(i) for i in range(1, 37)]
    return random.choice(pockets)


def format_pocket(pocket: str) -> str:
    col = pocket_color(pocket)
    if col == "red":
        return f"**{pocket} (red)**"
    if col == "black":
        return f"**{pocket} (black)**"
    return f"**{pocket} (green)**"


def payout_total(bet: int, bet_type: str, value: str, result_pocket: str) -> tuple[bool, int, str]:
    """Return (won, total_return, reason).

    total_return is the amount to add back after the wager is removed.
    """
    res_color = pocket_color(result_pocket)
    if bet_type == "color":
        # red/black: 2x total; green: 18x total (2 green pockets)
        if value == res_color:
            mult = 2 if value in {"red", "black"} else 18
            return True, bet * mult, f"Matched color **{value}**"
        return False, 0, f"Landed on {format_pocket(result_pocket)}"

    if bet_type == "number":
        if value == result_pocket:
            return True, bet * 36, f"Hit exact number **{value}**"
        return False, 0, f"Landed on {format_pocket(result_pocket)}"

    return False, 0, "Invalid bet"


async def ticking_animation(interaction: Interaction, bet_desc: str, ticks: int = 5) -> str:
    """Edit the original response several times to simulate a ticking wheel.

    The final (nth) tick result is the actual outcome.
    Returns the final pocket.
    """
    ticks = max(1, int(ticks))
    seq: list[str] = [spin_result() for _ in range(ticks)]
    final_pocket = seq[-1]

    embed = Embed(title="🎡 Roulette", description=f"Bet: {bet_desc}\n\nSpinning...", color=discord.Color.blurple())
    await interaction.edit_original_response(embed=embed, view=None)

    shown: list[str] = []
    for i, p in enumerate(seq):
        shown.append(p)
        trail = " → ".join(format_pocket(x) for x in shown[-5:])
        embed = Embed(
            title="🎡 Roulette",
            description=f"Bet: {bet_desc}\n\n{trail}",
            color=discord.Color.blurple() if i < len(seq) - 1 else discord.Color.gold(),
        )
        await interaction.edit_original_response(embed=embed, view=None)
        await asyncio.sleep(0.55 if i < len(seq) - 1 else 0.15)

    return final_pocket


class NumberModal(Modal, title="Roulette: Pick a Number"):
    number = TextInput(
        label="Number (0, 00, or 1-36)",
        placeholder="e.g. 17 or 00",
        required=True,
        max_length=2,
    )

    def __init__(self, parent_view: 'RoulettePickView'):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: Interaction):
        await self.parent_view.handle_pick(interaction, str(self.number.value))


class RoulettePickView(View):
    def __init__(self, cog: 'Roulette', author_id: int, bet: int):
        super().__init__(timeout=45)
        self.cog = cog
        self.author_id = int(author_id)
        self.bet = int(bet)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This roulette menu isn't for you.", ephemeral=True)
            return False
        return True

    async def handle_pick(self, interaction: Interaction, pick: str):
        parsed = parse_pocket(pick)
        if not parsed:
            await interaction.response.send_message(
                embed=Embed(
                    title="❌ Invalid Pick",
                    description="Pick `red`, `black`, `green`, or a number `0`, `00`, `1–36`.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return
        await self.cog._play(interaction, bet=self.bet, bet_type=parsed[0], value=parsed[1])

    @discord.ui.button(label="Red", style=discord.ButtonStyle.danger)
    async def red(self, interaction: Interaction, button: Button):
        await self.handle_pick(interaction, "red")

    @discord.ui.button(label="Black", style=discord.ButtonStyle.secondary)
    async def black(self, interaction: Interaction, button: Button):
        await self.handle_pick(interaction, "black")

    @discord.ui.button(label="Green", style=discord.ButtonStyle.success)
    async def green(self, interaction: Interaction, button: Button):
        await self.handle_pick(interaction, "green")

    @discord.ui.button(label="Pick Number", style=discord.ButtonStyle.primary)
    async def number(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(NumberModal(self))


class Roulette(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _play(self, interaction: Interaction, bet: int, bet_type: str, value: str):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)
        gid = str(guild.id)

        # Same cooldown as blackjack (shared across casino games)
        cd = get_blackjack_cooldown_seconds(gid)
        remaining = cooldown_remaining_seconds(gid, uid, cd)
        if remaining > 0:
            await interaction.response.send_message(
                embed=Embed(
                    title="⏳ Slow Down",
                    description=f"Please wait **{remaining}s** before playing roulette again.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        # Bet limits similar to slots default range
        if bet < 1 or bet > 10000:
            await interaction.response.send_message(
                embed=Embed(title="❌ Invalid Bet", description="Bet must be between 1 and 10000.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        bal = get_balance(uid, guild_id=gid)
        if bal < bet:
            await interaction.response.send_message(
                embed=Embed(title="❌ Insufficient Funds", description=f"You need {bet} coins but only have {bal} coins.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        # Deduct wager first
        if not remove_currency(uid, bet, guild_id=gid):
            await interaction.response.send_message(
                embed=Embed(title="❌ Bet Failed", description="Failed to place bet (insufficient funds).", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        # Start cooldown after wager succeeds
        try:
            set_last_casino_play(gid, uid)
        except Exception:
            pass

        bet_desc = f"**{bet:,}** on **{value}**" if bet_type == "number" else f"**{bet:,}** on **{value.capitalize()}**"

        # Acknowledge interaction and begin ticking edits
        if interaction.response.is_done():
            # should not happen, but fail safe
            pass
        else:
            await interaction.response.send_message(embed=Embed(title="🎡 Roulette", description=f"Bet: {bet_desc}\n\nSpinning...", color=discord.Color.blurple()))

        result = await ticking_animation(interaction, bet_desc=bet_desc, ticks=5)

        won, total_return, reason = payout_total(bet, bet_type, value, result)
        if won and total_return > 0:
            add_currency(uid, total_return, guild_id=gid)

        new_bal = get_balance(uid, guild_id=gid)
        color = discord.Color.green() if won else discord.Color.red()
        title = "✅ You won!" if won else "❌ You lost"
        payout_line = f"Payout: **{total_return:,}**" if won else "Payout: **0**"

        embed = Embed(
            title=f"🎡 Roulette — {title}",
            description=(
                f"Result: {format_pocket(result)}\n"
                f"{reason}\n\n"
                f"Bet: {bet_desc}\n"
                f"{payout_line}\n"
                "Odds: Red/Black pays **1:1**, Green (0/00) pays **17:1**, Number pays **35:1**\n"
                f"Balance: **{new_bal:,}**"
            ),
            color=color,
        )
        await interaction.edit_original_response(embed=embed, view=None)

    @app_commands.command(name="roulette", description="Play roulette: place a bet, then choose via buttons.")
    @app_commands.describe(bet="Coins to wager")
    async def roulette(self, interaction: Interaction, bet: int):
        view = RoulettePickView(self, author_id=interaction.user.id, bet=bet)
        await interaction.response.send_message(
            embed=Embed(
                title="🎡 Roulette",
                description=(
                    f"Bet: **{bet:,}**\n\n"
                    "Choose a color, or pick a number."
                ),
                color=discord.Color.blurple(),
            ),
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Roulette(bot))
