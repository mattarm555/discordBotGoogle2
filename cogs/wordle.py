import asyncio
import hashlib
import io
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, Interaction, ui
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from utils.botadmin import is_bot_admin
from utils.debug import debug_command

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "wordle_data.json"
ANSWERS_FILE = ROOT / "data" / "wordle_answers.txt"
VALID_FILE = ROOT / "data" / "wordle_valid.txt"

MAX_GUESSES = 6
KEEP_DAYS = 7
VIEW_TIMEOUT = 60 * 60  # Guess button stays live for an hour; /wordle play brings it back
EPOCH = date(2026, 1, 1)  # puzzle #1
SQUARE = {"g": "🟩", "y": "🟨", "b": "⬛"}


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.getenv("WORDLE_TZ", "America/New_York"))
    except Exception:
        return ZoneInfo("UTC")


def today() -> date:
    return datetime.now(_tz()).date()


def puzzle_number(d: date) -> int:
    return (d - EPOCH).days + 1


def _read_words(path: Path) -> list[str]:
    return [w.strip().lower() for w in path.read_text(encoding="utf-8").splitlines() if len(w.strip()) == 5]


def answer_for(answers: list[str], guild_id: int, d: date) -> str:
    h = int.from_bytes(hashlib.sha256(f"{guild_id}:{d.isoformat()}".encode()).digest()[:8], "big")
    return answers[h % len(answers)]


def score(guess: str, answer: str) -> str:
    """Return a 5-char string of g/y/b. Greens first, then yellows from the remaining letter counts."""
    res = ["b"] * 5
    remaining: dict[str, int] = {}
    for i in range(5):
        if guess[i] == answer[i]:
            res[i] = "g"
        else:
            remaining[answer[i]] = remaining.get(answer[i], 0) + 1
    for i in range(5):
        if res[i] == "g":
            continue
        if remaining.get(guess[i], 0) > 0:
            res[i] = "y"
            remaining[guess[i]] -= 1
    return "".join(res)


def letter_states(guesses: list[str], answer: str) -> dict[str, str]:
    best: dict[str, str] = {}
    rank = {"b": 0, "y": 1, "g": 2}
    for g in guesses:
        for ch, c in zip(g, score(g, answer)):
            if ch not in best or rank[c] > rank[best[ch]]:
                best[ch] = c
    return best


def emoji_grid(guesses: list[str], answer: str) -> str:
    return "\n".join("".join(SQUARE[c] for c in score(g, answer)) for g in guesses)


# ------------------------------------------------------------------ image
BG = (18, 18, 19)
COLORS = {"g": (83, 141, 78), "y": (181, 159, 59), "b": (58, 58, 60)}
EMPTY_BORDER = (58, 58, 60)
KEY_UNUSED = (129, 131, 132)
WHITE = (255, 255, 255)
KB_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]

TILE, GAP = 62, 6
KEY_W, KEY_H, KEY_GAP = 40, 54, 6
PAD = 20
WIDTH = PAD * 2 + 10 * KEY_W + 9 * KEY_GAP
BOARD_W = 5 * TILE + 4 * GAP
HEIGHT = PAD + MAX_GUESSES * TILE + (MAX_GUESSES - 1) * GAP + 28 + 3 * KEY_H + 2 * KEY_GAP + PAD


def _font(size: int):
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        for base in ("", "C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/"):
            try:
                return ImageFont.truetype(base + name, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


_TILE_FONT = _font(34)
_KEY_FONT = _font(20)


def render_image(guesses: list[str], answer: str) -> io.BytesIO:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    x0 = (WIDTH - BOARD_W) // 2

    for r in range(MAX_GUESSES):
        word = guesses[r] if r < len(guesses) else ""
        sc = score(word, answer) if word else ""
        for c in range(5):
            x = x0 + c * (TILE + GAP)
            y = PAD + r * (TILE + GAP)
            box = (x, y, x + TILE - 1, y + TILE - 1)
            if word:
                d.rectangle(box, fill=COLORS[sc[c]])
                d.text((x + TILE / 2, y + TILE / 2), word[c].upper(), font=_TILE_FONT, fill=WHITE, anchor="mm")
            else:
                d.rectangle(box, outline=EMPTY_BORDER, width=2)

    states = letter_states(guesses, answer)
    ky = PAD + MAX_GUESSES * TILE + (MAX_GUESSES - 1) * GAP + 28
    for i, row in enumerate(KB_ROWS):
        row_w = len(row) * KEY_W + (len(row) - 1) * KEY_GAP
        kx = (WIDTH - row_w) // 2
        y = ky + i * (KEY_H + KEY_GAP)
        for j, ch in enumerate(row):
            x = kx + j * (KEY_W + KEY_GAP)
            fill = COLORS[states[ch]] if ch in states else KEY_UNUSED
            d.rounded_rectangle((x, y, x + KEY_W - 1, y + KEY_H - 1), radius=5, fill=fill)
            d.text((x + KEY_W / 2, y + KEY_H / 2), ch.upper(), font=_KEY_FONT, fill=WHITE, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


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


def _new_stats() -> dict:
    return {"played": 0, "wins": 0, "dist": [0] * MAX_GUESSES, "streak": 0, "max": 0, "last": None}


# ------------------------------------------------------------------ UI
class GuessModal(ui.Modal, title="Your guess"):
    word = ui.TextInput(label="5-letter word", min_length=5, max_length=5, placeholder="crane")

    def __init__(self, view: "GameView"):
        super().__init__()
        self.game_view = view

    async def on_submit(self, interaction: Interaction):
        await self.game_view.submit(interaction, str(self.word.value))


class GameView(ui.View):
    def __init__(self, cog: "Wordle", guild_id: int, user_id: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog, self.guild_id, self.user_id = cog, guild_id, user_id
        self.day = today()

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Start your own game with `/wordle play`!", ephemeral=True)
            return False
        return True

    @ui.button(label="Guess", style=discord.ButtonStyle.success, emoji="⌨️")
    async def guess_button(self, interaction: Interaction, button: ui.Button):
        if today() != self.day:
            await interaction.response.edit_message(
                content="A new day, a new word! Run `/wordle play` again.", embed=None, attachments=[], view=None)
            self.stop()
            return
        await interaction.response.send_modal(GuessModal(self))

    async def submit(self, interaction: Interaction, raw: str):
        note, done = await self.cog.apply_guess(interaction, raw, self.day)
        embed, file = self.cog.build_message(self.guild_id, self.user_id, self.day, note)
        if done:
            self.stop()
        await interaction.response.edit_message(embed=embed, attachments=[file], view=None if done else self)


class Wordle(commands.Cog):
    wordle = app_commands.Group(name="wordle", description="Daily word puzzle with a server leaderboard", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = _load()
        self.lock = asyncio.Lock()
        try:
            self.answers = _read_words(ANSWERS_FILE)
            self.valid = set(_read_words(VALID_FILE)) | set(self.answers)
        except Exception as e:
            print(f"[wordle] could not load word lists: {e!r}")
            self.answers, self.valid = [], set()

    async def cog_load(self):
        self.recap_loop.start()

    async def cog_unload(self):
        self.recap_loop.cancel()

    # ------------------------------------------------------- daily recap
    def build_recap(self, g: dict, day: date) -> Optional[discord.Embed]:
        """Discord-Wordle-style recap of `day`: the server streak plus everyone's results, best first."""
        finished = {uid: v for uid, v in g["games"].get(day.isoformat(), {}).items() if v.get("done")}
        if not finished:
            return None
        groups: dict[int, list[str]] = {}
        for uid, v in finished.items():
            key = len(v["guesses"]) if v["won"] else MAX_GUESSES + 1
            groups.setdefault(key, []).append(f"<@{uid}>")
        lines = []
        for i, key in enumerate(sorted(groups)):
            label = f"{key}/{MAX_GUESSES}" if key <= MAX_GUESSES else f"X/{MAX_GUESSES}"
            crown = "👑 " if i == 0 and key <= MAX_GUESSES else ""
            lines.append(f"{crown}**{label}**: {' '.join(groups[key])}")
        s = self._server(g)
        if s["last"] == day.isoformat():
            streak = s["streak"]
        elif s["last"] == (day + timedelta(days=1)).isoformat():
            streak = max(1, s["streak"] - 1)  # someone already played today; show the count as of `day`
        else:
            streak = 1
        title = (f"🔥 This server is on a {streak}-day Wordle streak!" if streak >= 2
                 else "🟩 Yesterday's Wordle results")
        e = discord.Embed(title=title, color=discord.Color.orange() if streak >= 2 else discord.Color.green(),
                          description=f"Here are the results for **Wordle #{puzzle_number(day)}**:\n\n" + "\n".join(lines))
        e.set_footer(text=f"Wordle #{puzzle_number(day) + 1} is live! Play with /wordle play")
        return e

    @tasks.loop(minutes=5)
    async def recap_loop(self):
        yesterday = today() - timedelta(days=1)
        changed = False
        for gid, g in list(self.data.items()):
            g.setdefault("games", {})
            s = self._server(g)
            if s["recapped"] and s["recapped"] >= yesterday.isoformat():
                continue
            s["recapped"] = yesterday.isoformat()
            changed = True
            channel_id = s["channel"] or s["auto_channel"]
            embed = self.build_recap(g, yesterday) if s["recap"] else None
            if embed is None or channel_id is None:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                continue
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except Exception as e:
                print(f"[wordle] recap failed in guild {gid}: {e!r}")
        if changed:
            _save(self.data)

    @recap_loop.before_loop
    async def _before_recap(self):
        await self.bot.wait_until_ready()

    def _guild(self, guild_id: int) -> dict:
        g = self.data.setdefault(str(guild_id), {})
        g.setdefault("games", {})
        g.setdefault("stats", {})
        return g

    @staticmethod
    def _server(g: dict) -> dict:
        s = g.setdefault("server", {})
        for k, v in (("streak", 0), ("last", None), ("channel", None), ("auto_channel", None),
                     ("recap", True), ("recapped", None)):
            s.setdefault(k, v)
        return s

    def _bump_server_streak(self, g: dict, d: date) -> dict:
        """The server streak counts consecutive days on which at least one member finished the puzzle."""
        s = self._server(g)
        if s["last"] != d.isoformat():
            s["streak"] = s["streak"] + 1 if s["last"] == (d - timedelta(days=1)).isoformat() else 1
            s["last"] = d.isoformat()
        return s

    def server_streak(self, g: dict, d: date) -> int:
        """Current server streak; still alive if someone played today or yesterday."""
        s = self._server(g)
        return s["streak"] if s["last"] in (d.isoformat(), (d - timedelta(days=1)).isoformat()) else 0

    def _game(self, guild_id: int, user_id: int, d: date) -> dict:
        g = self._guild(guild_id)
        return g["games"].get(d.isoformat(), {}).get(str(user_id)) or {"guesses": [], "done": False, "won": False}

    def _prune(self, g: dict, d: date):
        cutoff = (d - timedelta(days=KEEP_DAYS)).isoformat()
        for k in [k for k in g["games"] if k < cutoff]:
            del g["games"][k]

    def _finish(self, g: dict, uid: str, d: date, won: bool, tries: int):
        st = g["stats"].setdefault(uid, _new_stats())
        st["played"] += 1
        yesterday = (d - timedelta(days=1)).isoformat()
        if won:
            st["wins"] += 1
            st["dist"][tries - 1] += 1
            st["streak"] = st["streak"] + 1 if st["last"] == yesterday else 1
            st["max"] = max(st["max"], st["streak"])
        else:
            st["streak"] = 0
        st["last"] = d.isoformat()

    def build_message(self, guild_id: int, user_id: int, d: date, note: str = "") -> tuple[discord.Embed, discord.File]:
        answer = answer_for(self.answers, guild_id, d)
        game = self._game(guild_id, user_id, d)
        guesses = game["guesses"]
        left = MAX_GUESSES - len(guesses)
        if game["won"]:
            desc, color = f"🎉 **Solved in {len(guesses)}/{MAX_GUESSES}!** Come back tomorrow for a new word.", discord.Color.green()
        elif game["done"]:
            desc, color = f"Out of guesses. The word was **{answer.upper()}**.", discord.Color.dark_grey()
        else:
            desc, color = f"Press **Guess** to type a word. {left} guess{'es' if left != 1 else ''} left.", discord.Color.blurple()
        if note:
            desc = note + "\n" + desc
        e = discord.Embed(title=f"🟩 JengBot Wordle #{puzzle_number(d)}", description=desc, color=color)
        e.set_image(url="attachment://wordle.png")
        return e, discord.File(render_image(guesses, answer), filename="wordle.png")

    async def apply_guess(self, interaction: Interaction, raw: str, d: date) -> tuple[str, bool]:
        """Validate and record a guess. Returns (note to show, game finished?)."""
        word = raw.strip().lower()
        if len(word) != 5 or not word.isalpha():
            return "❌ Letters only, exactly 5 of them.", False
        if word not in self.valid:
            return f"❌ **{word.upper()}** isn't in my word list.", False

        answer = answer_for(self.answers, interaction.guild_id, d)
        uid = str(interaction.user.id)
        public = None
        async with self.lock:
            g = self._guild(interaction.guild_id)
            self._prune(g, d)
            game = g["games"].setdefault(d.isoformat(), {}).setdefault(uid, {"guesses": [], "done": False, "won": False})
            if game["done"]:
                return "You already finished today's puzzle.", True
            if word in game["guesses"]:
                return f"You already tried **{word.upper()}**.", False
            game["guesses"].append(word)
            if word == answer:
                game["done"], game["won"] = True, True
            elif len(game["guesses"]) >= MAX_GUESSES:
                game["done"] = True
            if game["done"]:
                self._finish(g, uid, d, game["won"], len(game["guesses"]))
                srv = self._bump_server_streak(g, d)
                if interaction.channel is not None:
                    srv["auto_channel"] = interaction.channel.id
                result = f"{len(game['guesses'])}/{MAX_GUESSES}" if game["won"] else f"X/{MAX_GUESSES}"
                mine = g["stats"][uid]["streak"]
                extras = []
                if mine >= 2:
                    extras.append(f"🔥 {mine}-day win streak")
                if srv["streak"] >= 2:
                    extras.append(f"server streak: {srv['streak']} days")
                public = (f"{interaction.user.mention} finished **JengBot Wordle #{puzzle_number(d)}** {result}"
                          + (f"  ·  {' · '.join(extras)}" if extras else "") + "\n"
                          + emoji_grid(game["guesses"], answer))
            _save(self.data)
            done = game["done"]

        if public and interaction.channel is not None:
            try:
                await interaction.channel.send(public, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                pass
        return "", done

    # ------------------------------------------------------------ play
    @wordle.command(name="play", description="Play today's Wordle (same word for the whole server, 6 tries).")
    async def play(self, interaction: Interaction):
        debug_command("wordle play", interaction.user, interaction.guild)
        if not self.answers:
            await interaction.response.send_message("Wordle's word lists are missing on this bot.", ephemeral=True)
            return
        d = today()
        game = self._game(interaction.guild_id, interaction.user.id, d)
        embed, file = self.build_message(interaction.guild_id, interaction.user.id, d)
        view = None if game["done"] else GameView(self, interaction.guild_id, interaction.user.id)
        kwargs = {"view": view} if view else {}
        await interaction.response.send_message(embed=embed, file=file, ephemeral=True, **kwargs)

    # ------------------------------------------------------------ stats
    @wordle.command(name="stats", description="Wordle stats for you or someone else.")
    @app_commands.describe(user="Whose stats (default: you)")
    async def stats(self, interaction: Interaction, user: Optional[discord.Member] = None):
        debug_command("wordle stats", interaction.user, interaction.guild)
        user = user or interaction.user
        g = self._guild(interaction.guild_id)
        st = g["stats"].get(str(user.id))
        if not st or not st["played"]:
            await interaction.response.send_message(f"{user.display_name} hasn't finished a Wordle yet.", ephemeral=True)
            return
        # a streak is only alive if the last game was today or yesterday
        d = today()
        alive = st["last"] in (d.isoformat(), (d - timedelta(days=1)).isoformat())
        streak = st["streak"] if alive else 0
        pct = round(100 * st["wins"] / st["played"])
        top = max(st["dist"]) or 1
        dist = "\n".join(f"`{i + 1}` {'🟩' * max(1, round(8 * n / top)) if n else ''} {n}" for i, n in enumerate(st["dist"]))
        e = discord.Embed(title=f"🟩 Wordle stats · {user.display_name}", color=discord.Color.green())
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name="Played", value=str(st["played"]))
        e.add_field(name="Win %", value=f"{pct}%")
        e.add_field(name="Streak", value=f"{streak} (best {st['max']})")
        e.add_field(name="Guess distribution", value=dist, inline=False)
        await interaction.response.send_message(embed=e)

    # ------------------------------------------------------- leaderboard
    @wordle.command(name="leaderboard", description="Top Wordle players in this server.")
    async def leaderboard(self, interaction: Interaction):
        debug_command("wordle leaderboard", interaction.user, interaction.guild)
        g = self._guild(interaction.guild_id)
        d = today()
        rows = []
        for uid, st in g["stats"].items():
            if st["wins"] <= 0:
                continue
            avg = sum((i + 1) * n for i, n in enumerate(st["dist"])) / st["wins"]
            alive = st["last"] in (d.isoformat(), (d - timedelta(days=1)).isoformat())
            rows.append((uid, st["wins"], avg, st["streak"] if alive else 0))
        if not rows:
            await interaction.response.send_message("No one has solved a Wordle yet. Be the first with `/wordle play`!")
            return
        rows.sort(key=lambda r: (-r[1], r[2]))
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, wins, avg, streak) in enumerate(rows[:10]):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            fire = f" · 🔥{streak}" if streak >= 2 else ""
            lines.append(f"{prefix} <@{uid}> **{wins}** wins · avg {avg:.2f}{fire}")
        solved_today = sum(1 for v in g["games"].get(d.isoformat(), {}).values() if v["won"])
        e = discord.Embed(title="🟩 Wordle leaderboard", description="\n".join(lines), color=discord.Color.green())
        streak = self.server_streak(g, d)
        e.set_footer(text=f"Today's puzzle (#{puzzle_number(d)}): {solved_today} solved"
                          + (f" · 🔥 server streak: {streak} days" if streak else ""))
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    # ----------------------------------------------------------- channel
    @wordle.command(name="channel", description="Admin: choose where the daily Wordle streak recap is posted.")
    @app_commands.describe(channel="Channel for the daily recap (default: wherever people last played)",
                           off="Turn the daily recap off")
    async def channel(self, interaction: Interaction, channel: Optional[discord.TextChannel] = None, off: bool = False):
        debug_command("wordle channel", interaction.user, interaction.guild,
                      channel=getattr(channel, "name", None), off=off)
        member = interaction.user
        if not (isinstance(member, discord.Member)
                and (member.guild_permissions.manage_guild or is_bot_admin(member))):
            await interaction.response.send_message("Only server admins can change this.", ephemeral=True)
            return
        async with self.lock:
            s = self._server(self._guild(interaction.guild_id))
            if off:
                s["recap"] = False
                msg = "🔕 Daily Wordle recap turned off."
            elif channel is not None:
                s["recap"], s["channel"] = True, channel.id
                msg = f"📌 The daily Wordle recap will be posted in {channel.mention}."
            else:
                s["recap"], s["channel"] = True, None
                msg = "🔁 The daily Wordle recap will be posted wherever people last finished a game."
            _save(self.data)
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wordle(bot))
