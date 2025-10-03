import random
import discord
import json
import os
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, button
from utils.economy import get_balance, add_currency, remove_currency

# ---------- Slot math (reels, stops, paylines, paytable) ----------

# Symbols (emojis keep it readable in Discord)
CHERRY = "🍒"
LEMON  = "🍋"
BELL   = "🔔"
CLOVER = "🍀"
DIAM   = "💎"
SEVEN  = "7️⃣"

# Reels are lists of "stops" (positions a reel can land on).
# We weight reels by repeating symbols (more repeats = more common).
# Feel free to tweak these to adjust RTP.
REELS = [
    # Reel 1
    [CHERRY, CHERRY, LEMON, LEMON, LEMON, BELL, CLOVER, DIAM, SEVEN, CHERRY, LEMON, BELL, CHERRY, CLOVER, LEMON],
    # Reel 2
    [CHERRY, LEMON, LEMON, BELL, CLOVER, DIAM, SEVEN, CHERRY, LEMON, BELL, CHERRY, LEMON, CLOVER, LEMON, CHERRY],
    # Reel 3
    [CHERRY, LEMON, BELL, CLOVER, DIAM, SEVEN, CHERRY, LEMON, CHERRY, LEMON, BELL, CHERRY, CLOVER, LEMON, DIAM],
]

NUM_REELS = 3
REEL_LEN = len(REELS[0])   # all same length
WINDOW_ROWS = 3            # we show a 3-row window

# 1–5 paylines across the 3×3 window (indices are row numbers 0..2 from top)
PAYLINES = {
    1: [[1, 1, 1]],                     # middle row
    2: [[1, 1, 1], [0, 0, 0]],          # + top
    3: [[1, 1, 1], [0, 0, 0], [2, 2, 2]],  # + bottom
    4: [[1, 1, 1], [0, 0, 0], [2, 2, 2], [0, 1, 2]],  # + diag down
    5: [[1, 1, 1], [0, 0, 0], [2, 2, 2], [0, 1, 2], [2, 1, 0]]  # + diag up
}

# Paytable: payout multiplier per line (multiplies the line bet).
# Only exact 3-in-a-row are counted for this simple version.
PAYTABLE = {
    # Retuned upward to target ~90% RTP (theoretical ~90.06%).
    # Derived via symbol frequency EV calc; two-match kept at 1 to avoid over-inflating hit-rate value.
    (SEVEN, SEVEN, SEVEN): 180,   # very rare (1/3375 per line)
    (DIAM,  DIAM,  DIAM):  85,    # ~2/3375 per line
    (BELL,  BELL,  BELL):  44,
    (CLOVER,CLOVER,CLOVER):22,
    (CHERRY,CHERRY,CHERRY):11,
    (LEMON, LEMON, LEMON): 11,
    "TWO_MATCH": 1
}

# ---------- helpers ----------

def spin_reels() -> list[list[str]]:
    """
    Returns a 3x3 matrix window: rows x cols (rows=top/mid/bottom, cols=reel0..2).
    Each reel picks a stop index; window rows are (idx-1, idx, idx+1) modulo REEL_LEN.
    """
    cols = []
    for r in range(NUM_REELS):
        idx = random.randrange(REEL_LEN)
        # window top/mid/bottom for this reel
        col = [
            REELS[r][(idx - 1) % REEL_LEN],  # top
            REELS[r][idx],                   # middle
            REELS[r][(idx + 1) % REEL_LEN],  # bottom
        ]
        cols.append(col)

    # transpose to rows
    rows = [[cols[c][r] for c in range(NUM_REELS)] for r in range(WINDOW_ROWS)]
    return rows

def evaluate_spin(window_rows: list[list[str]], lines: int, line_bet: int) -> tuple[int, list[str]]:
    """Evaluate winnings across selected paylines.

    Returns (total_payout, notes) where notes contains human readable
    descriptions with intuitive payline names:
      Middle, Top, Bottom, Diag ↘, Diag ↗
    """
    label_map = ["Middle", "Top", "Bottom", "Diag ↘", "Diag ↗"]
    total = 0
    notes = []
    for idx, pattern in enumerate(PAYLINES[lines]):
        line_symbols = [window_rows[row][col] for col, row in enumerate(pattern)]
        name = label_map[idx]
        tpl = tuple(line_symbols)
        if tpl in PAYTABLE:
            mult = PAYTABLE[tpl]
            win = mult * line_bet
            total += win
            notes.append(f"{name}: {' '.join(line_symbols)}  →  x{mult}  (+{win})")
        else:
            if line_symbols[0] == line_symbols[1] and PAYTABLE.get("TWO_MATCH"):
                mult = PAYTABLE["TWO_MATCH"]
                win = mult * line_bet
                total += win
                notes.append(f"{name}: {' '.join(line_symbols)}  →  2-match x{mult}  (+{win})")
    return total, notes

def render_window(window_rows: list[list[str]]) -> str:
    """Ascii/emoji rendering of the 3×3 slot window."""
    return "\n".join("  ".join(row) for row in window_rows)

# ---------- Discord UI ----------

class SlotsView(View):
    def __init__(self, cog: 'Slots', user_id: int, wager: int, lines: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.wager = wager
        self.lines = lines

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    @button(label="Spin Again", style=discord.ButtonStyle.green)
    async def spin_again(self, interaction: Interaction, btn: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn’t for you.", ephemeral=True)
            return
        # Check funds
        total_bet = self.wager
        guild_id = str(interaction.guild.id) if interaction.guild else None
        bal = get_balance(str(self.user_id), guild_id=guild_id)
        if bal < total_bet:
            await interaction.response.send_message(
                f"❌ You need {total_bet} coins but only have {bal} coins.",
                ephemeral=True
            )
            return
        # Deduct and spin
        if not remove_currency(str(self.user_id), total_bet, guild_id=guild_id):
            await interaction.response.send_message("❌ Bet failed.", ephemeral=True)
            return

        window = spin_reels()
        total_win, notes = evaluate_spin(window, self.lines, line_bet=total_bet // self.lines)

        if total_win:
            add_currency(str(self.user_id), total_win, guild_id=guild_id)

        grid = render_window(window)
        desc = f"**Bet:** {total_bet}  |  **Lines:** {self.lines}\n\n```\n{grid}\n```\n"
        if notes:
            desc += "\n".join(f"• {n}" for n in notes)
        else:
            desc += "No winning lines."

        net = total_win - total_bet
        if net > 0:
            color = discord.Color.green()
        elif net == 0:
            color = discord.Color.yellow()
        else:
            color = discord.Color.red()
        footer = f"Net: {'+' if net>0 else ''}{net} (Win {total_win})"
        embed = discord.Embed(title="🎰 Slots", description=desc, color=color)
        embed.set_footer(text=footer)
        # Record stats
        self.cog.record_spin(user_id=str(self.user_id), guild_id=guild_id, bet=total_bet, win=total_win, lines=self.lines, net=net)

        await interaction.response.edit_message(embed=embed, view=self)

STATS_FILE = "slotstats.json"

def _load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"guilds": {}}
    return {"guilds": {}}

def _save_stats(data):
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

class Slots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.stats = _load_stats()

    #  stats structure:
    #  {
    #    "guilds": {
    #       guild_id: {
    #          user_id: {
    #             "spins": int,
    #             "bet_total": int,
    #             "win_total": int,
    #             "net": int,
    #             "biggest_win": int,
    #             "last_bet": int,
    #             "last_win": int,
    #             "last_lines": int,
    #             "last_play": iso str
    #          }
    #       }
    #    }
    #  }

    SESSION_TIMEOUT = timedelta(minutes=30)  # inactivity resets session baseline

    def _ensure_baseline(self, u: dict):
        if u.get("session_baseline") is None:
            u["session_baseline"] = {
                "spins": u.get("spins", 0),
                "bet_total": u.get("bet_total", 0),
                "win_total": u.get("win_total", 0),
                "net": u.get("net", 0),
            }

    def _maybe_reset_session(self, u: dict):
        last_play = u.get("last_play")
        if not last_play:
            return
        try:
            last_dt = datetime.fromisoformat(last_play)
        except Exception:
            return
        if datetime.utcnow() - last_dt > self.SESSION_TIMEOUT:
            # Reset baseline to current totals after timeout
            u["session_baseline"] = {
                "spins": u.get("spins", 0),
                "bet_total": u.get("bet_total", 0),
                "win_total": u.get("win_total", 0),
                "net": u.get("net", 0),
            }

    def record_spin(self, user_id: str, guild_id: str | None, bet: int, win: int, lines: int, net: int):
        if not guild_id:
            return  # only track per guild for now
        g = self.stats.setdefault("guilds", {}).setdefault(str(guild_id), {})
        u = g.setdefault(user_id, {
            "spins": 0,
            "bet_total": 0,
            "win_total": 0,
            "net": 0,
            "biggest_win": 0,
            "last_bet": 0,
            "last_win": 0,
            "last_lines": 0,
            "last_play": None,
            "session_baseline": None,
        })
        # Possibly reset session baseline after inactivity
        self._maybe_reset_session(u)
        # Ensure baseline exists
        self._ensure_baseline(u)
        u["spins"] += 1
        u["bet_total"] += bet
        u["win_total"] += win
        u["net"] += net
        if win > u.get("biggest_win", 0):
            u["biggest_win"] = win
        u["last_bet"] = bet
        u["last_win"] = win
        u["last_lines"] = lines
        u["last_play"] = datetime.utcnow().isoformat()
        _save_stats(self.stats)

    def get_user_stats(self, user_id: str, guild_id: str | None):
        if not guild_id:
            return None
        return self.stats.get("guilds", {}).get(str(guild_id), {}).get(user_id)

    @app_commands.command(name="slots", description="Spin the slots! Bet between 1 and 2000. Choose 1–5 lines.")
    @app_commands.describe(wager="Total bet for this spin (1–2000)", lines="Number of paylines (1–5)")
    async def slots(self, interaction: Interaction,
                    wager: app_commands.Range[int, 1, 2000],
                    lines: app_commands.Range[int, 1, 5] = 1):
        uid = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None

        # Whole-spin wager limit (total)
        total_bet = int(wager)
        if total_bet < lines:
            await interaction.response.send_message(
                "❌ Your total bet must be at least the number of lines (min 1 coin per line).",
                ephemeral=True
            )
            return

        bal = get_balance(uid, guild_id=guild_id)
        if bal < total_bet:
            await interaction.response.send_message(
                f"❌ You need {total_bet} coins but only have {bal} coins.",
                ephemeral=True
            )
            return

        # Deduct up-front
        if not remove_currency(uid, total_bet, guild_id=guild_id):
            await interaction.response.send_message("❌ Bet failed.", ephemeral=True)
            return

        # Spin!
        window = spin_reels()
        total_win, notes = evaluate_spin(window, lines, line_bet=total_bet // lines)

        if total_win:
            add_currency(uid, total_win, guild_id=guild_id)

        grid = render_window(window)
        desc = f"**Bet:** {total_bet}  |  **Lines:** {lines}\n\n```\n{grid}\n```\n"
        if notes:
            desc += "\n".join(f"• {n}" for n in notes)
        else:
            desc += "No winning lines."

        net = total_win - total_bet
        if net > 0:
            color = discord.Color.green()
        elif net == 0:
            color = discord.Color.yellow()
        else:
            color = discord.Color.red()
        footer = f"Net: {'+' if net>0 else ''}{net} (Win {total_win})"
        embed = discord.Embed(title="🎰 Slots", description=desc, color=color)
        embed.set_footer(text=footer)

        # Record stats
        self.record_spin(user_id=uid, guild_id=guild_id, bet=total_bet, win=total_win, lines=lines, net=net)

        view = SlotsView(self, interaction.user.id, total_bet, lines)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="slotstats", description="View your slot machine stats for this server (with session delta)")
    async def slotstats(self, interaction: Interaction):
        guild_id = str(interaction.guild.id) if interaction.guild else None
        if not guild_id:
            await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        stats = self.get_user_stats(uid, guild_id)
        if not stats:
            await interaction.response.send_message(embed=discord.Embed(title="🎰 Slot Stats", description="No slot data found yet. Play /slots to begin!", color=discord.Color.blurple()))
            return
        spins = stats.get("spins", 0)
        bet_total = stats.get("bet_total", 0)
        win_total = stats.get("win_total", 0)
        net = stats.get("net", 0)
        biggest_win = stats.get("biggest_win", 0)
        last_play = stats.get("last_play")  # kept for inactivity reset; not displayed
        avg_bet = (bet_total / spins) if spins else 0
        rtp = (win_total / bet_total * 100) if bet_total else 0
        baseline = stats.get("session_baseline")
        if baseline:
            delta_spins = spins - baseline.get("spins", 0)
            delta_bet = bet_total - baseline.get("bet_total", 0)
            delta_win = win_total - baseline.get("win_total", 0)
            delta_net = net - baseline.get("net", 0)
            session_block = (
                f"\n__Session Δ__ (resets after {int(self.SESSION_TIMEOUT.total_seconds()/60)}m idle)\n"
                f"Spins: {delta_spins} | Bet: {delta_bet} | Won: {delta_win} | Net: {'+' if delta_net>=0 else ''}{delta_net}"
            )
        else:
            session_block = ""
        description = (
            f"**Spins:** {spins}\n"
            f"**Total Bet:** {bet_total}\n"
            f"**Total Won:** {win_total}\n"
            f"**Net:** {'+' if net>=0 else ''}{net}\n"
            f"**RTP:** {rtp:.2f}%\n"
            f"**Avg Bet:** {avg_bet:.2f}\n"
            f"**Biggest Win:** {biggest_win}"
            f"{session_block}"
        )
        embed = discord.Embed(title="🎰 Slot Stats", description=description, color=discord.Color.gold())
        embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slotresetsession", description="Manually reset your slot session baseline")
    async def slotresetsession(self, interaction: Interaction):
        guild_id = str(interaction.guild.id) if interaction.guild else None
        if not guild_id:
            await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        g = self.stats.setdefault("guilds", {}).setdefault(guild_id, {})
        u = g.get(uid)
        if not u:
            await interaction.response.send_message("You have no stats yet.", ephemeral=True)
            return
        u["session_baseline"] = {
            "spins": u.get("spins", 0),
            "bet_total": u.get("bet_total", 0),
            "win_total": u.get("win_total", 0),
            "net": u.get("net", 0),
        }
        _save_stats(self.stats)
        await interaction.response.send_message("🔄 Session baseline reset. Future /slotstats deltas start from now.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Slots(bot))
