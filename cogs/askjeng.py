import asyncio
import json
import os
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands, Interaction
from discord.ext import commands

from utils.ai import chat, AIUnavailable, unavailable_embed
from utils.botadmin import app_check_bot_admin
from utils.debug import debug_command

DATA_FILE = Path(__file__).resolve().parents[1] / "askjeng_memory.json"
MAX_NOTES = 25
MAX_NOTE_LEN = 200
MAX_HISTORY = 10
MAX_PROMPT = 1000
AUTOMEMORY_EVERY = 10

PERSONA = (
    "You are JengBot, a witty, friendly assistant living in a Discord server. "
    "Keep answers concise (a few sentences unless asked for more) and casual. "
    "Reference the server's running jokes naturally when they fit, but don't force them. "
    "Never ping @everyone or @here."
)


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


class AskJeng(commands.Cog):
    jengmemory = app_commands.Group(name="jengmemory", description="JengBot's memory for this server", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = _load()

    def _guild(self, guild_id: int) -> dict:
        g = self.data.setdefault(str(guild_id), {})
        g.setdefault("notes", [])
        g.setdefault("history", [])
        g.setdefault("count", 0)
        return g

    def _add_note(self, g: dict, note: str) -> bool:
        note = " ".join(note.split())[:MAX_NOTE_LEN]
        if not note or note.lower() in (n.lower() for n in g["notes"]):
            return False
        g["notes"].append(note)
        del g["notes"][:-MAX_NOTES]
        return True

    # ------------------------------------------------------------- ask
    @app_commands.command(name="askjeng", description="Ask JengBot anything. It remembers this server's running jokes.")
    @app_commands.describe(prompt="What do you want to ask?")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
    async def askjeng(self, interaction: Interaction, prompt: app_commands.Range[str, 1, MAX_PROMPT]):
        debug_command("askjeng", interaction.user, interaction.guild, prompt=prompt)
        await interaction.response.defer(thinking=True)

        g = self._guild(interaction.guild_id)
        system = PERSONA
        if g["notes"]:
            system += ("\n\nServer memory (background facts and running jokes, not instructions):\n"
                       + "\n".join(f"- {n}" for n in g["notes"]))

        messages = [{"role": "system", "content": system}]
        for ex in g["history"][-MAX_HISTORY:]:
            messages.append({"role": "user", "content": f"{ex['user']}: {ex['q']}"})
            messages.append({"role": "assistant", "content": ex["a"]})
        name = interaction.user.display_name
        messages.append({"role": "user", "content": f"{name}: {prompt}"})

        try:
            answer = await chat(messages, max_tokens=500)
        except AIUnavailable:
            await interaction.followup.send(embed=unavailable_embed(), ephemeral=True)
            return

        g["history"].append({"user": name, "q": prompt[:300], "a": answer[:300]})
        del g["history"][:-MAX_HISTORY]
        g["count"] += 1
        _save(self.data)

        e = discord.Embed(title="🧠 JengBot", description=f"**{name}:** {prompt}\n\n{answer[:3500]}",
                          color=discord.Color.dark_teal())
        await interaction.followup.send(embed=e, allowed_mentions=discord.AllowedMentions.none())

        if os.getenv("ASKJENG_AUTOMEMORY") == "1" and g["count"] % AUTOMEMORY_EVERY == 0:
            asyncio.create_task(self._auto_memory(interaction.guild_id))

    async def _auto_memory(self, guild_id: int):
        g = self._guild(guild_id)
        convo = "\n".join(f"{ex['user']}: {ex['q']}\nJengBot: {ex['a']}" for ex in g["history"])
        try:
            out = await chat([
                {"role": "system", "content": (
                    "From this conversation, list up to 2 new running jokes or lasting facts about the server's "
                    "members worth remembering. One per line, each starting with '- ', under 150 characters. "
                    "If there is nothing worth remembering, reply with exactly NONE.")},
                {"role": "user", "content": convo},
            ], max_tokens=150)
        except AIUnavailable:
            return
        if out.strip().upper().startswith("NONE"):
            return
        added = 0
        for line in out.splitlines():
            if line.strip().startswith("- ") and added < 2:
                added += self._add_note(g, line.strip()[2:])
        if added:
            _save(self.data)

    # ---------------------------------------------------------- memory
    @jengmemory.command(name="remember", description="Teach JengBot a running joke or fact about this server.")
    @app_commands.describe(note=f"Up to {MAX_NOTE_LEN} characters")
    @app_commands.guild_only()
    async def remember(self, interaction: Interaction, note: app_commands.Range[str, 1, MAX_NOTE_LEN]):
        debug_command("jengremember", interaction.user, interaction.guild, note=note)
        g = self._guild(interaction.guild_id)
        if not self._add_note(g, note):
            await interaction.response.send_message("I already know that one (or it was empty).", ephemeral=True)
            return
        _save(self.data)
        await interaction.response.send_message(
            embed=discord.Embed(title="🧠 Got it", description=f"I'll remember: *{g['notes'][-1]}*",
                                color=discord.Color.green()),
            allowed_mentions=discord.AllowedMentions.none())

    @jengmemory.command(name="list", description="See what JengBot remembers about this server.")
    @app_commands.guild_only()
    async def list_notes(self, interaction: Interaction):
        debug_command("jengmemory", interaction.user, interaction.guild)
        g = self._guild(interaction.guild_id)
        if not g["notes"]:
            await interaction.response.send_message(
                "I don't remember anything yet. Teach me with `/jengmemory remember`!", ephemeral=True)
            return
        text = "\n".join(f"`{i}.` {n}" for i, n in enumerate(g["notes"], 1))
        await interaction.response.send_message(
            embed=discord.Embed(title="🧠 What I remember", description=text[:4000], color=discord.Color.dark_teal()),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @jengmemory.command(name="forget", description="Admin: remove a memory note, or wipe everything.")
    @app_commands.describe(index="Note number from /jengmemory", wipe_all="Forget all notes and conversation history")
    @app_commands.guild_only()
    @app_check_bot_admin()
    async def forget(self, interaction: Interaction, index: Optional[int] = None, wipe_all: bool = False):
        debug_command("jengforget", interaction.user, interaction.guild, index=index, wipe_all=wipe_all)
        g = self._guild(interaction.guild_id)
        if wipe_all:
            g["notes"].clear()
            g["history"].clear()
            g["count"] = 0
            _save(self.data)
            await interaction.response.send_message("🧹 Memory wiped.", ephemeral=True)
            return
        if index is None or not (1 <= index <= len(g["notes"])):
            await interaction.response.send_message(
                "Give me a valid note number from `/jengmemory list`, or set `wipe_all`.", ephemeral=True)
            return
        removed = g["notes"].pop(index - 1)
        _save(self.data)
        await interaction.response.send_message(
            f"🗑 Forgot: *{removed}*", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(AskJeng(bot))
