import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import asyncio
import yt_dlp
from utils.youtube_api import yt_api_search, yt_api_videos, yt_api_playlist_items
from urllib.parse import urlparse, parse_qs


def parse_iso8601_duration(iso: str) -> int:
    """Parse a simple ISO8601 duration (e.g. PT1H2M3S) into seconds. Returns 0 on failure."""
    if not iso or not isinstance(iso, str):
        return 0
    try:
        import re
        total = 0
        d = re.search(r"(\d+)D", iso)
        h = re.search(r"(\d+)H", iso)
        m = re.search(r"(\d+)M", iso)
        s = re.search(r"(\d+)S", iso)
        if d:
            total += int(d.group(1)) * 86400
        if h:
            total += int(h.group(1)) * 3600
        if m:
            total += int(m.group(1)) * 60
        if s:
            total += int(s.group(1))
        return total
    except Exception:
        return 0
import math
import json
import os
import random


# --- Persistent Queue File ---
QUEUE_FILE = "saved_queues.json"
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

# Maximum allowed duration for a single video (8 hours)
MAX_VIDEO_DURATION = 8 * 60 * 60

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
        self.force_stopped = {}  # guild_id: True if /leave was called
        global queues
        queues = {}
        save_queues(queues)
        print(f"{YELLOW}[INFO]{RESET} Cleared all queues at startup.")
        # DJ role configuration cache: guild_id -> role_id
        self.dj_roles = self._load_dj_config()

    DJ_CONFIG_FILE = "dj_config.json"

    # ---- DJ Role Persistence ----
    def _load_dj_config(self):
        if os.path.exists(self.DJ_CONFIG_FILE):
            try:
                with open(self.DJ_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _save_dj_config(self):
        try:
            with open(self.DJ_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.dj_roles, f, indent=4)
        except Exception:
            pass

    def _user_is_dj(self, interaction: Interaction) -> bool:
        """Return True if the user can control music.

        Rules:
          - If no DJ role set for guild -> everyone can use music commands (backwards compatible)
          - Guild owner OR user with manage_guild or manage_channels perms always allowed
          - If DJ role set -> user must have that role
        """
        guild = interaction.guild
        if guild is None:
            return True  # DM fallback (shouldn't happen for music control)
        # Elevated perms
        if interaction.user == guild.owner:
            return True
        perms = interaction.user.guild_permissions
        if perms.manage_guild or perms.manage_channels:
            return True
        role_id = self.dj_roles.get(str(guild.id))
        if not role_id:  # no role configured
            return True
        role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
        if role and role in interaction.user.roles:
            return True
        return False

    async def _enforce_dj(self, interaction: Interaction) -> bool:
        """Ensure the user has DJ permission. Returns True if allowed, False if blocked."""
        if self._user_is_dj(interaction):
            return True
        await interaction.response.send_message(embed=Embed(
            title="🎧 DJ Only",
            description="You need the configured DJ role (or Manage Server) to use this music command.",
            color=discord.Color.red()
        ), ephemeral=True)
        return False

    async def safe_connect(self, interaction):
        """Force a clean disconnect before joining to kill zombie sessions."""
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect(force=True)  # Kill zombie session

        try:
            return await interaction.user.voice.channel.connect()
        except Exception as e:
            print(f"{RED}❌ Voice connect failed: {e}{RESET}")
            raise

    def _is_youtube_mix(self, url: str) -> bool:
        """Return True if the URL appears to be a YouTube mix (auto-playlist) we want to reject.

        A mix typically has a 'list' parameter that starts with 'RD' or contains 'mix'.
        """
        try:
            from urllib.parse import urlparse, parse_qs
            p = urlparse(url)
            if 'youtube' not in p.netloc and 'youtu.be' not in p.netloc:
                return False
            qs = parse_qs(p.query)
            list_val = qs.get('list', [''])[0]
            if not list_val:
                return False
            lv = list_val.lower()
            if lv.startswith('rd') or 'mix' in lv:
                return True
            return False
        except Exception:
            return False

    def _is_watch_with_list(self, url: str) -> bool:
        """Detect YouTube watch URLs that include both a video id and a playlist param.

        Example to reject: https://www.youtube.com/watch?v=...&list=...
        """
        try:
            from urllib.parse import urlparse, parse_qs
            p = urlparse(url)
            if 'youtube' not in p.netloc and 'youtu.be' not in p.netloc:
                return False
            qs = parse_qs(p.query)
            if 'v' in qs and 'list' in qs:
                return True
            return False
        except Exception:
            return False


    def get_yt_info(self, query):
        is_playlist = "playlist" in query.lower() or "list=" in query.lower()
        print(f"[DEBUG] Using cookie file: {COOKIE_FILE}")

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist' if is_playlist else False,
            'cookiefile': COOKIE_FILE,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }

        # Only set default_search to ytsearch for non-SoundCloud queries. SoundCloud
        # search prefixes (scsearch/scsearch1) should be passed through directly.
        qlow = query.lower()
        if not (qlow.startswith('scsearch') or qlow.startswith('scsearch1')):
            ydl_opts['default_search'] = 'ytsearch'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)

    def get_stream_url(self, url: str, format_pref: str = None):
        # Prefer progressive (non-HLS) formats by default to avoid m3u8 segment URLs
        default_format = 'bestaudio[ext=mp4]/bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best'
        # Prefer MP3 for SoundCloud targets to avoid HLS/unsupported streams
        ydl_opts = {
            'format': format_pref or default_format,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'cookiefile': COOKIE_FILE,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }

        qlow = (url or '').lower()
        if 'soundcloud.com' in qlow or qlow.startswith('scsearch'):
            # prefer mp3 containers for SoundCloud to avoid HLS streams
            ydl_opts['format'] = 'bestaudio[ext=mp3]/bestaudio/best'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # Debug: show what URL/format we resolved to for easier troubleshooting
            try:
                fmt = info.get('format') or info.get('requested_formats')
            except Exception:
                fmt = None
            print(f"[DEBUG] Resolved stream for target={url} title={info.get('title')} format={fmt} url={info.get('url')}")
            return info['url']


    async def auto_disconnect(self, interaction: Interaction):
        await asyncio.sleep(60)  # Wait 60 seconds (or however long you want)
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


    def get_audio_source(self, url):
        ffmpeg_opts = {
            # Ensure ffmpeg seeks to the start to avoid HLS/segment URLs starting mid-stream
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss 0',
            'options': '-vn'
        }
        return discord.FFmpegPCMAudio(url, **ffmpeg_opts)

    @app_commands.command(name="play", description="Plays a song or playlist from YouTube or SoundCloud.")
    @app_commands.rename(url="search")
    @app_commands.describe(url="YouTube/SoundCloud URL or search term (accepts both links, searches only YouTube)")
    async def play(self, interaction: Interaction, url: str):
        if not self._user_is_dj(interaction):
            # Need to defer only if not responded; use private ephemeral
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot use /play.", color=discord.Color.red()), ephemeral=True)
            return
        debug_command("play", interaction.user, interaction.guild, url=url)
        await interaction.response.defer(thinking=True)

        guild_id = str(interaction.guild.id)
        self.force_stopped[guild_id] = False
        voice_client = interaction.guild.voice_client
        last_channels[guild_id] = interaction.channel

        if guild_id not in queues:
            queues[guild_id] = []

        # reject mixes and watch-with-list links up-front
        if url.startswith("http") and (self._is_youtube_mix(url) or self._is_watch_with_list(url)):
            if self._is_youtube_mix(url):
                embed = Embed(title="❌ Cannot Accept YouTube Mixes", description="Sorry — I can't accept YouTube Mix/Auto-playlist links. Please provide a single video or an explicit playlist URL.", color=discord.Color.red())
            else:
                embed = Embed(title="❌ Provide the Playlist Link Instead", description=("It looks like you provided a video link that includes a playlist parameter. Please provide the playlist URL instead, for example:\nhttps://www.youtube.com/playlist?list=PLFCHGavqRG-q_2ZhmgU2XB2--ZY6irT1c"), color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

        if url.startswith("sc:"):
            # SoundCloud search prefix
            query = f"scsearch1:{url[3:].strip()}"
        elif url.startswith("http"):
            # Direct link (YouTube, SoundCloud, etc.)
            query = url
        else:
            # Default to YouTube search for plain text
            query = f"ytsearch1:{url.strip()}"

        # run blocking extraction in a thread to avoid blocking the event loop
        # Prefer YouTube Data API for plain searches or YouTube URLs to avoid heavy yt_dlp metadata runs
        data = None
        try:
            if url.startswith('http'):
                # If YouTube URL, try to parse video id and fetch via API
                p = urlparse(url)
                host = p.netloc.lower()
                if 'youtube' in host or 'youtu.be' in host:
                    # get v= query or path short id
                    qs = parse_qs(p.query)
                    vid = None
                    if 'v' in qs:
                        vid = qs.get('v')[0]
                    else:
                        # youtu.be short link -> path component
                        path = p.path.strip('/')
                        if path:
                            vid = path
                    if vid:
                        api_res = yt_api_videos(vid)
                        items = api_res.get('items', [])
                        if items:
                            it = items[0]
                            snip = it.get('snippet', {})
                            # Try to parse ISO 8601 duration
                            dur = 0
                            try:
                                cd = it.get('contentDetails', {})
                                iso = cd.get('duration')
                                if iso:
                                    dur = parse_iso8601_duration(iso)
                            except Exception:
                                dur = 0
                            # construct a dict similar to yt_dlp output for downstream code
                            data = {'entries': [{'id': vid, 'webpage_url': url, 'title': snip.get('title'), 'thumbnail': snip.get('thumbnails', {}).get('high', {}).get('url') or snip.get('thumbnails', {}).get('default', {}).get('url'), 'duration': dur}]}
            else:
                # Plain text search: use YouTube Data API search (may cost quota)
                q = url.strip()
                api_res = yt_api_search(q, max_results=1)
                items = api_res.get('items', [])
                if items:
                    vid = items[0]['id']['videoId']
                    vres = yt_api_videos(vid)
                    vitems = vres.get('items', [])
                    if vitems:
                        it = vitems[0]
                        snip = it.get('snippet', {})
                        dur = 0
                        try:
                            cd = it.get('contentDetails', {})
                            iso = cd.get('duration')
                            if iso:
                                dur = parse_iso8601_duration(iso)
                        except Exception:
                            dur = 0
                        url_v = f"https://www.youtube.com/watch?v={vid}"
                        data = {'entries': [{'id': vid, 'webpage_url': url_v, 'title': snip.get('title'), 'thumbnail': snip.get('thumbnails', {}).get('high', {}).get('url') or snip.get('thumbnails', {}).get('default', {}).get('url'), 'duration': dur}]}
        except Exception:
            data = None

        # fallback to yt_dlp metadata extraction when API didn't return usable data
        if not data:
            try:
                data = await asyncio.to_thread(self.get_yt_info, query)
            except Exception as e:
                embed = Embed(title="⚠️ Extraction Failed", description=f"Failed to retrieve info: {e}", color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

        entries = data['entries'] if isinstance(data, dict) and 'entries' in data else [data]
        songs_added = []
        skipped = []
        is_sc_search = query.lower().startswith('scsearch')

        for info in entries:
            dur = info.get('duration', 0) or 0
            title = info.get('title', info.get('url', 'Unknown'))
            if dur and dur > MAX_VIDEO_DURATION:
                skipped.append(title)
                continue

            # Defer resolving the playable stream URL until playback time to avoid
            # performing many expensive webpage/js extractions up-front.
            # Ensure we always have a webpage_url even when extract_flat returns only an id
            vid_id = info.get('id')
            # Prefer the canonical webpage_url. If that's missing, prefer a raw http url
            # that's not an api.soundcloud.com link. If we only have a SoundCloud
            # internal id (soundcloud:tracks:...), try to construct a best-effort
            # permalink using uploader/title (not perfect but often works).
            webpage = info.get('webpage_url') or None
            raw_url = info.get('url')
            if not webpage and isinstance(raw_url, str):
                if raw_url.startswith('http') and 'api.soundcloud.com' not in raw_url:
                    webpage = raw_url

            if not webpage and isinstance(vid_id, str):
                if vid_id.startswith('soundcloud:tracks:'):
                    sc_id = vid_id.split(':')[-1]
                    uploader = info.get('uploader') or info.get('uploader_id') or info.get('creator') or 'unknown'
                    title = info.get('title') or sc_id
                    # minimal slugify for title
                    title_slug = ''.join(ch if ch.isalnum() or ch == '-' else '-' for ch in title.replace(' ', '-')).strip('-').lower()
                    webpage = f"https://soundcloud.com/{uploader}/{title_slug}"
                else:
                    webpage = (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None)
            song = {
                'id': vid_id,
                'webpage_url': webpage,
                'stream_url': None,
                # Keep the original search token so we can re-resolve if the
                # stored webpage_url is an API URL (api.soundcloud.com) which
                # yt-dlp can't extract directly.
                'search_query': query if is_sc_search else None,
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': dur
            }
            queues[guild_id].append(song)
            songs_added.append(song)

        # Notify about skipped too-long videos
        if len(entries) == 1 and skipped:
            embed = Embed(title="❌ Video Too Long", description="Sorry — I can't handle videos longer than 8 hours. Please provide a shorter video.", color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return
        if skipped:
            short_list = '\n'.join(f'- {t}' for t in skipped[:5])
            more = f"\n...and {len(skipped)-5} more" if len(skipped) > 5 else ''
            embed = Embed(title="⚠️ Some videos skipped", description=f"The following videos were longer than 8 hours and were skipped:\n{short_list}{more}", color=discord.Color.orange())
            await interaction.followup.send(embed=embed, ephemeral=True)

        save_queues(queues)

        was_playing = voice_client.is_playing() if voice_client else False
        if not voice_client:
            voice_client = await self.safe_connect(interaction)

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
        # ⛔ If force_stopped, do nothing
        if self.force_stopped.get(guild_id):
            return
            
        voice_client = interaction.guild.voice_client
        channel = last_channels.get(guild_id, interaction.channel)

        while queues[guild_id]:  # keep going until a song works or queue is empty
            next_song = queues[guild_id].pop(0)

            # 🟨 Fallback metadata if missing (e.g., from extract_flat)
            if not next_song.get("thumbnail") or not next_song.get("duration"):
                webpage = next_song.get('webpage_url') or next_song.get('url')
                if not webpage:
                    print(f"{RED}⚠️ No webpage URL for {next_song.get('title')}, skipping{RESET}")
                    await channel.send(embed=Embed(
                        title="⚠️ Metadata Error",
                        description=f"No URL available for **{next_song.get('title')}**, skipping...",
                        color=discord.Color.orange()
                    ))
                    continue
                try:
                    full_info = self.get_yt_info(webpage)
                    next_song["title"] = full_info.get("title", next_song["title"])
                    next_song["thumbnail"] = full_info.get("thumbnail", "")
                    next_song["duration"] = full_info.get("duration", 0)
                except Exception as e:
                    print(f"{RED}⚠️ Failed to fetch full info for {next_song.get('title')}: {e}{RESET}")
                    await channel.send(embed=Embed(
                        title="⚠️ Metadata Error",
                        description=f"Could not fetch full info for **{next_song.get('title')}**, skipping...",
                        color=discord.Color.orange()
                    ))
                    continue

            self.currently_playing[guild_id] = {
                "start_time": asyncio.get_event_loop().time(),
                "duration": next_song.get("duration", 0),
                "song": next_song
            }

            try:
                # Resolve stream URL on-demand (once) if it wasn't resolved at enqueue time.
                try:
                    # Always re-resolve the stream URL immediately before playback to avoid
                    # reusing an expired HLS/segment URL that might start mid-stream.
                    resolve_target = next_song.get('search_query') or next_song.get('webpage_url') or next_song.get('url')
                    if not resolve_target:
                        raise ValueError("No URL or search query to resolve stream")

                    # If this is a SoundCloud search token, run the search now and pick the first real page URL
                    if isinstance(resolve_target, str) and resolve_target.lower().startswith('scsearch'):
                        try:
                            search_info = await asyncio.to_thread(self.get_yt_info, resolve_target)
                            entries2 = search_info.get('entries') if isinstance(search_info, dict) and 'entries' in search_info else [search_info]
                            if entries2:
                                first = entries2[0]
                                candidate = first.get('webpage_url') or first.get('url')
                                if candidate:
                                    resolve_target = candidate
                                    next_song['webpage_url'] = candidate
                        except Exception as e:
                            print(f"{RED}⚠️ Failed to re-resolve SoundCloud search for {next_song.get('title')}: {e}{RESET}")

                    # blocking extraction in thread; prefer progressive formats to avoid HLS
                    stream = await asyncio.to_thread(self.get_stream_url, resolve_target)
                    # If yt-dlp still returned an HLS (.m3u8) playlist URL, retry once with explicit non-HLS preference
                    try:
                        if isinstance(stream, str) and stream.lower().endswith('.m3u8'):
                            print(f"[DEBUG] Got HLS stream (.m3u8) for {next_song.get('title')}, retrying with non-HLS preference")
                            retry_pref = 'bestaudio[ext=mp4]/bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best'
                            try:
                                stream_retry = await asyncio.to_thread(self.get_stream_url, resolve_target, retry_pref)
                                if isinstance(stream_retry, str) and not stream_retry.lower().endswith('.m3u8'):
                                    stream = stream_retry
                                    print(f"[DEBUG] Retry returned non-HLS stream for {next_song.get('title')}")
                                else:
                                    print(f"[DEBUG] Retry still returned HLS (or non-progressive) for {next_song.get('title')}, proceeding with original stream")
                            except Exception as e:
                                print(f"[DEBUG] Retry to avoid HLS failed: {e}")
                    except Exception:
                        # Defensive: if stream isn't a string or something unexpected, ignore and proceed
                        pass

                    # overwrite stream_url so we always use a fresh playable URL
                    next_song['stream_url'] = stream
                except Exception as e:
                    print(f"{RED}⚠️ Failed to resolve stream for {next_song.get('title')}: {e}{RESET}")
                    await channel.send(embed=Embed(
                        title="❌ Failed to Resolve Stream",
                        description=f"Could not resolve a playable stream for **{next_song.get('title')}**, skipping...",
                        color=discord.Color.red()
                    ))
                    continue

                stream_url = next_song.get('stream_url')
                source = self.get_audio_source(stream_url)
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
                return  # song successfully started

            except Exception as e:
                print(f"{RED}⚠️ Failed to play: {next_song['title']} — {e}{RESET}")
                await channel.send(embed=Embed(
                    title="❌ Failed to Play",
                    description=f"Sorry, **{next_song['title']}** could not be downloaded properly.",
                    color=discord.Color.red()
                ))
                continue  # try the next song in the queue

        # If we reached here, queue is empty or all songs failed
        self.currently_playing.pop(guild_id, None)
        await self.auto_disconnect(interaction)




    def _after_song(self, interaction: Interaction):
        # small delay to avoid racing with FFmpeg process shutdown when skipping
        async def wrapper():
            await asyncio.sleep(0.3)
            await self.start_next(interaction)

        asyncio.run_coroutine_threadsafe(wrapper(), self.bot.loop)

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
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot skip songs.", color=discord.Color.red()), ephemeral=True)
            return
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
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot pause music.", color=discord.Color.red()), ephemeral=True)
            return
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
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot resume music.", color=discord.Color.red()), ephemeral=True)
            return
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
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot disconnect the bot.", color=discord.Color.red()), ephemeral=True)
            return
        await interaction.response.defer()  # ✅ Defer response
        debug_command("leave", interaction.user, interaction.guild)

        guild_id = str(interaction.guild.id)
        last_channels[guild_id] = interaction.channel
        vc = interaction.guild.voice_client

        # ✅ Mark this server as force-stopped
        self.force_stopped[guild_id] = True

        # ✅ Clear queue and save
        queues[guild_id] = []
        save_queues(queues)

        if vc:
            await vc.disconnect()
            embed = Embed(
                title="Jeng has ran away.",
                description="Left the voice channel.",
                color=discord.Color.purple()
            )
            await interaction.followup.send(embed=embed)
        else:
            embed = Embed(
                title="Not Connected",
                description="I'm not in a voice channel.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)


    

    @app_commands.command(name="queueshuffle", description="Shuffle the current song queue.")
    async def queueshuffle(self, interaction: Interaction):
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot shuffle the queue.", color=discord.Color.red()), ephemeral=True)
            return
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
        debug_command("play_song", interaction.user, interaction.guild, url=url)
        guild_id = str(interaction.guild.id)
        self.force_stopped[guild_id] = False
        voice_client = interaction.guild.voice_client
        last_channels[guild_id] = interaction.channel

        if guild_id not in queues:
            queues[guild_id] = []

        # reject mixes and watch-with-list links up-front
        if url.startswith("http") and (self._is_youtube_mix(url) or self._is_watch_with_list(url)):
            if self._is_youtube_mix(url):
                embed = Embed(title="❌ Cannot Accept YouTube Mixes", description="Sorry — I can't accept YouTube Mix/Auto-playlist links. Please provide a single video or an explicit playlist URL.", color=discord.Color.red())
            else:
                embed = Embed(title="❌ Provide the Playlist Link Instead", description=("It looks like you provided a video link that includes a playlist parameter. Please provide the playlist URL instead, for example:\nhttps://www.youtube.com/playlist?list=PLFCHGavqRG-q_2ZhmgU2XB2--ZY6irT1c"), color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if url.startswith("sc:"):
            # SoundCloud search prefix
            query = f"scsearch1:{url[3:].strip()}"
        elif url.startswith("http"):
            # Direct link (YouTube, SoundCloud, etc.)
            query = url
        else:
            # Default to YouTube search for plain text
            query = f"ytsearch1:{url.strip()}"
        # run blocking extraction in a thread
        try:
            data = await asyncio.to_thread(self.get_yt_info, query)
        except Exception as e:
            await interaction.followup.send(embed=Embed(title="⚠️ Extraction Failed", description=f"Failed to retrieve info: {e}", color=discord.Color.red()), ephemeral=True)
            return

        entries = data["entries"] if isinstance(data, dict) and "entries" in data else [data]
        songs_added = []
        skipped = []
        is_sc_search = query.lower().startswith('scsearch')

        for info in entries:
            dur = info.get('duration', 0) or 0
            title = info.get('title', info.get('url', 'Unknown'))
            if dur and dur > MAX_VIDEO_DURATION:
                skipped.append(title)
                continue

            vid_id = info.get('id')
            webpage = info.get('webpage_url') or None
            raw_url = info.get('url')
            if not webpage and isinstance(raw_url, str):
                if raw_url.startswith('http') and 'api.soundcloud.com' not in raw_url:
                    webpage = raw_url

            if not webpage and isinstance(vid_id, str):
                if vid_id.startswith('soundcloud:tracks:'):
                    sc_id = vid_id.split(':')[-1]
                    uploader = info.get('uploader') or info.get('uploader_id') or info.get('creator') or 'unknown'
                    title = info.get('title') or sc_id
                    title_slug = ''.join(ch if ch.isalnum() or ch == '-' else '-' for ch in title.replace(' ', '-')).strip('-').lower()
                    webpage = f"https://soundcloud.com/{uploader}/{title_slug}"
                else:
                    webpage = (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None)
            song = {
                'id': vid_id,
                'webpage_url': webpage,
                'stream_url': None,
                'search_query': query if is_sc_search else None,
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': dur
            }
            queues[guild_id].append(song)
            songs_added.append(song)

        # notify user about skipped too-long videos
        if len(entries) == 1 and skipped:
            embed = Embed(title="❌ Video Too Long", description="Sorry — I can't handle videos longer than 8 hours. Please provide a shorter video.", color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        if skipped:
            short_list = '\n'.join(f'- {t}' for t in skipped[:5])
            more = f"\n...and {len(skipped)-5} more" if len(skipped) > 5 else ''
            embed = Embed(title="⚠️ Some videos skipped", description=f"The following videos were longer than 8 hours and were skipped:\n{short_list}{more}", color=discord.Color.orange())
            await interaction.followup.send(embed=embed, ephemeral=True)

        await asyncio.sleep(0.5)  # you can increase this to 0.5 if needed

        save_queues(queues)

        was_playing = voice_client.is_playing() if voice_client else False
        if not voice_client:
            voice_client = await self.safe_connect(interaction)

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

    @app_commands.command(name="removeplaylist", description="Delete a saved playlist.")
    async def remove_playlist(self, interaction: Interaction, name: str):
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot modify playlists.", color=discord.Color.red()), ephemeral=True)
            return
        debug_command("removeplaylist", interaction.user, interaction.guild, name=name)
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id in playlists and name in playlists[guild_id]:
            del playlists[guild_id][name]
            self.save_playlists(playlists)
            await interaction.response.send_message(embed=Embed(
                title="🗑️ Playlist Removed",
                description=f"`{name}` has been deleted.",
                color=discord.Color.red()
            ))
        else:
            await interaction.response.send_message(embed=Embed(
                title="⚠️ Not Found",
                description=f"No playlist found under `{name}`.",
                color=discord.Color.orange()
            ))



    @app_commands.command(name="playplaylist", description="Play a previously saved playlist.")
    async def play_playlist(self, interaction: Interaction, name: str):
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot start playlists.", color=discord.Color.red()), ephemeral=True)
            return
        debug_command("playplaylist", interaction.user, interaction.guild, name=name)
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id in playlists and name in playlists[guild_id]:
            link = playlists[guild_id][name]
            await interaction.response.send_message(embed=Embed(
                title="📼 Loading Playlist",
                description=f"Now playing: `{name}`",
                color=discord.Color.blue()
            ))
            await self.play_song(interaction, link)
        else:
            await interaction.response.send_message(embed=Embed(
                title="⚠️ Not Found",
                description=f"No playlist saved under `{name}`.",
                color=discord.Color.red()
            ))


    @app_commands.command(name="listplaylists", description="List saved playlists for this server.")
    async def list_playlists(self, interaction: Interaction):
        debug_command("listplaylists", interaction.user, interaction.guild)
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists().get(guild_id, {})
        if not playlists:
            await interaction.response.send_message(embed=Embed(
                title="📂 No Playlists",
                description="No playlists saved yet.",
                color=discord.Color.orange()
            ))
            return

        embed = Embed(title="📚 Saved Playlists", color=discord.Color.blurple())
        for name, link in playlists.items():
            embed.add_field(name=name, value=link, inline=False)
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="saveplaylist", description="Save a playlist link under a custom name.")
    async def save_playlist(self, interaction: Interaction, name: str, link: str):
        if not self._user_is_dj(interaction):
            await interaction.response.send_message(embed=Embed(title="🎧 DJ Only", description="A DJ role is set. You cannot save playlists.", color=discord.Color.red()), ephemeral=True)
            return
        debug_command("saveplaylist", interaction.user, interaction.guild, name=name, link=link)
        guild_id = str(interaction.guild.id)
        # Reject YouTube mixes
        if link.startswith('http') and self._is_youtube_mix(link):
            embed = Embed(title="❌ Cannot Save YouTube Mixes", description="Sorry — I can't save YouTube Mix/Auto-playlist links as playlists. Please provide an explicit playlist URL (https://www.youtube.com/playlist?list=PL...).", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Reject watch URLs that include a playlist parameter; ask for the canonical playlist link
        if link.startswith('http') and self._is_watch_with_list(link):
            embed = Embed(title="❌ Provide the Playlist Link Instead", description=("It looks like you provided a video link that includes a playlist parameter. "
                                 "Please provide the playlist URL instead, for example:\n"
                                 "https://www.youtube.com/playlist?list=PLFCHGavqRG-q_2ZhmgU2XB2--ZY6irT1c"), color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Require the link to be a playlist URL
        if not (link.startswith('http') and ("list=" in link.lower() or "playlist" in link.lower())):
            embed = Embed(title="❌ Not a Playlist URL", description="Please provide a playlist URL, for example: https://www.youtube.com/playlist?list=PL...", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        playlists = self.load_playlists()

        # Validate the playlist lightly (cap handled in get_yt_info)
        try:
            info = self.get_yt_info(link)
            if not info:
                await interaction.response.send_message(embed=Embed(
                    title="⚠️ Invalid Playlist",
                    description="Could not validate the provided playlist link.",
                    color=discord.Color.orange()
                ), ephemeral=True)
                return
        except Exception as e:
            await interaction.response.send_message(embed=Embed(
                title="⚠️ Playlist Validation Failed",
                description=f"Could not validate playlist: {e}",
                color=discord.Color.orange()
            ), ephemeral=True)
            return

        if guild_id not in playlists:
            playlists[guild_id] = {}
        playlists[guild_id][name] = link
        self.save_playlists(playlists)
        await interaction.response.send_message(embed=Embed(
            title="✅ Playlist Saved",
            description=f"Saved `{name}`.",
            color=discord.Color.green()
        ))

    # ---- DJ Role Commands ----
    @app_commands.command(name="setdj", description="Assign or update the DJ role for this server.")
    @app_commands.describe(role="Role that will have permission to control music features")
    async def set_dj(self, interaction: Interaction, role: discord.Role):
        # Require manage_guild to set
        if not interaction.user.guild_permissions.manage_guild and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(embed=Embed(
                title="❌ Missing Permission",
                description="You need Manage Server to set the DJ role.",
                color=discord.Color.red()
            ), ephemeral=True)
            return
        self.dj_roles[str(interaction.guild.id)] = role.id
        self._save_dj_config()
        await interaction.response.send_message(embed=Embed(
            title="🎧 DJ Role Set",
            description=f"DJ role is now {role.mention}. Users with this role (or Manage Server) can control music commands.",
            color=discord.Color.green()
        ))

    @app_commands.command(name="cleardj", description="Remove the configured DJ role (revert to everyone allowed).")
    async def clear_dj(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(embed=Embed(
                title="❌ Missing Permission",
                description="You need Manage Server to clear the DJ role.",
                color=discord.Color.red()
            ), ephemeral=True)
            return
        removed = self.dj_roles.pop(str(interaction.guild.id), None)
        self._save_dj_config()
        if removed:
            msg = "DJ role cleared. All users may use music commands now."
        else:
            msg = "No DJ role was set. Nothing changed."
        await interaction.response.send_message(embed=Embed(
            title="🎧 DJ Role Cleared",
            description=msg,
            color=discord.Color.orange()
        ))

    @app_commands.command(name="djinfo", description="Show the current DJ role configuration.")
    async def dj_info(self, interaction: Interaction):
        role_id = self.dj_roles.get(str(interaction.guild.id))
        if role_id:
            role = interaction.guild.get_role(int(role_id))
            if role:
                desc = f"Current DJ role: {role.mention}\nUsers with this role or Manage Server/Manage Channels can use music commands."
            else:
                desc = "A DJ role ID is stored, but the role no longer exists. Use /setdj to assign a new one or /cleardj to remove it."
        else:
            desc = "No DJ role is set. Everyone can use music commands. Use /setdj to restrict access."
        await interaction.response.send_message(embed=Embed(
            title="🎧 DJ Info",
            description=desc,
            color=discord.Color.blurple()
        ), ephemeral=True)




async def setup(bot):
    await bot.add_cog(Music(bot))



