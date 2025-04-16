import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import asyncio
import yt_dlp
import math
import os
import json
import random

QUEUE_FILE = "saved_queues.json"
PLAYLIST_FILE = "saved_playlists.json"

queues = {}  # guild_id: [song dicts]
last_channels = {}  # guild_id: last Interaction.channel

RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"

def save_queues(queues):
    if any(queues.values()):
        with open(QUEUE_FILE, "w") as f:
            json.dump(queues, f, indent=4)
    elif os.path.exists(QUEUE_FILE):
        os.remove(QUEUE_FILE)

def debug_command(command_name, user, guild, **kwargs):
    print(f"{RED}[COMMAND] /{command_name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{BLUE}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"{RED}  {key.capitalize()}: {value}{RESET}")

class QueueView(ui.View):
    def __init__(self, queue, per_page=5):
        super().__init__(timeout=60)
        self.queue = queue
        self.per_page = per_page
        self.page = 0
        self.max_pages = max(1, math.ceil(len(queue) / per_page))

    def format_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        embed = Embed(title=f"🎶 Current Queue (Page {self.page + 1}/{self.max_pages})", color=discord.Color.blue())
        songs_on_page = self.queue[start:end]
        for i, song in enumerate(songs_on_page, start=start + 1):
            embed.add_field(name=f"{i}. {song['title']}", value=" ", inline=False)
        if songs_on_page:
            embed.set_thumbnail(url=songs_on_page[0]['thumbnail'])
        return embed

    @ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def previous(self, interaction: Interaction, button: ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.format_embed(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def next(self, interaction: Interaction, button: ui.Button):
        if self.page < self.max_pages - 1:
            self.page += 1
            await interaction.response.edit_message(embed=self.format_embed(), view=self)
        else:
            await interaction.response.defer()

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.currently_playing = {}
        global queues
        queues = {}
        save_queues(queues)

    def get_yt_info(self, query):
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'default_search': 'ytsearch',
            'extract_flat': False
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)

    def get_audio_source(self, url):
        ffmpeg_opts = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }
        return discord.FFmpegPCMAudio(url, **ffmpeg_opts)

    def load_playlists(self):
        if os.path.exists(PLAYLIST_FILE):
            with open(PLAYLIST_FILE, "r") as f:
                return json.load(f)
        return {}

    def save_playlists(self, playlists):
        with open(PLAYLIST_FILE, "w") as f:
            json.dump(playlists, f, indent=4)

    @app_commands.command(name="play", description="Play a song or playlist from YouTube or SoundCloud.")
    @app_commands.rename(url="search")
    @app_commands.describe(url="YouTube/SoundCloud URL or search term (use 'sc:' for SoundCloud search)")
    async def play(self, interaction: Interaction, url: str):
        debug_command("play", interaction.user, interaction.guild, url=url)
        await interaction.response.defer(thinking=True)
        guild_id = str(interaction.guild.id)
        voice_client = interaction.guild.voice_client
        last_channels[guild_id] = interaction.channel

        if guild_id not in queues:
            queues[guild_id] = []

        if url.startswith("http"):
            query = url
        elif url.startswith("sc:"):
            query = f"scsearch:{url[3:].strip()}"
        else:
            query = f"ytsearch:{url.strip()}"

        data = self.get_yt_info(query)
        entries = data['entries'] if 'entries' in data else [data]
        songs_added = []

        for info in entries:
            song = {
                'url': info['url'],
                'title': info['title'],
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0)
            }
            queues[guild_id].append(song)
            songs_added.append(song)

        save_queues(queues)

        was_playing = voice_client.is_playing() if voice_client else False
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()

        if not was_playing and len(queues[guild_id]) == len(songs_added):
            msg = await interaction.edit_original_response(embed=Embed(title="Now Playing...", color=discord.Color.blurple()))
            await self.start_next(interaction, msg)
        else:
            desc = songs_added[0]['title'] if len(songs_added) == 1 else f"Added {len(songs_added)} songs to the queue."
            color = discord.Color.blue() if len(songs_added) == 1 else discord.Color.green()
            embed = Embed(title="Added to Queue", description=desc, color=color)
            embed.set_thumbnail(url=songs_added[0]['thumbnail'])
            await interaction.edit_original_response(embed=embed)

    async def start_next(self, interaction: Interaction, msg: discord.Message = None):
        guild_id = str(interaction.guild.id)
        voice_client = interaction.guild.voice_client
        channel = last_channels.get(guild_id, interaction.channel)

        if queues[guild_id]:
            next_song = queues[guild_id].pop(0)
            self.currently_playing[guild_id] = {
                "start_time": asyncio.get_event_loop().time(),
                "duration": next_song.get("duration", 0),
                "song": next_song
            }

            source = self.get_audio_source(next_song['url'])
            voice_client.play(source, after=lambda e: self._after_song(interaction))

            embed = Embed(title="Now Playing", description=next_song['title'], color=discord.Color.green())
            embed.set_thumbnail(url=next_song['thumbnail'])
            if msg:
                await msg.edit(embed=embed)
            else:
                await channel.send(embed=embed)
            save_queues(queues)
        else:
            self.currently_playing.pop(guild_id, None)
            await self.auto_disconnect(interaction)

    def _after_song(self, interaction: Interaction):
        asyncio.run_coroutine_threadsafe(self.start_next(interaction), self.bot.loop)

    async def auto_disconnect(self, interaction: Interaction):
        await asyncio.sleep(60)
        vc = interaction.guild.voice_client
        if vc and not vc.is_playing():
            await vc.disconnect()
            queues[str(interaction.guild.id)] = []
            save_queues(queues)
            embed = Embed(
                title="Jeng has ran away.",
                description="No music playing — disconnected automatically.",
                color=discord.Color.purple()
            )
            channel = last_channels.get(str(interaction.guild.id), interaction.channel)
            await channel.send(embed=embed)

    @app_commands.command(name="queueshuffle", description="Shuffle the current song queue.")
    async def queueshuffle(self, interaction: Interaction):
        await interaction.response.defer()
        guild_id = str(interaction.guild.id)
        if guild_id in queues and queues[guild_id]:
            random.shuffle(queues[guild_id])
            await interaction.followup.send(embed=Embed(title="🔀 Queue Shuffled", description="The queue has been shuffled.", color=discord.Color.green()))
        else:
            await interaction.followup.send(embed=Embed(title="📭 Empty Queue", description="There is nothing to shuffle.", color=discord.Color.red()))

    @app_commands.command(name="saveplaylist", description="Save a playlist link under a custom name.")
    async def save_playlist(self, interaction: Interaction, name: str, link: str):
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id not in playlists:
            playlists[guild_id] = {}
        playlists[guild_id][name] = link
        self.save_playlists(playlists)
        await interaction.response.send_message(embed=Embed(title="✅ Playlist Saved", description=f"Saved `{name}`.", color=discord.Color.green()))

    @app_commands.command(name="playplaylist", description="Play a previously saved playlist.")
    async def play_playlist(self, interaction: Interaction, name: str):
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id in playlists and name in playlists[guild_id]:
            link = playlists[guild_id][name]
            await interaction.response.send_message(embed=Embed(title='📼 Loading Playlist', description=f'Now playing: `{name}`', color=discord.Color.blue()))
            await self.play(interaction, link)
        else:
            await interaction.response.send_message(embed=Embed(title="⚠️ Not Found", description=f"No playlist saved under `{name}`.", color=discord.Color.red()))

    @app_commands.command(name="listplaylists", description="List saved playlists for this server.")
    async def list_playlists(self, interaction: Interaction):
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists().get(guild_id, {})
        if not playlists:
            await interaction.response.send_message(embed=Embed(title="📂 No Playlists", description="No playlists saved yet.", color=discord.Color.orange()))
            return
        embed = Embed(title="📚 Saved Playlists", color=discord.Color.blurple())
        for name, link in playlists.items():
            embed.add_field(name=name, value=link, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removeplaylist", description="Delete a saved playlist.")
    async def remove_playlist(self, interaction: Interaction, name: str):
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id in playlists and name in playlists[guild_id]:
            del playlists[guild_id][name]
            self.save_playlists(playlists)
            await interaction.response.send_message(embed=Embed(title="🗑️ Playlist Removed", description=f"`{name}` has been deleted.", color=discord.Color.red()))
        else:
            await interaction.response.send_message(embed=Embed(title="⚠️ Not Found", description=f"No playlist found under `{name}`.", color=discord.Color.orange()))

async def setup(bot):
    await bot.add_cog(Music(bot))
