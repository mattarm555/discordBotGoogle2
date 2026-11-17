from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands, Interaction
from discord.ext import commands

from utils.daytime import today
from utils.debug import debug_command

# (emoji, name, description) shown when earned
BADGES = {
    "wordle_week": ("🟩", "Wordle Week", "7-day Wordle win streak"),
    "wordle_wiz": ("🧩", "Wordle Wizard", "25 Wordle wins"),
    "trivia_hot": ("🧠", "Quiz Whiz", "10 trivia answers in a row"),
    "daily_week": ("📅", "Daily Devotee", "7-day daily trivia streak"),
    "cube_sub30": ("⚡", "Speedcuber", "3x3 single under 30 seconds"),
    "cube_grind": ("🧊", "Cube Grinder", "50 saved solves"),
    "xp_10": ("📈", "Level 10", "Reached XP level 10"),
}


def _cog_data(bot: commands.Bot, cog_name: str, attr: str = "data"):
    cog = bot.get_cog(cog_name)
    return getattr(cog, attr, None) if cog else None


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------ sections
    def _xp(self, gid: str, uid: str) -> Optional[tuple[str, int]]:
        xp = _cog_data(self.bot, "XP", "xp_data")
        if not xp or uid not in xp.get(gid, {}):
            return None
        users = xp[gid]
        order = sorted(users.items(), key=lambda kv: (kv[1].get("level", 1), kv[1].get("xp", 0)), reverse=True)
        rank = next((i for i, (u, _) in enumerate(order, 1) if u == uid), None)
        me = users[uid]
        return f"Level **{me.get('level', 1)}** · {me.get('xp', 0)} XP" + (f" · rank **#{rank}**" if rank else ""), me.get("level", 1)

    def _wordle(self, gid: str, uid: str):
        data = _cog_data(self.bot, "Wordle")
        st = (data or {}).get(gid, {}).get("stats", {}).get(uid)
        if not st or not st.get("played"):
            return None
        d = today()
        alive = st["last"] in (d.isoformat(), (d - timedelta(days=1)).isoformat())
        streak = st["streak"] if alive else 0
        avg = sum((i + 1) * n for i, n in enumerate(st["dist"])) / st["wins"] if st["wins"] else None
        text = (f"**{st['wins']}** wins / {st['played']} played · 🔥 **{streak}** (best {st['max']})"
                + (f" · avg {avg:.2f}" if avg else ""))
        return text, st

    def _trivia(self, gid: str, uid: str):
        trivia = self.bot.get_cog("Trivia")
        if not trivia:
            return None
        u = trivia.get_user(int(gid), int(uid))
        daily = trivia.daily_stats(int(gid), int(uid))
        lines = []
        if u:
            pct = round(100 * u["correct"] / u["total"]) if u["total"] else 0
            lines.append(f"Best streak **{u['best']}** · {u['correct']}/{u['total']} correct ({pct}%)")
        if daily.get("played"):
            lines.append(f"📅 Daily: 🔥 **{trivia.daily_streak(int(gid), int(uid))}** (best {daily['best']}) · "
                         f"{daily['correct']}/{daily['played']} correct")
        return ("\n".join(lines), u, daily) if lines else None

    def _cube(self, gid: str, uid: str):
        cube_cog = self.bot.get_cog("Cube")
        if not cube_cog:
            return None
        from cogs.cube import PUZZLES, best_average, eff, fmt_avg, fmt_ms
        lines, singles, total = [], {}, 0
        for p in PUZZLES:
            solves = cube_cog.get_solves(int(gid), int(uid), p)
            if not solves:
                continue
            total += len(solves)
            times = [t for t in (eff(s) for s in solves) if t is not None]
            if not times:
                continue
            singles[p] = min(times)
            ao5 = best_average(solves, 5)
            lines.append(f"**{p}** single {fmt_ms(min(times))}" + (f" · Ao5 {fmt_avg(ao5)}" if ao5 is not None else "")
                         + f" · {len(solves)} solves")
        return ("\n".join(lines), singles, total) if lines else None

    # ------------------------------------------------------------- command
    @app_commands.command(name="profile", description="Your game stats and badges in one place.")
    @app_commands.describe(user="Whose profile to show (default: you)")
    @app_commands.guild_only()
    async def profile(self, interaction: Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        debug_command("profile", interaction.user, interaction.guild, target=target.name)
        gid, uid = str(interaction.guild_id), str(target.id)

        e = discord.Embed(title=f"🎮 {target.display_name}'s profile", color=target.color
                          if target.color.value else discord.Color.blurple())
        e.set_thumbnail(url=target.display_avatar.url)
        earned: set[str] = set()
        shown = 0

        xp = self._xp(gid, uid)
        if xp:
            e.add_field(name="📈 XP", value=xp[0], inline=False)
            shown += 1
            if xp[1] >= 10:
                earned.add("xp_10")

        w = self._wordle(gid, uid)
        if w:
            e.add_field(name="🟩 Wordle", value=w[0], inline=False)
            shown += 1
            st = w[1]
            if st["max"] >= 7:
                earned.add("wordle_week")
            if st["wins"] >= 25:
                earned.add("wordle_wiz")

        t = self._trivia(gid, uid)
        if t:
            e.add_field(name="🧠 Trivia", value=t[0], inline=False)
            shown += 1
            if t[1] and t[1]["best"] >= 10:
                earned.add("trivia_hot")
            if t[2].get("best", 0) >= 7:
                earned.add("daily_week")

        c = self._cube(gid, uid)
        if c:
            e.add_field(name="🧊 Cube", value=c[0], inline=False)
            shown += 1
            if c[1].get("3x3", 10 ** 9) < 30000:
                earned.add("cube_sub30")
            if c[2] >= 50:
                earned.add("cube_grind")

        if not shown:
            await interaction.response.send_message(
                f"{target.display_name} hasn't played anything yet. Try `/wordle play` or `/trivia daily`!",
                ephemeral=True)
            return

        if earned:
            e.add_field(name=f"🏅 Badges ({len(earned)}/{len(BADGES)})",
                        value="\n".join(f"{BADGES[k][0]} **{BADGES[k][1]}** · {BADGES[k][2]}"
                                        for k in BADGES if k in earned), inline=False)
        else:
            e.add_field(name="🏅 Badges", value=f"None yet · {len(BADGES)} to earn", inline=False)
        e.set_footer(text=f"Active in {shown} of 4 games")
        await interaction.response.send_message(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
