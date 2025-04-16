import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import asyncio
import yt_dlp
import math
import json
import os
import random


# --- Persistent Queue File ---
QUEUE_FILE = "saved_queues.json"

queues = {}  # guild_id: [song dicts]
last_channels = {}  # guild_id: last Interaction.channel

# --- Color Codes ---
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
        embed = Embed(
            title=f"🎶 Current Queue (Page {self.page + 1}/{self.max_pages})",
            color=discord.Color.blue()
        )
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
        self.currently_playing = {}  # guild_id: {start_time, duration, song}
        global queues
        queues = {}
        save_queues(queues)
        print(f"{YELLOW}[INFO]{RESET} Cleared all queues at startup.")

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

    @app_commands.command(name="play", description="Plays a song or playlist from YouTube or SoundCloud.")
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
            if len(songs_added) == 1:
                embed = Embed(title='Added to Queue', description=songs_added[0]['title'], color=discord.Color.blue())
                embed.set_thumbnail(url=songs_added[0]['thumbnail'])
            else:
                embed = Embed(title='Playlist Queued', description=f"Added {len(songs_added)} songs.", color=discord.Color.green())
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
                await asyncio.sleep(30)
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass
            else:
                temp = await channel.send(embed=embed)
                await asyncio.sleep(30)
                try:
                    await temp.delete()
                except discord.NotFound:
                    pass

            save_queues(queues)
        else:
            self.currently_playing.pop(guild_id, None)
            await self.auto_disconnect(interaction)

    def _after_song(self, interaction: Interaction):
        asyncio.run_coroutine_threadsafe(self.start_next(interaction), self.bot.loop)

    @app_commands.command(name="np", description="Shows the currently playing song.")
    async def now_playing(self, interaction: Interaction):
        await interaction.response.defer()
        guild_id = str(interaction.guild.id)
        now = asyncio.get_event_loop().time()
        playing = self.currently_playing.get(guild_id)

        if not playing:
            embed = Embed(title="No Song Playing", description="Nothing is currently playing.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            return

        start = playing["start_time"]
        duration = playing["duration"]
        elapsed = int(now - start)
        total = duration or 1

        bar_len = 20
        filled_len = int(bar_len * elapsed / total)
        bar = "▬" * min(filled_len, bar_len - 1) + "🔘" + "▬" * max(0, bar_len - filled_len - 1)
        elapsed_fmt = f"{elapsed // 60}:{elapsed % 60:02}"
        total_fmt = f"{total // 60}:{total % 60:02}"

        embed = Embed(
            title="🎵 Now Playing",
            description=f"**{playing['song']['title']}**\n{bar}",
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=playing["song"]["thumbnail"])
        embed.set_footer(text=f"{elapsed_fmt} / {total_fmt}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="queue", description="Shows the current music queue.")
    async def queue(self, interaction: Interaction):
        await interaction.response.defer()
        debug_command("queue", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        song_queue = queues.get(str(interaction.guild.id), [])
        if not song_queue:
            embed = Embed(title="Queue Empty", description="No songs in queue.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            return
        view = QueueView(song_queue)
        embed = view.format_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: Interaction):
        await interaction.response.defer()
        debug_command("skip", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            embed = Embed(title="Skipped", description="Skipped to the next song.", color=discord.Color.orange())
            await interaction.followup.send(embed=embed)
            save_queues(queues)
        else:
            embed = Embed(title="No Song Playing", description="Nothing to skip.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="stop", description="Pauses the music.")
    async def stop(self, interaction: Interaction):
        await interaction.response.defer()
        debug_command("stop", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            embed = Embed(title="Paused", description="Music paused.", color=discord.Color.orange())
            await interaction.followup.send(embed=embed)
        else:
            embed = Embed(title="No Music Playing", description="Nothing to pause.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="start", description="Resumes paused music.")
    async def start(self, interaction: Interaction):
        await interaction.response.defer()
        debug_command("start", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            embed = Embed(title="Resumed", description="Music resumed.", color=discord.Color.green())
            await interaction.followup.send(embed=embed)
        else:
            embed = Embed(title="Not Paused", description="Nothing is paused.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="leave", description="Disconnects from voice and clears queue.")
    async def leave(self, interaction: Interaction):
        debug_command("leave", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            queues[str(interaction.guild.id)] = []
            save_queues(queues)
            embed = Embed(title="Jeng has ran away.", description="Left the voice channel.", color=discord.Color.purple())
            await interaction.response.send_message(embed=embed)
        else:
            embed = Embed(title="Not Connected", description="I'm not in a voice channel.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

    

    @app_commands.command(name="queueshuffle", description="Shuffle the current song queue.")
    async def queueshuffle(self, interaction: Interaction):
        await interaction.response.defer()
        guild_id = str(interaction.guild.id)
        if guild_id in queues and queues[guild_id]:
            
            random.shuffle(queues[guild_id])
            await interaction.followup.send(embed=Embed(title="🔀 Queue Shuffled", description="The queue has been shuffled.", color=discord.Color.green()))
        else:
            await interaction.followup.send(embed=Embed(title="📭 Empty Queue", description="There is nothing to shuffle.", color=discord.Color.red()))

    def load_playlists(self):
        if os.path.exists("saved_playlists.json"):
            with open("saved_playlists.json", "r") as f:
                return json.load(f)
        return {}

    def save_playlists(self, playlists):
        with open("saved_playlists.json", "w") as f:
            json.dump(playlists, f, indent=4)

    async def play_song(self, interaction: Interaction, url: str):
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
        entries = data["entries"] if "entries" in data else [data]
        songs_added = []

        for info in entries:
            song = {
                "url": info["url"],
                "title": info["title"],
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0)
            }
            queues[guild_id].append(song)
            songs_added.append(song)

        save_queues(queues)

        was_playing = voice_client.is_playing() if voice_client else False
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()

        if not was_playing and len(queues[guild_id]) == len(songs_added):
            msg = await interaction.followup.send(embed=Embed(title="Now Playing...", color=discord.Color.blurple()), wait=True)
            await self.start_next(interaction, msg)
        else:
            if len(songs_added) == 1:
                embed = Embed(title="Added to Queue", description=songs_added[0]["title"], color=discord.Color.blue())
                embed.set_thumbnail(url=songs_added[0]["thumbnail"])
            else:
                embed = Embed(title="Playlist Queued", description=f"Added {len(songs_added)} songs.", color=discord.Color.green())
            await interaction.followup.send(embed=embed)

    async def setup(bot):
    await bot.add_cog(Music(bot))



