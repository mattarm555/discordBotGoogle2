import asyncio
import os
import time

import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ext import commands

from utils.debug import debug_command


class ServerStatus(commands.Cog):
    """/server status for the JengChat game server.

    Expected JSON from JENGCHAT_STATUS_URL:
      {"online": true, "name": "JengChat", "players": ["a","b"],
       "max_players": 20, "version": "0.3", "motd": "..."}
    Only "online" and "players" are required. Without a URL the bot falls back to a
    plain TCP connect to JENGCHAT_HOST:JENGCHAT_PORT (online/offline only).
    """

    server = app_commands.Group(name="server", description="Game server commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _query_http(self, url: str):
        start = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
        ping = int((time.monotonic() - start) * 1000)
        return data, ping

    async def _query_tcp(self, host: str, port: int):
        start = time.monotonic()
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
        ping = int((time.monotonic() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {"online": True}, ping

    @server.command(name="status", description="Check whether JengChat is up and who's online.")
    async def status(self, interaction: Interaction):
        debug_command("server status", interaction.user, interaction.guild)

        url = os.getenv("JENGCHAT_STATUS_URL")
        host = os.getenv("JENGCHAT_HOST")
        port = os.getenv("JENGCHAT_PORT")

        if not url and not (host and port):
            await interaction.response.send_message(embed=discord.Embed(
                title="⚙️ Not configured yet",
                description="The server status isn't set up yet. The owner needs to set `JENGCHAT_STATUS_URL` (or `JENGCHAT_HOST` and `JENGCHAT_PORT`) in the bot's `.env`.",
                color=discord.Color.light_grey()), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        data, ping = None, None
        if url:
            try:
                data, ping = await self._query_http(url)
            except Exception:
                data = None
        if data is None and host and port:
            try:
                data, ping = await self._query_tcp(host, int(port))
            except Exception:
                data = None

        if not data or not data.get("online", False):
            await interaction.followup.send(embed=discord.Embed(
                title="🔴 JengChat is offline",
                description="The server isn't responding right now.",
                color=discord.Color.red()))
            return

        name = data.get("name") or "JengChat"
        players = data.get("players")
        embed = discord.Embed(title=f"🟢 {name} is online", color=discord.Color.green())
        embed.add_field(name="Ping", value=f"{ping} ms", inline=True)

        if isinstance(players, list):
            max_p = data.get("max_players")
            count = f"{len(players)}/{max_p}" if max_p else str(len(players))
            embed.add_field(name="Players", value=count, inline=True)
            if players:
                shown = [str(p) for p in players[:25]]
                text = "\n".join(f"• {p}" for p in shown)
                if len(players) > 25:
                    text += f"\n…and {len(players) - 25} more"
                embed.add_field(name="Who's online", value=text[:1024], inline=False)
            else:
                embed.add_field(name="Who's online", value="Nobody right now.", inline=False)
        else:
            embed.set_footer(text="Player list unavailable (connection check only).")

        if data.get("version"):
            embed.add_field(name="Version", value=str(data["version"])[:100], inline=True)
        if data.get("motd"):
            embed.description = str(data["motd"])[:300]

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStatus(bot))
