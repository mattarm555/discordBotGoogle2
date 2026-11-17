import asyncio
import json
import logging
import os
import time
from pathlib import Path

import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ext import commands, tasks

from utils.botadmin import app_check_can_manage_bot_permissions
from utils.debug import debug_command

LIVE_FILE = Path(__file__).resolve().parents[1] / "jengchat_status_messages.json"
REFRESH_SECONDS = 30
log = logging.getLogger(__name__)


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
        self.live_messages: dict[int, tuple[int, int]] = {}
        self.live_lock = asyncio.Lock()
        try:
            records = json.loads(LIVE_FILE.read_text(encoding="utf-8"))
            for guild_id, (channel_id, message_id) in records.items():
                self.live_messages[int(guild_id)] = (int(channel_id), int(message_id))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError):
            log.exception("Could not load JengChat live messages")

    async def cog_load(self):
        self.refresh_live.start()

    async def cog_unload(self):
        self.refresh_live.cancel()

    def _save_live(self):
        temporary = LIVE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.live_messages), encoding="utf-8")
        temporary.replace(LIVE_FILE)

    async def _query_http(self, url: str):
        start = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=False) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
        if not isinstance(data, dict) or not isinstance(data.get("online"), bool):
            raise ValueError("Expected a JSON object with an online boolean")
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

    @staticmethod
    def _target():
        return (os.getenv("JENGCHAT_STATUS_URL"), os.getenv("JENGCHAT_HOST"), os.getenv("JENGCHAT_PORT"))

    async def _status_embed(self, *, live: bool = False) -> discord.Embed:
        url, host, port = self._target()
        embed = await self._build_status(url, host, port)
        if live:
            embed.timestamp = discord.utils.utcnow()
            notes = [embed.footer.text, f"Checked every {REFRESH_SECONDS} seconds · Last checked"]
            embed.set_footer(text=" · ".join(note for note in notes if note))
        return embed

    async def _build_status(self, url, host, port) -> discord.Embed:
        if not url and not (host and port):
            return discord.Embed(
                title="⚙️ Not configured yet",
                description="The server status isn't set up yet. The owner needs to set `JENGCHAT_STATUS_URL` (or `JENGCHAT_HOST` and `JENGCHAT_PORT`) in the bot's `.env`.",
                color=discord.Color.light_grey())

        data, ping = None, None
        if url:
            try:
                data, ping = await self._query_http(url)
            except (aiohttp.ClientError, TimeoutError, ValueError, RuntimeError):
                log.debug("JengChat HTTP check failed", exc_info=True)
        if data is None and host and port:
            try:
                data, ping = await self._query_tcp(host, int(port))
            except (OSError, TimeoutError, ValueError, OverflowError):
                log.debug("JengChat TCP check failed", exc_info=True)

        if data is None:
            return discord.Embed(
                title="🟠 JengChat is unreachable",
                description="The status check did not respond. The online member list is unavailable.",
                color=discord.Color.orange())
        if not data["online"]:
            return discord.Embed(
                title="🔴 JengChat is offline",
                description="The status service reports that JengChat is offline.",
                color=discord.Color.red())

        name = str(data.get("name") or "JengChat")[:100]
        players = data.get("players")
        embed = discord.Embed(title=f"🟢 {name} is online", color=discord.Color.green())
        embed.add_field(name="Ping", value=f"{ping} ms", inline=True)

        if isinstance(players, list):
            max_p = data.get("max_players")
            count = f"{len(players)}/{max_p}" if max_p else str(len(players))
            embed.add_field(name="Players", value=count, inline=True)
            if players:
                shown = [discord.utils.escape_markdown(" ".join(str(p).split())[:36])[:36] for p in players[:25]]
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

        return embed

    @server.command(name="status", description="Check whether JengChat is up and who's online.")
    async def status(self, interaction: Interaction):
        debug_command("server status", interaction.user, interaction.guild)
        url, host, port = self._target()
        await interaction.response.defer(thinking=True, ephemeral=not (url or (host and port)))
        await interaction.followup.send(embed=await self._status_embed(), allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="jengchat", description="Create or refresh this server's live JengChat status message.")
    @app_commands.guild_only()
    @app_check_can_manage_bot_permissions()
    async def jengchat(self, interaction: Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Run `/jengchat` in a server text channel.", ephemeral=True)
            return
        url, host, port = self._target()
        if not url and not (host and port):
            await interaction.response.send_message(embed=await self._status_embed(), ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self.live_lock:
            embed = await self._status_embed(live=True)
            existing = self.live_messages.get(channel.guild.id)
            if existing:
                channel_id, message_id = existing
                message = self._live_message(channel_id, message_id)
                jump_url = f"https://discord.com/channels/{channel.guild.id}/{channel_id}/{message_id}"
                try:
                    await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                except discord.NotFound:
                    pass  # Recreate a deleted message in the current channel.
                except discord.HTTPException:
                    await interaction.followup.send(f"I couldn't refresh the [existing status message]({jump_url}). Check my channel permissions.")
                    return
                else:
                    await interaction.followup.send(f"Refreshed the [live JengChat status]({jump_url}).")
                    return
            try:
                message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await interaction.followup.send("I couldn't post the status here. Check my Send Messages and Embed Links permissions.")
                return
            self.live_messages[channel.guild.id] = (channel.id, message.id)
            try:
                self._save_live()
            except OSError:
                log.exception("Could not save JengChat live messages")
                await interaction.followup.send(f"Posted the [live status]({message.jump_url}), but I couldn't save it for the next restart.")
                return
            await interaction.followup.send(f"Posted the [live JengChat status]({message.jump_url}).")

    def _live_message(self, channel_id: int, message_id: int) -> discord.PartialMessage:
        return self.bot.get_partial_messageable(channel_id).get_partial_message(message_id)

    @tasks.loop(seconds=REFRESH_SECONDS)
    async def refresh_live(self):
        async with self.live_lock:
            if not self.live_messages:
                return
            embed = await self._status_embed(live=True)
            removed = False
            for guild_id, ids in list(self.live_messages.items()):
                try:
                    await self._live_message(*ids).edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                except discord.NotFound:
                    del self.live_messages[guild_id]
                    removed = True
                except discord.HTTPException as error:
                    log.warning("Couldn't update JengChat status in guild %s (HTTP %s)", guild_id, error.status)
            if removed:
                try:
                    self._save_live()
                except OSError:
                    log.exception("Could not save JengChat live messages")

    @refresh_live.before_loop
    async def _wait_until_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStatus(bot))
