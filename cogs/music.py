import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import asyncio
import yt_dlp
import math

queues = {}

RESET = "\033[0m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Debug logger
def debug_command(command_name, user, **kwargs):
    print(f"{RED}[COMMAND] /{command_name}{RESET} triggered by {YELLOW}{user.display_name}{RESET}")
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
        self.max_pages = math.ceil(len(queue) / per_page)

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

    @app_commands.command(name="play", description="Plays a song from a YouTube URL.")
    @app_commands.describe(url="YouTube URL")
    async def play(self, interaction: Interaction, url: str):
        debug_command("play", interaction.user, url=url)
        await interaction.response.defer()
        guild_id = interaction.guild.id

        if guild_id not in queues:
            queues[guild_id] = []

        ydl_opts = {'format': 'bestaudio', 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            song = {
                'url': info['url'],
                'title': info['title'],
                'thumbnail': info['thumbnail']
            }

        voice_client = interaction.guild.voice_client
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()

        if not voice_client.is_playing():
            voice_client.play(discord.FFmpegPCMAudio(song['url']), after=lambda e: self.play_next(interaction))
            embed = Embed(title='Now Playing', description=song['title'], color=discord.Color.green())
            embed.set_thumbnail(url=song['thumbnail'])
            await interaction.followup.send(embed=embed)
        else:
            queues[guild_id].append(song)
            embed = Embed(title='Added to Queue', description=song['title'], color=discord.Color.blue())
            embed.set_thumbnail(url=song['thumbnail'])
            await interaction.followup.send(embed=embed)

    def play_next(self, interaction: Interaction):
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        if queues[guild_id]:
            next_song = queues[guild_id].pop(0)
            voice_client.play(
                discord.FFmpegPCMAudio(next_song['url']),
                after=lambda e: self.play_next(interaction)
            )
            embed = Embed(title='Now Playing', description=next_song['title'], color=discord.Color.green())
            embed.set_thumbnail(url=next_song['thumbnail'])
            asyncio.run_coroutine_threadsafe(interaction.channel.send(embed=embed), self.bot.loop)
        else:
            # No more songs — auto disconnect in 60 seconds
            asyncio.run_coroutine_threadsafe(self.auto_disconnect(interaction), self.bot.loop)

    async def auto_disconnect(self, interaction: Interaction):
        await asyncio.sleep(60)
        vc = interaction.guild.voice_client
        if vc and not vc.is_playing():
            await vc.disconnect()
            queues[interaction.guild.id] = []
            embed = Embed(
                title="Jeng has ran away.",
                description="No music playing — disconnected automatically.",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

    @app_commands.command(name="queue", description="Shows the current music queue.")
    async def queue(self, interaction: Interaction):
        debug_command("queue", interaction.user)
        song_queue = queues.get(interaction.guild.id, [])
        if not song_queue:
            embed = Embed(title="Queue Empty", description="No songs in queue.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return
        view = QueueView(song_queue)
        embed = view.format_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: Interaction):
        debug_command("skip", interaction.user)
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()
            embed = Embed(title="Skipped", description="Skipped to the next song.", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
        else:
            embed = Embed(title="No Song Playing", description="Nothing to skip.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="Pauses the music.")
    async def stop(self, interaction: Interaction):
        debug_command("stop", interaction.user)
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            embed = Embed(title="Paused", description="Music paused.", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
        else:
            embed = Embed(title="No Music Playing", description="Nothing to pause.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="start", description="Resumes paused music.")
    async def start(self, interaction: Interaction):
        debug_command("start", interaction.user)
        if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
            interaction.guild.voice_client.resume()
            embed = Embed(title="Resumed", description="Music resumed.", color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
        else:
            embed = Embed(title="Not Paused", description="Nothing is paused.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leave", description="Disconnects from voice and clears queue.")
    async def leave(self, interaction: Interaction):
        debug_command("leave", interaction.user)
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            queues[interaction.guild.id] = []
            embed = Embed(title="Jeng has ran away.", description="Left the voice channel.", color=discord.Color.purple())
            await interaction.response.send_message(embed=embed)
        else:
            embed = Embed(title="Not Connected", description="I'm not in a voice channel.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Music(bot))
