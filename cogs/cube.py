import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands, Interaction
from discord.ext import commands

from utils.debug import debug_command

DATA_FILE = Path(__file__).resolve().parents[1] / "cube_data.json"
MAX_SOLVES = 200
PUZZLES = ["2x2", "3x3", "4x4"]

AXES = {"U": 0, "D": 0, "L": 1, "R": 1, "F": 2, "B": 2}


# ---------------------------------------------------------------- scrambles
def generate_scramble(puzzle: str = "3x3", rng: random.Random | None = None) -> str:
    rng = rng or random
    if puzzle == "2x2":
        faces, length = ["U", "R", "F"], 11
    elif puzzle == "4x4":
        faces, length = ["U", "D", "L", "R", "F", "B"], 40
    else:
        faces, length = ["U", "D", "L", "R", "F", "B"], 20

    moves: list[str] = []
    history: list[str] = []  # base faces only
    while len(moves) < length:
        face = rng.choice(faces)
        if history and face == history[-1]:
            continue
        # no same-axis triple (e.g. R L R)
        if len(history) >= 2 and AXES[history[-1]] == AXES[history[-2]] and AXES[face] == AXES[history[-1]]:
            continue
        history.append(face)
        move = face
        if puzzle == "4x4" and rng.random() < 0.4:
            move = face + "w"
        moves.append(move + rng.choice(["", "'", "2"]))
    return " ".join(moves)


# -------------------------------------------------------------------- times
_TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2})(?:[.,](\d{1,3}))?$")


def parse_time(text: str) -> Optional[int]:
    """'12.34' / '1:02.34' -> milliseconds, or None if invalid."""
    m = _TIME_RE.match(text.strip())
    if not m:
        return None
    mins = int(m.group(1) or 0)
    secs = int(m.group(2))
    frac = (m.group(3) or "0").ljust(3, "0")[:3]
    if m.group(1) is not None and secs >= 60:
        return None
    ms = (mins * 60 + secs) * 1000 + int(frac)
    return ms if 0 < ms <= 99 * 60 * 1000 else None


def fmt_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "DNF"
    cs = int(round(ms / 10.0))
    total_s, cs = divmod(cs, 100)
    mins, s = divmod(total_s, 60)
    return f"{mins}:{s:02d}.{cs:02d}" if mins else f"{s}.{cs:02d}"


def eff(solve: dict) -> Optional[int]:
    """Effective time in ms including penalty; None for DNF."""
    if solve.get("pen") == "DNF" or solve.get("t") is None:
        return None
    return solve["t"] + (2000 if solve.get("pen") == "+2" else 0)


def average(solves: list[dict], n: int) -> Optional[float]:
    """WCA-style average of the last n solves. Returns None if there are too few
    solves, and float('inf') for a DNF average."""
    if len(solves) < n:
        return None
    times = [eff(s) for s in solves[-n:]]
    vals = [float("inf") if t is None else t for t in times]
    vals.sort()
    trim = 1 if n <= 12 else max(1, int(round(n * 0.05)))
    kept = vals[trim:n - trim]
    if any(v == float("inf") for v in kept):
        return float("inf")
    return sum(kept) / len(kept)


def best_average(solves: list[dict], n: int) -> Optional[float]:
    best = None
    for i in range(n, len(solves) + 1):
        a = average(solves[:i], n)
        if a is not None and a != float("inf") and (best is None or a < best):
            best = a
    return best


def fmt_avg(a: Optional[float]) -> str:
    if a is None:
        return "-"
    return "DNF" if a == float("inf") else fmt_ms(a)


# ------------------------------------------------------------------ storage
def _load() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


# --------------------------------------------------------------- timer view
class TimerView(discord.ui.View):
    def __init__(self, cog: "Cube", user: discord.abc.User, guild_id: int, puzzle: str, scramble: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.user = user
        self.guild_id = guild_id
        self.puzzle = puzzle
        self.scramble = scramble
        self.start_at: Optional[datetime] = None
        self.elapsed_ms: Optional[int] = None
        self.pen = ""
        self.message: Optional[discord.Message] = None
        self._phase_start()

    # ---- helpers
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "This isn't your timer. Use `/cube timer` to start your own.", ephemeral=True)
            return False
        return True

    def _btn(self, label, style, cb):
        b = discord.ui.Button(label=label, style=style)
        b.callback = cb
        self.add_item(b)

    def _phase_start(self):
        self.clear_items()
        self._btn("▶ Start", discord.ButtonStyle.success, self.on_start)

    def _phase_running(self):
        self.clear_items()
        self._btn("⏹ Stop", discord.ButtonStyle.danger, self.on_stop)

    def _phase_done(self):
        self.clear_items()
        self._btn("💾 Save", discord.ButtonStyle.success, self.on_save)
        self._btn("+2", discord.ButtonStyle.primary if self.pen == "+2" else discord.ButtonStyle.secondary, self.on_plus2)
        self._btn("DNF", discord.ButtonStyle.primary if self.pen == "DNF" else discord.ButtonStyle.secondary, self.on_dnf)
        self._btn("🗑 Discard", discord.ButtonStyle.secondary, self.on_discard)

    def _embed(self, title: str, extra: str = "") -> discord.Embed:
        e = discord.Embed(title=title, color=discord.Color.blurple())
        e.add_field(name=f"Scramble ({self.puzzle})", value=f"```{self.scramble}```", inline=False)
        if extra:
            e.description = extra
        return e

    def _result_embed(self) -> discord.Embed:
        solve = {"t": self.elapsed_ms, "pen": self.pen}
        e = self._embed("⏱ Solve finished", f"**Time: {fmt_ms(eff(solve))}**" + (f"  ({self.pen})" if self.pen else ""))
        e.set_footer(text="Button timing is accurate to about ±0.2s (network latency).")
        return e

    # ---- callbacks
    async def on_start(self, interaction: Interaction):
        self.start_at = interaction.created_at
        self._phase_running()
        await interaction.response.edit_message(
            embed=self._embed("🟢 Solving...", "Press **Stop** when you're done."), view=self)

    async def on_stop(self, interaction: Interaction):
        self.elapsed_ms = max(1, int((interaction.created_at - self.start_at).total_seconds() * 1000))
        self._phase_done()
        await interaction.response.edit_message(embed=self._result_embed(), view=self)

    async def on_plus2(self, interaction: Interaction):
        self.pen = "" if self.pen == "+2" else "+2"
        self._phase_done()
        await interaction.response.edit_message(embed=self._result_embed(), view=self)

    async def on_dnf(self, interaction: Interaction):
        self.pen = "" if self.pen == "DNF" else "DNF"
        self._phase_done()
        await interaction.response.edit_message(embed=self._result_embed(), view=self)

    async def on_save(self, interaction: Interaction):
        self.cog.add_solve(self.guild_id, self.user.id, self.puzzle, self.elapsed_ms, self.pen, self.scramble)
        self.stop()
        e = self._result_embed()
        e.title = "✅ Solve saved"
        await interaction.response.edit_message(embed=e, view=None)

    async def on_discard(self, interaction: Interaction):
        self.stop()
        await interaction.response.edit_message(embed=self._embed("🗑 Solve discarded"), view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass


# ---------------------------------------------------------------------- cog
PUZZLE_CHOICES = [app_commands.Choice(name=p, value=p) for p in PUZZLES]


class Cube(commands.Cog):
    cube = app_commands.Group(name="cube", description="Rubik's cube scrambles, timer and leaderboard", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = _load()
        # (guild_id, user_id) -> (puzzle, scramble) from the latest scramble they were shown
        self.last_scramble: dict[tuple[int, int], tuple[str, str]] = {}

    def add_solve(self, guild_id: int, user_id: int, puzzle: str, t: int, pen: str, scramble: str):
        solves = self.data.setdefault(str(guild_id), {}).setdefault(str(user_id), {}).setdefault(puzzle, [])
        solves.append({"t": t, "pen": pen, "scr": scramble, "at": datetime.now(timezone.utc).isoformat()})
        del solves[:-MAX_SOLVES]
        _save(self.data)

    def get_solves(self, guild_id: int, user_id: int, puzzle: str) -> list[dict]:
        return self.data.get(str(guild_id), {}).get(str(user_id), {}).get(puzzle, [])

    @cube.command(name="scramble", description="Get a random scramble.")
    @app_commands.describe(puzzle="Which puzzle (default 3x3)")
    @app_commands.choices(puzzle=PUZZLE_CHOICES)
    async def scramble(self, interaction: Interaction, puzzle: app_commands.Choice[str] = None):
        p = puzzle.value if puzzle else "3x3"
        debug_command("cube scramble", interaction.user, interaction.guild, puzzle=p)
        scr = generate_scramble(p)
        self.last_scramble[(interaction.guild_id, interaction.user.id)] = (p, scr)
        e = discord.Embed(title=f"🧊 {p} scramble", description=f"```{scr}```", color=discord.Color.blurple())
        await interaction.response.send_message(embed=e)

    @cube.command(name="timer", description="Scramble plus a button timer.")
    @app_commands.describe(puzzle="Which puzzle (default 3x3)")
    @app_commands.choices(puzzle=PUZZLE_CHOICES)
    async def timer(self, interaction: Interaction, puzzle: app_commands.Choice[str] = None):
        p = puzzle.value if puzzle else "3x3"
        debug_command("cube timer", interaction.user, interaction.guild, puzzle=p)
        scr = generate_scramble(p)
        self.last_scramble[(interaction.guild_id, interaction.user.id)] = (p, scr)
        view = TimerView(self, interaction.user, interaction.guild_id, p, scr)
        await interaction.response.send_message(
            embed=view._embed("🧊 Ready?", "Press **Start**, solve, then press **Stop**."), view=view)
        view.message = await interaction.original_response()

    @cube.command(name="submit", description="Submit a time from a real timer.")
    @app_commands.describe(time="e.g. 12.34 or 1:02.34", puzzle="Which puzzle (default 3x3)", penalty="Optional penalty")
    @app_commands.choices(puzzle=PUZZLE_CHOICES, penalty=[
        app_commands.Choice(name="none", value=""),
        app_commands.Choice(name="+2", value="+2"),
        app_commands.Choice(name="DNF", value="DNF")])
    async def submit(self, interaction: Interaction, time: str, puzzle: app_commands.Choice[str] = None,
                     penalty: app_commands.Choice[str] = None):
        p = puzzle.value if puzzle else "3x3"
        debug_command("cube submit", interaction.user, interaction.guild, time=time, puzzle=p)
        ms = parse_time(time)
        if ms is None:
            await interaction.response.send_message(
                "❌ I couldn't read that time. Try `12.34` or `1:02.34`.", ephemeral=True)
            return
        pen = penalty.value if penalty else ""
        last = self.last_scramble.get((interaction.guild_id, interaction.user.id))
        scr = last[1] if last and last[0] == p else ""
        self.add_solve(interaction.guild_id, interaction.user.id, p, ms, pen, scr)
        solve = {"t": ms, "pen": pen}
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Solve saved",
            description=f"{interaction.user.mention}: **{fmt_ms(eff(solve))}** on {p}" + (f" ({pen})" if pen else ""),
            color=discord.Color.green()))

    @cube.command(name="leaderboard", description="Server leaderboard by best single.")
    @app_commands.describe(puzzle="Which puzzle (default 3x3)")
    @app_commands.choices(puzzle=PUZZLE_CHOICES)
    async def leaderboard(self, interaction: Interaction, puzzle: app_commands.Choice[str] = None):
        p = puzzle.value if puzzle else "3x3"
        debug_command("cube leaderboard", interaction.user, interaction.guild, puzzle=p)
        rows = []
        for uid, per_puzzle in self.data.get(str(interaction.guild_id), {}).items():
            solves = per_puzzle.get(p, [])
            valid = [eff(s) for s in solves if eff(s) is not None]
            if valid:
                rows.append((min(valid), best_average(solves, 5), len(solves), uid))
        rows.sort(key=lambda r: r[0])
        if not rows:
            await interaction.response.send_message(
                f"No {p} solves yet. Use `/cube timer` to be the first!", ephemeral=True)
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (single, ao5, n, uid) in enumerate(rows[:10]):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{prefix} <@{uid}> **{fmt_ms(single)}** · best Ao5 {fmt_avg(ao5)} · {n} solves")
        await interaction.response.send_message(embed=discord.Embed(
            title=f"🏆 {p} leaderboard", description="\n".join(lines), color=discord.Color.gold()))

    @cube.command(name="times", description="Your recent solves and averages.")
    @app_commands.describe(puzzle="Which puzzle (default 3x3)")
    @app_commands.choices(puzzle=PUZZLE_CHOICES)
    async def times(self, interaction: Interaction, puzzle: app_commands.Choice[str] = None):
        p = puzzle.value if puzzle else "3x3"
        debug_command("cube times", interaction.user, interaction.guild, puzzle=p)
        solves = self.get_solves(interaction.guild_id, interaction.user.id, p)
        if not solves:
            await interaction.response.send_message(f"You have no {p} solves yet.", ephemeral=True)
            return
        recent = solves[-12:]
        lines = []
        for s in reversed(recent):
            t = fmt_ms(eff(s))
            lines.append(t + (" (+2)" if s.get("pen") == "+2" else ""))
        e = discord.Embed(title=f"⏱ Your {p} times", description=" · ".join(lines), color=discord.Color.blurple())
        e.add_field(name="Current Ao5", value=fmt_avg(average(solves, 5)), inline=True)
        e.add_field(name="Current Ao12", value=fmt_avg(average(solves, 12)), inline=True)
        e.add_field(name="Solves", value=str(len(solves)), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cube(bot))
