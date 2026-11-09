import asyncio
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from typing import Awaitable, Callable, Optional
from urllib.parse import parse_qs, urlparse

import discord
import yt_dlp
from discord import Embed, Interaction, app_commands, ui
from discord.ext import commands

from utils.botadmin import is_bot_admin
from utils.youtube_api import yt_api_search, yt_api_videos


# --- Files / limits ---
QUEUE_FILE = "saved_queues.json"
PLAYLIST_FILE = "saved_playlists.json"
DJ_CONFIG_FILE = "dj_config.json"
MAX_VIDEO_DURATION = 8 * 60 * 60  # 8 hours
IDLE_DISCONNECT_SECONDS = 60
NOW_PLAYING_DELETE_AFTER = 30

# Optional: path to a Netscape-format cookies file exported from a (throwaway) logged-in
# YouTube account. Only needed if YouTube blocks the host IP even with a PO token provider.
YT_COOKIES = os.getenv("YT_COOKIES")

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -reconnect_on_network_error 1",
    "options": "-vn",
}

queues: dict[str, list[dict]] = {}       # guild_id -> [song dicts]
last_channels: dict[str, discord.abc.Messageable] = {}  # guild_id -> text channel for announcements

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"


def _log(msg: str):
    """print() that can never raise (e.g. emoji on a non-UTF-8 Windows console)."""
    try:
        print(msg, flush=True)
    except Exception:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass


class _StderrTail:
    """Write-only sink for FFmpeg's stderr that keeps the last few KB.

    It has no fileno(), so discord.py pipes stderr through a reader thread into write()."""

    def __init__(self, limit: int = 4096):
        self._buf = bytearray()
        self._limit = limit

    def write(self, data: bytes):
        self._buf.extend(data)
        if len(self._buf) > self._limit:
            del self._buf[:-self._limit]

    def fileno(self):
        raise OSError("no fileno")

    def text(self) -> str:
        return self._buf.decode(errors="replace").strip()


def parse_iso8601_duration(iso: str) -> int:
    """Parse a simple ISO8601 duration (e.g. PT1H2M3S) into seconds. Returns 0 on failure."""
    if not iso or not isinstance(iso, str):
        return 0
    total = 0
    for pattern, mult in ((r"(\d+)D", 86400), (r"(\d+)H", 3600), (r"(\d+)M", 60), (r"(\d+)S", 1)):
        m = re.search(pattern, iso)
        if m:
            total += int(m.group(1)) * mult
    return total


def save_queues(queues):
    if any(queues.values()):
        with open(QUEUE_FILE, "w") as f:
            json.dump(queues, f, indent=4)
    elif os.path.exists(QUEUE_FILE):
        os.remove(QUEUE_FILE)


def debug_command(command_name, user, guild, **kwargs):
    _log(f"{RED}[COMMAND] /{command_name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    for key, value in kwargs.items():
        _log(f"{RED}  {key.capitalize()}: {value}{RESET}")


def _is_soundcloud(target: str) -> bool:
    t = (target or "").lower()
    return "soundcloud.com" in t or t.startswith("scsearch")


def _ydl_opts(**extra) -> dict:
    """Shared yt-dlp options. Let yt-dlp pick its own clients/user agent (needed for
    PO tokens / JS challenge solving to work)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
    }
    if YT_COOKIES and os.path.exists(YT_COOKIES):
        opts["cookiefile"] = YT_COOKIES
    opts.update(extra)
    return opts


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
        if songs_on_page and songs_on_page[0].get('thumbnail'):
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
        self.force_stopped = {}      # guild_id: True if /leave was called (or we aborted)
        self.fail_counts = {}        # guild_id -> consecutive failure count
        self.play_last_used = {}     # user_id -> last monotonic timestamp
        self.locks: dict[str, asyncio.Lock] = {}  # guild_id -> lock around start_next
        self.user_stopped: dict[str, bool] = {}   # guild_id -> True when /skip or /leave ended the song
        self.last_playback: dict[str, dict] = {}  # guild_id -> diagnostics about the last song started
        self.PLAY_COOLDOWN = 10
        # Allow up to 2 failures; on the 3rd ("> 2"), abort and leave
        self.FAILURE_THRESHOLD = 2
        global queues
        queues = {}
        save_queues(queues)
        _log(f"{YELLOW}[INFO]{RESET} Cleared all queues at startup.")
        self.dj_roles = self._load_dj_config()

    def _lock(self, guild_id: str) -> asyncio.Lock:
        lock = self.locks.get(guild_id)
        if lock is None:
            lock = self.locks[guild_id] = asyncio.Lock()
        return lock

    # ---- Voice helpers ----
    def _looks_like_voice_e2ee_dave_4017(self, exc: Exception) -> bool:
        """Best-effort detection for Discord voice close code 4017 (DAVE/E2EE required)."""
        text = f"{exc}".lower()
        return any(k in text for k in ("4017", "dave", "e2ee", "end-to-end", "requires a client supporting"))

    async def _report_voice_connect_failure(self, interaction: Interaction, exc: Exception):
        if self._looks_like_voice_e2ee_dave_4017(exc):
            title = "❌ Can't Join Voice (4017)"
            desc = (
                "Discord rejected the voice connection because it requires E2EE/DAVE voice.\n\n"
                "The bot host needs discord.py 2.7+ with the `davey` package installed "
                "(`pip install -U \"discord.py[voice]\" davey`)."
            )
        else:
            title = "❌ Couldn't Join Voice"
            desc = (
                "I couldn't join your voice channel.\n\n"
                "Common causes: missing Connect/Speak permissions, a full channel, or a temporary voice gateway issue."
            )
        embed = Embed(title=title, description=desc, color=discord.Color.red())
        embed.add_field(name="Error", value=str(exc)[:900] or "(no details)", inline=False)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            channel = last_channels.get(str(interaction.guild.id), interaction.channel)
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    async def safe_connect(self, interaction: Interaction) -> discord.VoiceClient:
        """Connect to (or move to) the user's voice channel, reusing a healthy connection."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            raise RuntimeError("You need to be in a voice channel first.")
        target = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        if vc and vc.is_connected():
            if vc.channel != target:
                await vc.move_to(target)
            return vc
        if vc:
            # Zombie session (exists but not connected) -> kill it before reconnecting
            await vc.disconnect(force=True)

        try:
            vc = await target.connect(timeout=20, reconnect=True, self_deaf=True)
        except Exception as e:
            _log(f"{RED}❌ Voice connect failed: {e}{RESET}")
            raise

        # Some failures (e.g. 4017) disconnect right after the handshake without raising.
        await asyncio.sleep(1.25)
        current = interaction.guild.voice_client
        if current is None or not current.is_connected():
            raise RuntimeError("Voice handshake failed (disconnected immediately)")
        return current

    # ---- DJ Role Persistence ----
    def _load_dj_config(self):
        if os.path.exists(DJ_CONFIG_FILE):
            try:
                with open(DJ_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _save_dj_config(self):
        try:
            with open(DJ_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.dj_roles, f, indent=4)
        except Exception:
            pass

    def _user_is_dj(self, interaction: Interaction) -> bool:
        """Return True if the user can control music.

        Rules:
          - If no DJ role set for guild -> everyone can use music commands
          - Guild owner OR user with manage_guild or manage_channels perms always allowed
          - If DJ role set -> user must have that role
        """
        guild = interaction.guild
        if guild is None:
            return True
        if interaction.user == guild.owner:
            return True
        perms = interaction.user.guild_permissions
        if perms.manage_guild or perms.manage_channels:
            return True
        role_id = self.dj_roles.get(str(guild.id))
        if not role_id:
            return True
        role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
        return bool(role and role in interaction.user.roles)

    async def _deny_dj(self, interaction: Interaction, action: str):
        await interaction.response.send_message(embed=Embed(
            title="🎧 DJ Only",
            description=f"A DJ role is set. You cannot {action}.",
            color=discord.Color.red()
        ), ephemeral=True)

    # ---- /play cooldown helpers ----
    def _play_cooldown_remaining(self, user_id: int) -> float:
        now = asyncio.get_running_loop().time()
        remaining = (self.play_last_used.get(user_id, 0) + self.PLAY_COOLDOWN) - now
        return max(0.0, remaining)

    def _mark_play_used(self, user_id: int):
        self.play_last_used[user_id] = asyncio.get_running_loop().time()

    # ---- Failure guard ----
    async def _record_failure_and_maybe_abort(self, guild: discord.Guild, channel, reason: str) -> bool:
        """Increment failure counter; if above threshold, clear queue, notify, and leave.

        Returns True if we aborted (disconnected and cleared), False otherwise.
        """
        guild_id = str(guild.id)
        cnt = self.fail_counts.get(guild_id, 0) + 1
        self.fail_counts[guild_id] = cnt
        if cnt <= self.FAILURE_THRESHOLD:
            return False

        self.fail_counts[guild_id] = 0
        self.force_stopped[guild_id] = True
        queues[guild_id] = []
        save_queues(queues)

        embed = Embed(
            title="🚫 Too Many Playback Errors",
            description=(
                "I've hit errors on several songs in a row.\n"
                "To avoid spamming the channel, I'm clearing the queue and leaving the voice channel.\n"
                "Please try again later or with different links."
            ),
            color=discord.Color.red()
        )
        if reason:
            embed.add_field(name="Last error", value=reason[:1000], inline=False)
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
        vc = guild.voice_client
        if vc:
            try:
                await vc.disconnect()
            except Exception:
                pass
        return True

    # ---- URL checks ----
    def _is_youtube_mix(self, url: str) -> bool:
        """True if the URL is a YouTube Mix (auto-playlist): list= starting with RD or containing 'mix'."""
        try:
            p = urlparse(url)
            if 'youtube' not in p.netloc and 'youtu.be' not in p.netloc:
                return False
            lv = parse_qs(p.query).get('list', [''])[0].lower()
            return bool(lv) and (lv.startswith('rd') or 'mix' in lv)
        except Exception:
            return False

    def _is_watch_with_list(self, url: str) -> bool:
        """Detect YouTube watch URLs that include both a video id and a playlist param."""
        try:
            p = urlparse(url)
            if 'youtube' not in p.netloc and 'youtu.be' not in p.netloc:
                return False
            qs = parse_qs(p.query)
            return 'v' in qs and 'list' in qs
        except Exception:
            return False

    def _url_rejection_embed(self, url: str) -> Optional[Embed]:
        if not url.startswith("http"):
            return None
        if self._is_youtube_mix(url):
            return Embed(title="❌ Cannot Accept YouTube Mixes", description="Sorry — I can't accept YouTube Mix/Auto-playlist links. Please provide a single video or an explicit playlist URL.", color=discord.Color.red())
        if self._is_watch_with_list(url):
            return Embed(title="❌ Provide the Playlist Link Instead", description=("It looks like you provided a video link that includes a playlist parameter. Please provide the playlist URL instead, for example:\nhttps://www.youtube.com/playlist?list=PLFCHGavqRG-q_2ZhmgU2XB2--ZY6irT1c"), color=discord.Color.red())
        return None

    # ---- yt-dlp (blocking; always call via asyncio.to_thread) ----
    def get_yt_info(self, query: str):
        is_playlist = "playlist" in query.lower() or "list=" in query.lower()
        extra = {
            'format': 'bestaudio/best',
            'extract_flat': 'in_playlist' if is_playlist else False,
        }
        if not query.lower().startswith('scsearch'):
            extra['default_search'] = 'ytsearch'
        with yt_dlp.YoutubeDL(_ydl_opts(**extra)) as ydl:
            return ydl.extract_info(query, download=False)

    def get_stream_url(self, url: str) -> str:
        if url.lower().startswith('scsearch'):
            return self._soundcloud_search_stream(url.split(':', 1)[1])
        fmt = 'bestaudio[ext=mp3]/bestaudio/best' if _is_soundcloud(url) else 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best'
        with yt_dlp.YoutubeDL(_ydl_opts(format=fmt, noplaylist=True)) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or not isinstance(info, dict):
            raise RuntimeError("yt-dlp returned no info")
        if info.get('entries'):
            info = info['entries'][0]
        resolved = info.get('url')
        if not resolved:
            raise RuntimeError("yt-dlp info missing stream url")
        _log(f"[DEBUG] Resolved stream for {url} -> {info.get('title')} ({info.get('format')})")
        return resolved

    def _soundcloud_search_stream(self, terms: str, candidates: int = 5) -> str:
        """Search SoundCloud and return the first result that actually resolves
        (many top results are DRM-protected Go+ tracks that can't be played)."""
        with yt_dlp.YoutubeDL(_ydl_opts(extract_flat='in_playlist')) as ydl:
            results = ydl.extract_info(f"scsearch{candidates}:{terms}", download=False) or {}
        last_err: Exception = RuntimeError("No SoundCloud results")
        for entry in results.get('entries') or []:
            page = entry.get('webpage_url') or entry.get('url')
            if not page:
                continue
            try:
                return self.get_stream_url(page)
            except Exception as e:
                last_err = e
        raise last_err

    async def _resolve_stream(self, song: dict) -> tuple[str, Optional[str]]:
        """Resolve a fresh playable URL for a song. Falls back to a SoundCloud search by
        title when YouTube fails. Returns (stream_url, fallback_label_or_None)."""
        target = song.get('search_query') or song.get('webpage_url') or song.get('url')
        if not target:
            raise RuntimeError("No URL or search query to resolve stream")
        try:
            return await asyncio.to_thread(self.get_stream_url, target), None
        except Exception as primary_err:
            if _is_soundcloud(target) or not song.get('title'):
                raise
            _log(f"{YELLOW}⚠️ YouTube resolve failed for {song.get('title')}: {primary_err} — trying SoundCloud{RESET}")
            try:
                return await asyncio.to_thread(self.get_stream_url, f"scsearch1:{song['title']}"), "SoundCloud"
            except Exception as sc_err:
                raise RuntimeError(f"YouTube: {primary_err} | SoundCloud fallback: {sc_err}") from primary_err

    # ---- Metadata lookup ----
    def _api_entry(self, vid: str, page_url: str) -> Optional[dict]:
        """Build a yt-dlp-like entry from the YouTube Data API (blocking)."""
        items = yt_api_videos(vid).get('items', [])
        if not items:
            return None
        it = items[0]
        snip = it.get('snippet', {})
        thumbs = snip.get('thumbnails', {})
        return {
            'id': vid,
            'webpage_url': page_url,
            'title': snip.get('title'),
            'thumbnail': thumbs.get('high', {}).get('url') or thumbs.get('default', {}).get('url'),
            'duration': parse_iso8601_duration(it.get('contentDetails', {}).get('duration')),
        }

    def _lookup_via_api(self, url: str) -> Optional[dict]:
        """Try the YouTube Data API for single videos and plain searches (blocking).
        Cheaper and less likely to be rate-limited than a yt-dlp metadata run."""
        if url.startswith('http'):
            p = urlparse(url)
            host = p.netloc.lower()
            if 'youtube' not in host and 'youtu.be' not in host:
                return None
            if 'list' in parse_qs(p.query) or '/playlist' in p.path:
                return None  # playlists go through yt-dlp
            vid = parse_qs(p.query).get('v', [None])[0] or p.path.strip('/') or None
            if not vid:
                return None
            entry = self._api_entry(vid, url)
        else:
            items = yt_api_search(url.strip(), max_results=1).get('items', [])
            if not items:
                return None
            vid = items[0]['id']['videoId']
            entry = self._api_entry(vid, f"https://www.youtube.com/watch?v={vid}")
        return {'entries': [entry]} if entry else None

    def _entry_to_song(self, info: dict, query: str) -> dict:
        vid_id = info.get('id')
        webpage = info.get('webpage_url') or None
        raw_url = info.get('url')
        if not webpage and isinstance(raw_url, str) and raw_url.startswith('http') and 'api.soundcloud.com' not in raw_url:
            webpage = raw_url
        if not webpage and isinstance(vid_id, str) and not vid_id.startswith('soundcloud:'):
            webpage = f"https://www.youtube.com/watch?v={vid_id}"
        return {
            'id': vid_id,
            'webpage_url': webpage,
            # For SoundCloud searches keep the search token so we can re-resolve at play time.
            'search_query': query if query.lower().startswith('scsearch') else None,
            'title': info.get('title') or 'Unknown',
            'thumbnail': info.get('thumbnail') or '',
            'duration': info.get('duration') or 0,
        }

    # ---- Enqueue (shared by /play and /playplaylist) ----
    async def _enqueue(self, interaction: Interaction, url: str,
                       respond: Callable[..., Awaitable[Optional[discord.Message]]]):
        """Look up `url`, add the results to the queue, join voice and start playback if idle.

        `respond(embed, ephemeral=False)` sends/edits the user-facing reply and returns the message.
        """
        guild = interaction.guild
        guild_id = str(guild.id)
        last_channels[guild_id] = interaction.channel
        queues.setdefault(guild_id, [])

        rejection = self._url_rejection_embed(url)
        if rejection:
            await respond(rejection, ephemeral=True)
            return

        if url.startswith("sc:"):
            query = f"scsearch1:{url[3:].strip()}"
        elif url.startswith("http"):
            query = url
        else:
            query = f"ytsearch1:{url.strip()}"

        data = None
        if not query.startswith("scsearch"):
            try:
                data = await asyncio.to_thread(self._lookup_via_api, url)
            except Exception as e:
                _log(f"[DEBUG] YouTube API lookup failed, falling back to yt-dlp: {e}")
        if not data:
            try:
                data = await asyncio.to_thread(self.get_yt_info, query)
            except Exception as e:
                await respond(Embed(title="⚠️ Extraction Failed", description=f"Failed to retrieve info: {str(e)[:1500]}", color=discord.Color.red()))
                return
        if not data:
            await respond(Embed(title="🔍 Nothing Found", description="No results for that search.", color=discord.Color.orange()))
            return

        entries = [e for e in (data['entries'] if isinstance(data, dict) and 'entries' in data else [data]) if e]
        songs_added, skipped = [], []
        for info in entries:
            dur = info.get('duration') or 0
            if dur > MAX_VIDEO_DURATION:
                skipped.append(info.get('title') or 'Unknown')
                continue
            song = self._entry_to_song(info, query)
            queues[guild_id].append(song)
            songs_added.append(song)

        if not songs_added:
            if skipped:
                await respond(Embed(title="❌ Video Too Long", description="Sorry — I can't handle videos longer than 8 hours. Please provide a shorter video.", color=discord.Color.red()))
            else:
                await respond(Embed(title="🔍 Nothing Found", description="No playable results for that search.", color=discord.Color.orange()))
            return
        if skipped:
            short_list = '\n'.join(f'- {t}' for t in skipped[:5])
            more = f"\n...and {len(skipped) - 5} more" if len(skipped) > 5 else ''
            try:
                await interaction.followup.send(embed=Embed(title="⚠️ Some videos skipped", description=f"These were longer than 8 hours and were skipped:\n{short_list}{more}", color=discord.Color.orange()), ephemeral=True)
            except Exception:
                pass
        save_queues(queues)

        try:
            vc = await self.safe_connect(interaction)
        except Exception as e:
            # Undo the enqueue so a later /play doesn't replay stale songs
            for s in songs_added:
                if s in queues[guild_id]:
                    queues[guild_id].remove(s)
            save_queues(queues)
            await self._report_voice_connect_failure(interaction, e)
            return

        self.force_stopped[guild_id] = False
        if vc.is_playing() or vc.is_paused():
            if len(songs_added) == 1:
                embed = Embed(title='Added to Queue', description=songs_added[0]['title'], color=discord.Color.blue())
                if songs_added[0]['thumbnail']:
                    embed.set_thumbnail(url=songs_added[0]['thumbnail'])
            else:
                embed = Embed(title='Playlist Queued', description=f"Added {len(songs_added)} songs.", color=discord.Color.green())
            await respond(embed)
            return

        if len(songs_added) > 1:
            await respond(Embed(title='Playlist Queued', description=f"Added {len(songs_added)} songs. Starting playback…", color=discord.Color.green()))
            await self.start_next(guild)
        else:
            msg = await respond(Embed(title="Now Playing...", color=discord.Color.blurple()))
            await self.start_next(guild, msg)

    # ---- Playback loop ----
    async def start_next(self, guild: discord.Guild, msg: Optional[discord.Message] = None):
        """Pop songs off the queue until one starts playing (or the queue runs out)."""
        guild_id = str(guild.id)
        async with self._lock(guild_id):
            if self.force_stopped.get(guild_id):
                return
            channel = last_channels.get(guild_id)
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                self.force_stopped[guild_id] = True
                return
            if vc.is_playing() or vc.is_paused():
                return  # someone else already started a song

            while queues.get(guild_id):
                song = queues[guild_id].pop(0)
                save_queues(queues)

                try:
                    stream_url, via = await self._resolve_stream(song)
                except Exception as e:
                    _log(f"{RED}⚠️ Failed to resolve stream for {song.get('title')}: {e}{RESET}")
                    extra = ""
                    if "403" in str(e) or "sign in" in str(e).lower() or "bot" in str(e).lower():
                        extra = "\n\nYouTube blocked the request from this server. See the hosting notes in `deploy/README.md`."
                    if channel:
                        await channel.send(embed=Embed(
                            title="❌ Failed to Resolve Stream",
                            description=f"Could not get a playable stream for **{song.get('title')}**, skipping...{extra}",
                            color=discord.Color.red()
                        ))
                    if await self._record_failure_and_maybe_abort(guild, channel, str(e)[:500]):
                        return
                    continue

                # Voice may have dropped while we were resolving.
                vc = guild.voice_client
                if vc is None or not vc.is_connected() or self.force_stopped.get(guild_id):
                    return

                try:
                    stderr_tail = _StderrTail()
                    source = discord.FFmpegPCMAudio(stream_url, stderr=stderr_tail, **FFMPEG_OPTS)
                    self.user_stopped[guild_id] = False
                    self.last_playback[guild_id] = {
                        "title": song.get("title"), "via": via or "YouTube/direct",
                        "started": time.monotonic(), "stderr": stderr_tail, "error": None, "ended_after": None,
                    }
                    vc.play(source, after=lambda err, gid=guild_id: self._after_song(gid, err))
                except Exception as e:
                    _log(f"{RED}⚠️ Failed to play: {song.get('title')} — {e}{RESET}")
                    if channel:
                        await channel.send(embed=Embed(
                            title="❌ Failed to Play",
                            description=f"Sorry, **{song.get('title')}** couldn't be played.",
                            color=discord.Color.red()
                        ))
                    if await self._record_failure_and_maybe_abort(guild, channel, f"Playback failure: {e}"):
                        return
                    continue

                self.fail_counts[guild_id] = 0
                self.currently_playing[guild_id] = {
                    "start_time": asyncio.get_running_loop().time(),
                    "duration": song.get("duration") or 0,
                    "song": song,
                }
                embed = Embed(title="Now Playing", description=song['title'], color=discord.Color.green())
                if song.get('thumbnail'):
                    embed.set_thumbnail(url=song['thumbnail'])
                if via:
                    embed.set_footer(text=f"YouTube was unavailable — playing via {via}")
                try:
                    if msg:
                        await msg.edit(embed=embed)
                        asyncio.create_task(self._delete_later(msg, NOW_PLAYING_DELETE_AFTER))
                    elif channel:
                        await channel.send(embed=embed, delete_after=NOW_PLAYING_DELETE_AFTER)
                except Exception:
                    pass
                return

            # Queue empty (or everything failed)
            self.currently_playing.pop(guild_id, None)
        asyncio.create_task(self.auto_disconnect(guild))

    async def _delete_later(self, msg: discord.Message, delay: float):
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass

    def _after_song(self, guild_id: str, error: Optional[Exception]):
        """Runs in the audio thread when a song finishes/is stopped."""
        info = self.last_playback.get(guild_id) or {}
        elapsed = time.monotonic() - info.get("started", time.monotonic())
        info["ended_after"] = round(elapsed, 1)
        info["error"] = str(error) if error else None
        song_len = (self.currently_playing.get(guild_id) or {}).get("duration") or 0
        # A song that ends within a few seconds on its own (not /skip or /leave) means FFmpeg
        # couldn't read/decode the stream -> tell the channel instead of failing silently.
        died_early = (not self.user_stopped.get(guild_id) and not self.force_stopped.get(guild_id)
                      and elapsed < 8 and (song_len == 0 or song_len > 10))
        ff = info["stderr"].text() if info.get("stderr") else ""
        if error or died_early:
            _log(f"{RED}⚠️ Playback problem in guild {guild_id} after {elapsed:.1f}s: {error} | ffmpeg: {ff}{RESET}")

        async def advance():
            if error or died_early:
                channel = last_channels.get(guild_id)
                details = (info.get("error") or "") + ("\n" + ff if ff else "")
                if channel:
                    try:
                        await channel.send(embed=Embed(
                            title="⚠️ Playback Stopped Unexpectedly",
                            description=(f"**{info.get('title')}** stopped after {elapsed:.1f}s.\n"
                                         f"```{(details.strip() or 'FFmpeg exited without an error message')[:1500]}```"
                                         "The bot owner can run `/musicdebug` for details."),
                            color=discord.Color.orange()))
                    except Exception:
                        pass
            await asyncio.sleep(0.3)  # let FFmpeg shut down cleanly
            guild = self.bot.get_guild(int(guild_id))
            if guild:
                if (error or died_early) and await self._record_failure_and_maybe_abort(
                        guild, last_channels.get(guild_id), f"Playback stopped after {elapsed:.1f}s"):
                    return
                await self.start_next(guild)

        asyncio.run_coroutine_threadsafe(advance(), self.bot.loop)

    async def auto_disconnect(self, guild: discord.Guild):
        await asyncio.sleep(IDLE_DISCONNECT_SECONDS)
        guild_id = str(guild.id)
        vc = guild.voice_client
        if not vc or vc.is_playing() or vc.is_paused() or queues.get(guild_id):
            return
        await vc.disconnect()
        queues[guild_id] = []
        save_queues(queues)
        channel = last_channels.get(guild_id)
        if channel:
            try:
                await channel.send(embed=Embed(
                    title="Jeng has ran away.",
                    description="No music playing — disconnected automatically.",
                    color=discord.Color.purple()
                ))
            except Exception:
                pass

    # ---- Commands ----
    @app_commands.command(name="play", description="Plays a song or playlist from YouTube or SoundCloud.")
    @app_commands.rename(url="search")
    @app_commands.describe(url="YouTube/SoundCloud URL or search term (prefix with sc: to search SoundCloud)")
    async def play(self, interaction: Interaction, url: str):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "use /play")
            return
        rem = self._play_cooldown_remaining(interaction.user.id)
        if rem > 0:
            await interaction.response.send_message(embed=Embed(
                title="⏳ Slow down",
                description=f"Please wait {int(math.ceil(rem))}s before using /play again.",
                color=discord.Color.orange()
            ), ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(embed=Embed(
                title="🔇 Join a Voice Channel",
                description="You need to be in a voice channel to use /play.",
                color=discord.Color.red()
            ), ephemeral=True)
            return
        self._mark_play_used(interaction.user.id)
        debug_command("play", interaction.user, interaction.guild, url=url)
        await interaction.response.defer(thinking=True)

        async def respond(embed: Embed, ephemeral: bool = False):
            return await interaction.edit_original_response(embed=embed)

        await self._enqueue(interaction, url, respond)

    @app_commands.command(name="np", description="Shows the currently playing song.")
    async def now_playing(self, interaction: Interaction):
        guild_id = str(interaction.guild.id)
        playing = self.currently_playing.get(guild_id)
        vc = interaction.guild.voice_client
        if not playing or not vc or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message(embed=Embed(title="No Song Playing", description="Nothing is currently playing.", color=discord.Color.red()))
            return

        elapsed = int(asyncio.get_running_loop().time() - playing["start_time"])
        total = playing["duration"] or 1
        elapsed = min(elapsed, total)
        bar_len = 20
        filled_len = int(bar_len * elapsed / total)
        bar = "▬" * min(filled_len, bar_len - 1) + "🔘" + "▬" * max(0, bar_len - filled_len - 1)
        embed = Embed(
            title="🎵 Now Playing",
            description=f"**{playing['song']['title']}**\n{bar}",
            color=discord.Color.orange()
        )
        if playing["song"].get("thumbnail"):
            embed.set_thumbnail(url=playing["song"]["thumbnail"])
        embed.set_footer(text=f"{elapsed // 60}:{elapsed % 60:02} / {total // 60}:{total % 60:02}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="Shows the current music queue.")
    async def queue(self, interaction: Interaction):
        debug_command("queue", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        song_queue = queues.get(str(interaction.guild.id), [])
        if not song_queue:
            await interaction.response.send_message(embed=Embed(title="Queue Empty", description="No songs in queue.", color=discord.Color.red()))
            return
        view = QueueView(song_queue)
        await interaction.response.send_message(embed=view.format_embed(), view=view)

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: Interaction):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "skip songs")
            return
        debug_command("skip", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self.user_stopped[str(interaction.guild.id)] = True
            vc.stop()  # triggers _after_song -> start_next
            await interaction.response.send_message(embed=Embed(title="Skipped", description="Skipped to the next song.", color=discord.Color.orange()))
        else:
            await interaction.response.send_message(embed=Embed(title="No Song Playing", description="Nothing to skip.", color=discord.Color.red()))

    @app_commands.command(name="stop", description="Pauses the music.")
    async def stop(self, interaction: Interaction):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "pause music")
            return
        debug_command("stop", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message(embed=Embed(title="Paused", description="Music paused. Use /start to resume.", color=discord.Color.orange()))
        else:
            await interaction.response.send_message(embed=Embed(title="No Music Playing", description="Nothing to pause.", color=discord.Color.red()))

    @app_commands.command(name="start", description="Resumes paused music.")
    async def start(self, interaction: Interaction):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "resume music")
            return
        debug_command("start", interaction.user, interaction.guild)
        last_channels[str(interaction.guild.id)] = interaction.channel
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message(embed=Embed(title="Resumed", description="Music resumed.", color=discord.Color.green()))
        else:
            await interaction.response.send_message(embed=Embed(title="Not Paused", description="Nothing is paused.", color=discord.Color.red()))

    @app_commands.command(name="leave", description="Disconnects from voice and clears queue.")
    async def leave(self, interaction: Interaction):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "disconnect the bot")
            return
        debug_command("leave", interaction.user, interaction.guild)
        guild_id = str(interaction.guild.id)
        last_channels[guild_id] = interaction.channel
        self.force_stopped[guild_id] = True
        queues[guild_id] = []
        save_queues(queues)
        self.currently_playing.pop(guild_id, None)

        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            await interaction.response.send_message(embed=Embed(title="Jeng has ran away.", description="Left the voice channel.", color=discord.Color.purple()))
        else:
            await interaction.response.send_message(embed=Embed(title="Not Connected", description="I'm not in a voice channel.", color=discord.Color.red()))

    @app_commands.command(name="queueshuffle", description="Shuffle the current song queue.")
    async def queueshuffle(self, interaction: Interaction):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "shuffle the queue")
            return
        guild_id = str(interaction.guild.id)
        if queues.get(guild_id):
            random.shuffle(queues[guild_id])
            save_queues(queues)
            await interaction.response.send_message(embed=Embed(title="🔀 Queue Shuffled", description="The queue has been shuffled.", color=discord.Color.green()))
        else:
            await interaction.response.send_message(embed=Embed(title="📭 Empty Queue", description="There is nothing to shuffle.", color=discord.Color.red()))

    # ---- Saved playlists ----
    def load_playlists(self):
        if os.path.exists(PLAYLIST_FILE):
            with open(PLAYLIST_FILE, "r") as f:
                return json.load(f)
        return {}

    def save_playlists(self, playlists):
        with open(PLAYLIST_FILE, "w") as f:
            json.dump(playlists, f, indent=4)

    @app_commands.command(name="removeplaylist", description="Delete a saved playlist.")
    async def remove_playlist(self, interaction: Interaction, name: str):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "modify playlists")
            return
        debug_command("removeplaylist", interaction.user, interaction.guild, name=name)
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id in playlists and name in playlists[guild_id]:
            del playlists[guild_id][name]
            self.save_playlists(playlists)
            await interaction.response.send_message(embed=Embed(title="🗑️ Playlist Removed", description=f"`{name}` has been deleted.", color=discord.Color.red()))
        else:
            await interaction.response.send_message(embed=Embed(title="⚠️ Not Found", description=f"No playlist found under `{name}`.", color=discord.Color.orange()))

    @app_commands.command(name="playplaylist", description="Play a previously saved playlist.")
    async def play_playlist(self, interaction: Interaction, name: str):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "start playlists")
            return
        debug_command("playplaylist", interaction.user, interaction.guild, name=name)
        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        if guild_id not in playlists or name not in playlists[guild_id]:
            await interaction.response.send_message(embed=Embed(title="⚠️ Not Found", description=f"No playlist saved under `{name}`.", color=discord.Color.red()))
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(embed=Embed(title="🔇 Join a Voice Channel", description="You need to be in a voice channel first.", color=discord.Color.red()), ephemeral=True)
            return

        await interaction.response.send_message(embed=Embed(title="📼 Loading Playlist", description=f"Now loading: `{name}`", color=discord.Color.blue()))

        async def respond(embed: Embed, ephemeral: bool = False):
            return await interaction.followup.send(embed=embed, ephemeral=ephemeral, wait=True)

        await self._enqueue(interaction, playlists[guild_id][name], respond)

    @app_commands.command(name="listplaylists", description="List saved playlists for this server.")
    async def list_playlists(self, interaction: Interaction):
        debug_command("listplaylists", interaction.user, interaction.guild)
        playlists = self.load_playlists().get(str(interaction.guild.id), {})
        if not playlists:
            await interaction.response.send_message(embed=Embed(title="📂 No Playlists", description="No playlists saved yet.", color=discord.Color.orange()))
            return
        embed = Embed(title="📚 Saved Playlists", color=discord.Color.blurple())
        for name, link in playlists.items():
            embed.add_field(name=name, value=link, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="saveplaylist", description="Save a playlist link under a custom name.")
    async def save_playlist(self, interaction: Interaction, name: str, link: str):
        if not self._user_is_dj(interaction):
            await self._deny_dj(interaction, "save playlists")
            return
        debug_command("saveplaylist", interaction.user, interaction.guild, name=name, link=link)
        rejection = self._url_rejection_embed(link)
        if rejection:
            await interaction.response.send_message(embed=rejection, ephemeral=True)
            return
        if not (link.startswith('http') and ("list=" in link.lower() or "playlist" in link.lower())):
            await interaction.response.send_message(embed=Embed(title="❌ Not a Playlist URL", description="Please provide a playlist URL, for example: https://www.youtube.com/playlist?list=PL...", color=discord.Color.orange()), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            info = await asyncio.to_thread(self.get_yt_info, link)
        except Exception as e:
            await interaction.edit_original_response(embed=Embed(title="⚠️ Playlist Validation Failed", description=f"Could not validate playlist: {str(e)[:1500]}", color=discord.Color.orange()))
            return
        if not info:
            await interaction.edit_original_response(embed=Embed(title="⚠️ Invalid Playlist", description="Could not validate the provided playlist link.", color=discord.Color.orange()))
            return

        guild_id = str(interaction.guild.id)
        playlists = self.load_playlists()
        playlists.setdefault(guild_id, {})[name] = link
        self.save_playlists(playlists)
        await interaction.edit_original_response(embed=Embed(title="✅ Playlist Saved", description=f"Saved `{name}`.", color=discord.Color.green()))

    # ---- DJ Role Commands ----
    @app_commands.command(name="setdj", description="Assign or update the DJ role for this server.")
    @app_commands.describe(role="Role that will have permission to control music features")
    async def set_dj(self, interaction: Interaction, role: discord.Role):
        if not is_bot_admin(interaction.user):
            await interaction.response.send_message(embed=Embed(title="❌ Missing Permission", description="You do not have permission to set the DJ role.", color=discord.Color.red()), ephemeral=True)
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
        if not is_bot_admin(interaction.user):
            await interaction.response.send_message(embed=Embed(title="❌ Missing Permission", description="You do not have permission to clear the DJ role.", color=discord.Color.red()), ephemeral=True)
            return
        removed = self.dj_roles.pop(str(interaction.guild.id), None)
        self._save_dj_config()
        msg = "DJ role cleared. All users may use music commands now." if removed else "No DJ role was set. Nothing changed."
        await interaction.response.send_message(embed=Embed(title="🎧 DJ Role Cleared", description=msg, color=discord.Color.orange()))

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
        await interaction.response.send_message(embed=Embed(title="🎧 DJ Info", description=desc, color=discord.Color.blurple()), ephemeral=True)

    # ---- Diagnostics ----
    def _audio_selftest(self) -> str:
        """Blocking: resolve a known YouTube video and decode 5s with FFmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return "❌ ffmpeg not found on PATH"
        try:
            url = self.get_stream_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        except Exception as e:
            return f"❌ yt-dlp could not resolve a YouTube stream: {str(e)[:300]}"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", *FFMPEG_OPTS["before_options"].split(),
               "-i", url, "-t", "5", "-vn", "-f", "s16le", "-ar", "48000", "-ac", "2", "-"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            return f"❌ ffmpeg failed to run: {e}"
        got, want = len(p.stdout), 48000 * 2 * 2 * 5
        ok = "✅" if got >= want * 0.9 else "❌"
        err = p.stderr.decode(errors="replace").strip()[:300]
        return f"{ok} decoded {got:,}/{want:,} bytes (rc={p.returncode})" + (f"\n{err}" if err else "")

    @app_commands.command(name="musicdebug", description="Owner-only: diagnose music playback problems.")
    async def music_debug(self, interaction: Interaction):
        app_info = await self.bot.application_info()
        if interaction.user.id != app_info.owner.id:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)

        def ver(mod):
            try:
                return __import__(mod).__version__
            except Exception:
                return "not installed"

        def first_line(exe, *args):
            path = shutil.which(exe)
            if not path:
                return "❌ not on PATH"
            try:
                out = subprocess.run([path, *args], capture_output=True, text=True, timeout=15,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return f"✅ {(out.stdout or out.stderr).splitlines()[0][:80]}"
            except Exception as e:
                return f"⚠️ {path}: {e}"

        try:
            opus_ok = discord.opus.is_loaded() or bool(discord.opus._load_default())
        except Exception:
            opus_ok = False

        embed = Embed(title="🔧 Music Debug", color=discord.Color.blurple())
        embed.add_field(name="Versions", inline=False, value=(
            f"Python {sys.version.split()[0]} · discord.py {discord.__version__} · davey {ver('davey')} · "
            f"yt-dlp {yt_dlp.version.__version__} · PyNaCl {ver('nacl')}"))
        embed.add_field(name="Tools", inline=False, value=(
            f"ffmpeg: {await asyncio.to_thread(first_line, 'ffmpeg', '-version')}\n"
            f"deno: {await asyncio.to_thread(first_line, 'deno', '--version')}\n"
            f"opus loaded: {'✅' if opus_ok else '❌'}"))

        vc = interaction.guild.voice_client
        if vc:
            conn = getattr(vc, "_connection", None)
            embed.add_field(name="Voice", inline=False, value=(
                f"connected: {vc.is_connected()} · channel: {getattr(vc.channel, 'name', '?')}\n"
                f"playing: {vc.is_playing()} · paused: {vc.is_paused()} · latency: {vc.latency * 1000:.0f} ms\n"
                f"DAVE version: {getattr(conn, 'dave_protocol_version', '?')} · "
                f"encrypting: {getattr(conn, 'can_encrypt', '?')} · privacy code: {getattr(vc, 'voice_privacy_code', None)}"))
        else:
            embed.add_field(name="Voice", value="Not connected in this server.", inline=False)

        lp = self.last_playback.get(str(interaction.guild.id))
        if lp:
            ff = lp["stderr"].text() if lp.get("stderr") else ""
            ran = "still playing" if lp.get("ended_after") is None else f"ended after {lp['ended_after']}s"
            embed.add_field(name="Last song", inline=False, value=(
                f"**{lp.get('title')}** via {lp.get('via')} — {ran}\n"
                f"error: {lp.get('error') or 'none'}\nffmpeg: {(ff or 'no output')[:500]}"))

        embed.add_field(name="Self-test (YouTube → FFmpeg, 5s)", inline=False,
                        value=(await asyncio.to_thread(self._audio_selftest))[:1000])
        await interaction.edit_original_response(embed=embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """If the bot is kicked/disconnected from voice, reset that guild's state."""
        if member.id != self.bot.user.id or before.channel is None or after.channel is not None:
            return
        guild_id = str(member.guild.id)
        self.force_stopped[guild_id] = True
        queues[guild_id] = []
        save_queues(queues)
        self.currently_playing.pop(guild_id, None)


async def setup(bot):
    await bot.add_cog(Music(bot))
