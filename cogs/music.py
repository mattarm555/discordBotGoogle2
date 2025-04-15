import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import asyncio
import yt_dlp
import math
import os
import json

# --- Persistent Queue File ---
QUEUE_FILE = "saved_queues.json"

def save_queues(queues):
    if any(queues.values()):
        with open(QUEUE_FILE, "w") as f:
            json.dump(queues, f, indent=4)
    elif os.path.exists(QUEUE_FILE):
        os.remove(QUEUE_FILE)

def load_queues():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            return json.load(f)
    return {}

queues = load_queues()

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"

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
            title=f"\U0001F3B6 Current Queue (Page {self.page + 1}/{self.max_pages})",
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

    @app_commands.command(name="play", description="Plays a song or playlist from YouTube.")
    @app_commands.describe(url="YouTube URL or search term")
    async def play(self, interaction: Interaction, url: str):
        debug_command("play", interaction.user, interaction.guild, url=url)
        await interaction.response.defer(thinking=True)

        guild_id = str(interaction.guild.id)
        voice_client = interaction.guild.voice_client

        if guild_id not in queues:
            queues[guild_id] = []

        data = self.get_yt_info(url)
        entries = data['entries'] if 'entries' in data else [data]
        songs_added = []

        for info in entries:
            song = {
                'url': info['url'],
                'title': info['title'],
                'thumbnail': info.get('thumbnail', '')
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

        if queues[guild_id]:
            next_song = queues[guild_id].pop(0)
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
                temp = await interaction.channel.send(embed=embed)
                await asyncio.sleep(30)
                try:
                    await temp.delete()
                except discord.NotFound:
                    pass

            save_queues(queues)
        else:
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
            await interaction.channel.send(embed=embed)

    @app_commands.command(name="queue", description="Shows the current music queue.")
    async def queue(self, interaction: Interaction):
        await interaction.response.defer()
        debug_command("queue", interaction.user, interaction.guild)
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

async def setup(bot):
    await bot.add_cog(Music(bot))
