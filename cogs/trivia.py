import asyncio
import html
import json
import os
import random
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ext import commands

from utils.botadmin import is_bot_admin
from utils.debug import debug_command

DATA_FILE = Path(__file__).resolve().parents[1] / "trivia_data.json"
OTDB = "https://opentdb.com"
ANSWER_SECONDS = 20
NIGHT_QUESTIONS = 20
NIGHT_SECONDS = 15
NIGHT_PAUSE = 4  # seconds between questions
NIGHT_IDLE_LIMIT = 3  # trivia night ends after this many questions in a row with no answers
LETTERS = ["A", "B", "C", "D"]

# Fallback if the category endpoint is unreachable (id -> name)
FALLBACK_CATEGORIES = {
    9: "General Knowledge", 10: "Books", 11: "Film", 12: "Music", 14: "Television",
    15: "Video Games", 17: "Science & Nature", 18: "Computers", 19: "Mathematics",
    20: "Mythology", 21: "Sports", 22: "Geography", 23: "History", 25: "Art",
    27: "Animals", 31: "Anime & Manga",
}


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


class TriviaError(Exception):
    pass


class QuestionView(discord.ui.View):
    def __init__(self, cog: "Trivia", guild_id: int, correct_index: int, options: list[str],
                 seconds: Optional[float] = ANSWER_SECONDS):
        # seconds=None: the caller ends the question itself by calling reveal() (trivia night).
        super().__init__(timeout=seconds)
        self.winners: list[int] = []
        self.losers: list[int] = []
        self._revealed = False
        self.cog = cog
        self.guild_id = guild_id
        self.correct_index = correct_index
        self.options = options
        self.answers: dict[int, int] = {}  # user_id -> chosen index
        self.message: Optional[discord.Message] = None
        for i in range(len(options)):
            b = discord.ui.Button(label=LETTERS[i], style=discord.ButtonStyle.primary)
            b.callback = self._make_cb(i)
            self.add_item(b)

    def _make_cb(self, index: int):
        async def cb(interaction: Interaction):
            if interaction.user.id in self.answers:
                await interaction.response.send_message("You already locked in an answer!", ephemeral=True)
                return
            self.answers[interaction.user.id] = index
            await interaction.response.send_message(f"🔒 Locked in **{LETTERS[index]}**. Results when time's up!", ephemeral=True)
        return cb

    async def on_timeout(self):
        await self.reveal()

    async def reveal(self):
        # Score everybody, then reveal. Safe to call more than once.
        if self._revealed:
            return
        self._revealed = True
        self.stop()
        winners, losers = [], []
        for uid, choice in self.answers.items():
            correct = choice == self.correct_index
            self.cog.record(self.guild_id, uid, correct)
            (winners if correct else losers).append(uid)
        self.winners, self.losers = winners, losers

        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                e = self.message.embeds[0] if self.message.embeds else discord.Embed(title="Trivia")
                e.color = discord.Color.green() if winners else discord.Color.red()
                e.clear_fields()
                e.add_field(
                    name="✅ Correct answer",
                    value=f"**{LETTERS[self.correct_index]}. {self.options[self.correct_index]}**", inline=False)
                if winners:
                    lines = []
                    for uid in winners:
                        streak = self.cog.get_user(self.guild_id, uid).get("streak", 0)
                        lines.append(f"<@{uid}> (🔥 {streak})")
                    e.add_field(name="Got it right", value="\n".join(lines)[:1024], inline=False)
                if losers:
                    e.add_field(name="Missed", value=" ".join(f"<@{u}>" for u in losers)[:1024], inline=False)
                if not self.answers:
                    e.add_field(name="Nobody answered", value="Better luck next time!", inline=False)
                e.set_footer(text="Time's up!")
                await self.message.edit(embed=e, view=self)
            except Exception:
                pass


class Trivia(commands.Cog):
    trivia = app_commands.Group(name="trivia", description="Trivia from Open Trivia DB", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = _load()
        self.categories: dict[int, str] = {}
        self._api_lock = asyncio.Lock()
        self._last_request = 0.0
        self._active: set[int] = set()  # channel ids with a live question or trivia night
        self._nights: dict[int, dict] = {}  # channel id -> {starter, stop, event}

    # ------------------------------------------------------------ data
    def get_user(self, guild_id: int, user_id: int) -> dict:
        return self.data.get(str(guild_id), {}).get("users", {}).get(str(user_id), {})

    def record(self, guild_id: int, user_id: int, correct: bool):
        g = self.data.setdefault(str(guild_id), {})
        u = g.setdefault("users", {}).setdefault(
            str(user_id), {"streak": 0, "best": 0, "correct": 0, "total": 0})
        u["total"] += 1
        if correct:
            u["correct"] += 1
            u["streak"] += 1
            u["best"] = max(u["best"], u["streak"])
        else:
            u["streak"] = 0
        _save(self.data)

    # ------------------------------------------------------------- API
    async def _get_json(self, session: aiohttp.ClientSession, path: str) -> dict:
        async with session.get(f"{OTDB}/{path}") as resp:
            if resp.status == 429:
                raise TriviaError("rate")
            return await resp.json(content_type=None)

    async def _ensure_categories(self):
        if self.categories:
            return
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
                data = await self._get_json(s, "api_category.php")
            self.categories = {c["id"]: c["name"].replace("Entertainment: ", "").replace("Science: ", "")
                               for c in data["trivia_categories"]}
        except Exception:
            self.categories = dict(FALLBACK_CATEGORIES)

    async def _fetch_question(self, guild_id: int, category: Optional[int], difficulty: Optional[str]) -> dict:
        return (await self._fetch_questions(guild_id, category, difficulty, 1))[0]

    async def _fetch_questions(self, guild_id: int, category: Optional[int], difficulty: Optional[str],
                               amount: int = 1) -> list[dict]:
        # OTDB allows 1 request per 5 seconds per IP, so serialize and space requests out.
        async with self._api_lock:
            wait = 5.2 - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                    g = self.data.setdefault(str(guild_id), {})
                    token = g.get("token")
                    if not token:
                        t = await self._get_json(s, "api_token.php?command=request")
                        token = g["token"] = t.get("token")
                        _save(self.data)
                        await asyncio.sleep(5.2)

                    for attempt in range(3):
                        q = f"api.php?amount={amount}&type=multiple&encode=url3986&token={token}"
                        if category:
                            q += f"&category={category}"
                        if difficulty:
                            q += f"&difficulty={difficulty}"
                        self._last_request = time.monotonic()
                        res = await self._get_json(s, q)
                        code = res.get("response_code")
                        if code == 0:
                            return res["results"]
                        if code == 4:  # token exhausted: reset it
                            await asyncio.sleep(5.2)
                            await self._get_json(s, f"api_token.php?command=reset&token={token}")
                            await asyncio.sleep(5.2)
                            continue
                        if code == 3:  # token invalid
                            g.pop("token", None)
                            _save(self.data)
                            raise TriviaError("token")
                        if code == 5:  # rate limited
                            await asyncio.sleep(5.2)
                            continue
                        raise TriviaError("few" if code == 1 else "none")  # 1: not enough questions, 2: bad parameter
                    raise TriviaError("rate")
            except TriviaError:
                raise
            except Exception as e:
                raise TriviaError("net") from e
            finally:
                self._last_request = time.monotonic()

    # ---------------------------------------------------------- commands
    async def _category_autocomplete(self, interaction: Interaction, current: str):
        await self._ensure_categories()
        cur = current.lower()
        return [app_commands.Choice(name=name, value=str(cid))
                for cid, name in self.categories.items() if cur in name.lower()][:25]

    @trivia.command(name="play", description="Ask a trivia question. Anyone can answer!")
    @app_commands.describe(category="Pick a category (optional)", difficulty="Pick a difficulty (optional)")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy", value="easy"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="Hard", value="hard")])
    @app_commands.autocomplete(category=_category_autocomplete)
    async def play(self, interaction: Interaction, category: Optional[str] = None,
                   difficulty: Optional[app_commands.Choice[str]] = None):
        debug_command("trivia play", interaction.user, interaction.guild, category=category,
                      difficulty=difficulty.value if difficulty else None)

        if interaction.channel_id in self._active:
            await interaction.response.send_message("A question is already live in this channel. Answer it first!", ephemeral=True)
            return

        cat_id = None
        if category:
            if not category.isdigit():
                await interaction.response.send_message("Pick a category from the list that appears as you type.", ephemeral=True)
                return
            cat_id = int(category)

        self._active.add(interaction.channel_id)
        try:
            await interaction.response.defer(thinking=True)
            try:
                q = await self._fetch_question(interaction.guild_id, cat_id, difficulty.value if difficulty else None)
            except TriviaError as e:
                msg = {
                    "none": "No questions are available for that category and difficulty. Try something else!",
                    "rate": "Trivia is being rate limited. Try again in a few seconds.",
                }.get(str(e), "Couldn't reach the trivia service. Try again in a moment.")
                await interaction.followup.send(msg, ephemeral=True)
                self._active.discard(interaction.channel_id)
                return

            dec = lambda s: html.unescape(unquote(s))
            question = dec(q["question"])
            correct = dec(q["correct_answer"])
            options = [dec(a) for a in q["incorrect_answers"]] + [correct]
            random.shuffle(options)
            correct_index = options.index(correct)

            e = discord.Embed(title="🧠 Trivia time!", description=f"**{question}**", color=discord.Color.blurple())
            e.add_field(name=f"{dec(q['category'])} · {q['difficulty'].title()}",
                        value="\n".join(f"**{LETTERS[i]}.** {o}" for i, o in enumerate(options)), inline=False)
            e.set_footer(text=f"You have {ANSWER_SECONDS} seconds. One answer each!")

            view = QuestionView(self, interaction.guild_id, correct_index, options)
            msg = await interaction.followup.send(embed=e, view=view, wait=True)
            view.message = msg
            asyncio.create_task(self._release_when_done(view, interaction.channel_id))
        except Exception:
            self._active.discard(interaction.channel_id)
            raise

    async def _release_when_done(self, view: QuestionView, channel_id: int):
        await view.wait()
        self._active.discard(channel_id)

    # -------------------------------------------------------- trivia night
    @trivia.command(name="night", description=f"Trivia night! {NIGHT_QUESTIONS} questions, {NIGHT_SECONDS} seconds each.")
    @app_commands.describe(
        difficulty="How hard the questions are",
        category="Stick to one category (default: a random mix)")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy", value="easy"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="Hard", value="hard")])
    @app_commands.autocomplete(category=_category_autocomplete)
    async def night(self, interaction: Interaction, difficulty: app_commands.Choice[str],
                    category: Optional[str] = None):
        debug_command("trivia night", interaction.user, interaction.guild, category=category,
                      difficulty=difficulty.value)

        channel = interaction.channel
        if channel is None or not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message("❌ I cannot send messages in this channel.", ephemeral=True)
            return
        if channel.id in self._active:
            await interaction.response.send_message(
                "Trivia is already running in this channel. Wait for it to finish (or use `/trivia stop`).",
                ephemeral=True)
            return

        cat_id = None
        if category:
            if not category.isdigit():
                await interaction.response.send_message(
                    "Pick a category from the list that appears as you type.", ephemeral=True)
                return
            cat_id = int(category)

        self._active.add(channel.id)
        started = False
        try:
            await interaction.response.defer(thinking=True)

            # Ask for a full set; if the category/difficulty does not have enough, settle for fewer.
            questions = None
            for amount in (NIGHT_QUESTIONS, 10, 5):
                try:
                    questions = await self._fetch_questions(interaction.guild_id, cat_id, difficulty.value, amount)
                    break
                except TriviaError as e:
                    if str(e) == "few":
                        continue
                    msg = {"none": "No questions are available for that category and difficulty.",
                           "rate": "Trivia is being rate limited. Try again in a few seconds."
                           }.get(str(e), "Could not reach the trivia service. Try again in a moment.")
                    await interaction.followup.send(msg, ephemeral=True)
                    return
            if not questions:
                await interaction.followup.send(
                    "That category does not have enough questions at that difficulty. "
                    "Try another difficulty or category!", ephemeral=True)
                return

            await self._ensure_categories()
            cat_label = self.categories.get(cat_id, "Random mix") if cat_id else "Random mix"
            intro = discord.Embed(
                title="🌙 Trivia Night!",
                description=(f"**{len(questions)} questions** · **{NIGHT_SECONDS} seconds** each\n"
                             f"Difficulty: **{difficulty.name}** · Category: **{cat_label}**\n\n"
                             f"Tap A-D to lock in an answer. One answer per question, so choose wisely.\n"
                             f"First question in 5 seconds..."),
                color=discord.Color.purple())
            if len(questions) < NIGHT_QUESTIONS:
                intro.set_footer(text=f"Only {len(questions)} questions were available for this combination.")
            await interaction.followup.send(embed=intro)

            started = True
            asyncio.create_task(self._run_night(channel, interaction.guild_id, questions,
                                                interaction.user.id, difficulty.name, cat_label))
        finally:
            if not started:
                self._active.discard(channel.id)

    async def _run_night(self, channel, guild_id: int, questions: list[dict], starter_id: int,
                         difficulty_label: str, cat_label: str):
        event = asyncio.Event()
        state = {"starter": starter_id, "stop": False, "event": event}
        self._nights[channel.id] = state
        scores: dict[int, int] = {}
        asked = 0
        idle = 0  # consecutive questions nobody answered
        idle_stopped = False
        dec = lambda x: html.unescape(unquote(x))

        async def pause(seconds: float):
            try:
                await asyncio.wait_for(event.wait(), seconds)
            except asyncio.TimeoutError:
                pass

        def standings(limit: int = 10) -> list[str]:
            medals = ["🥇", "🥈", "🥉"]
            rows = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
            out = []
            for i, (uid, pts) in enumerate(rows):
                prefix = medals[i] if i < 3 else f"`{i + 1}.`"
                out.append(f"{prefix} <@{uid}> **{pts}**")
            return out

        try:
            await pause(5)
            total = len(questions)
            for n, q in enumerate(questions, 1):
                if state["stop"]:
                    break
                asked = n
                question = dec(q["question"])
                correct = dec(q["correct_answer"])
                options = [dec(a) for a in q["incorrect_answers"]] + [correct]
                random.shuffle(options)
                correct_index = options.index(correct)

                ends = int(time.time()) + NIGHT_SECONDS + 1
                e = discord.Embed(title=f"🌙 Trivia Night · Question {n}/{total}",
                                  description=f"**{question}**", color=discord.Color.purple())
                e.add_field(name=f"{dec(q['category'])} · {q['difficulty'].title()}",
                            value="\n".join(f"**{LETTERS[i]}.** {o}" for i, o in enumerate(options)), inline=False)
                e.add_field(name="⏱ Time", value=f"Ends <t:{ends}:R>", inline=False)
                e.set_footer(text="One answer each!")

                view = QuestionView(self, guild_id, correct_index, options, seconds=None)
                view.message = await channel.send(embed=e, view=view)
                await pause(NIGHT_SECONDS)
                await view.reveal()

                for uid in view.answers:
                    scores.setdefault(uid, 0)
                for uid in view.winners:
                    scores[uid] += 1

                # Nobody touched the last few questions: assume everyone left and wrap up.
                idle = 0 if view.answers else idle + 1
                if idle >= NIGHT_IDLE_LIMIT and n < total:
                    idle_stopped = True
                    await channel.send(f"😴 No one answered the last {NIGHT_IDLE_LIMIT} questions, "
                                       "so I'm ending trivia night.")
                    break

                if state["stop"]:
                    break
                if n < total:
                    if n % 5 == 0 and scores:
                        await channel.send(embed=discord.Embed(
                            title=f"📊 After {n} questions", description="\n".join(standings(5)),
                            color=discord.Color.blurple()))
                    await pause(NIGHT_PAUSE)

            # Final results
            early = (state["stop"] or idle_stopped) and asked < len(questions)
            title = "🏁 Trivia Night results" + (" (ended early)" if early else "")
            if scores:
                desc = "\n".join(f"{line} / {asked}" for line in standings())
            else:
                desc = "Nobody answered a single question. 😴"
            res = discord.Embed(title=title, description=desc, color=discord.Color.gold())
            res.set_footer(text=f"{difficulty_label} · {cat_label} · /trivia leaderboard for all-time streaks")
            await channel.send(embed=res)
        except Exception as e:
            print(f"[trivia night] error: {e!r}")
            try:
                await channel.send("⚠️ Trivia night hit a problem and had to stop.")
            except Exception:
                pass
        finally:
            self._nights.pop(channel.id, None)
            self._active.discard(channel.id)

    @trivia.command(name="stop", description="End the trivia night running in this channel.")
    async def stop(self, interaction: Interaction):
        debug_command("trivia stop", interaction.user, interaction.guild)
        state = self._nights.get(interaction.channel_id)
        if not state:
            await interaction.response.send_message("There is no trivia night running in this channel.", ephemeral=True)
            return
        member = interaction.user
        allowed = (member.id == state["starter"]
                   or (isinstance(member, discord.Member)
                       and (member.guild_permissions.manage_guild or is_bot_admin(member))))
        if not allowed:
            await interaction.response.send_message(
                "Only the person who started it (or a server admin) can stop trivia night.", ephemeral=True)
            return
        state["stop"] = True
        state["event"].set()
        await interaction.response.send_message("🛑 Ending trivia night...")

    @trivia.command(name="leaderboard", description="Top trivia players in this server.")
    async def leaderboard(self, interaction: Interaction):
        debug_command("trivia leaderboard", interaction.user, interaction.guild)
        users = self.data.get(str(interaction.guild_id), {}).get("users", {})
        rows = sorted(users.items(), key=lambda kv: (kv[1]["best"], kv[1]["correct"]), reverse=True)[:10]
        if not rows:
            await interaction.response.send_message("Nobody has played yet. Try `/trivia play`!", ephemeral=True)
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, u) in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            pct = round(100 * u["correct"] / u["total"]) if u["total"] else 0
            lines.append(f"{prefix} <@{uid}> best streak **{u['best']}** · {u['correct']}/{u['total']} correct ({pct}%)")
        await interaction.response.send_message(embed=discord.Embed(
            title="🏆 Trivia leaderboard", description="\n".join(lines), color=discord.Color.gold()))

    @trivia.command(name="streak", description="Your trivia streak and stats.")
    @app_commands.describe(user="Check someone else (optional)")
    async def streak(self, interaction: Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        debug_command("trivia streak", interaction.user, interaction.guild, target=target.name)
        u = self.get_user(interaction.guild_id, target.id)
        if not u:
            await interaction.response.send_message(f"{target.display_name} hasn't played trivia yet.", ephemeral=True)
            return
        e = discord.Embed(title=f"🔥 {target.display_name}'s trivia stats", color=discord.Color.orange())
        e.add_field(name="Current streak", value=str(u["streak"]), inline=True)
        e.add_field(name="Best streak", value=str(u["best"]), inline=True)
        pct = round(100 * u["correct"] / u["total"]) if u["total"] else 0
        e.add_field(name="Correct", value=f"{u['correct']}/{u['total']} ({pct}%)", inline=True)
        await interaction.response.send_message(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Trivia(bot))
