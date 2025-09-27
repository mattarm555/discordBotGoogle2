import discord
from discord.ext import commands
from discord import app_commands, Interaction
import asyncio
import aiohttp
import os
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from utils.debug import debug_command
import logging

logger = logging.getLogger("jeng.follow")
# Default to INFO for this cog so routine checks (debug-level) don't spam the console.
# We still log INFO for actual postings and WARN/ERROR for problems.
logger.setLevel(logging.INFO)


FOLLOW_FILE = "followings.json"


def load_followings():
    if os.path.exists(FOLLOW_FILE):
        with open(FOLLOW_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_followings(data):
    with open(FOLLOW_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class Follow(commands.Cog):
    """Follow YouTube (RSS) and Twitch (optional) channels and post new links to a Discord channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.followings = load_followings()  # guild_id -> list of subs
        self.session = aiohttp.ClientSession()
        # concurrency limiter for parallel checks
        self._sem = asyncio.Semaphore(10)
        # per-channel locks to avoid interleaving pings/messages for multiple subs
        self._channel_locks: dict[int, asyncio.Lock] = {}
        # Twitch token cache
        self._twitch_token = None
        self._twitch_token_expiry = 0.0
        # per-subscription last-checked timestamps to throttle platform checks
        # key: subscription id (the stored s.get('id')), value: epoch seconds
        self._last_checked: dict[str, float] = {}
        # minimum interval (seconds) between YouTube checks for the same subscription
        # default 15 minutes; can be overridden with env var YOUTUBE_MIN_INTERVAL (seconds)
        try:
            self._youtube_min_interval = float(os.getenv('YOUTUBE_MIN_INTERVAL', '900'))
        except Exception:
            self._youtube_min_interval = 900.0
        # background worker
        # Use asyncio.create_task to schedule the worker on the running loop.
        # Using bot.loop.create_task can fail silently with some event loop setups.
        self.worker_task = asyncio.create_task(self.worker())

    async def cog_unload(self):
        self.worker_task.cancel()
        await self.session.close()

    async def _get_youtube_channel_thumbnail(self, identifier: str):
        """Attempt to fetch a YouTube channel/profile image from the channel page's og:image meta tag."""
        try:
            if identifier.startswith('http'):
                url = identifier
            else:
                if identifier.startswith('UC'):
                    url = f'https://www.youtube.com/channel/{identifier}'
                else:
                    url = f'https://www.youtube.com/user/{identifier}'

            text = await self._fetch_text(url)
            if not text:
                return None
            m = re.search(r'<meta property="og:image" content="([^"]+)"', text)
            if m:
                return m.group(1)
        except Exception:
            logger.exception("[Follow] Error fetching YouTube thumbnail")
        return None

    async def _resolve_youtube_handle(self, identifier: str) -> str | None:
        """Resolve YouTube handle or @username pages to a canonical channel id (UC...).

        Accepts forms like:
        - https://www.youtube.com/@handle
        - @handle
        - youtube.com/@handle
        Returns a channel id (UC...) when possible, otherwise None.
        """
        try:
            # Normalize simple handle forms
            ident = identifier.strip()
            if ident.startswith('@'):
                url = f'https://www.youtube.com/{ident}'
            elif ident.startswith('http') and '/@' in ident:
                url = ident
            elif ident.startswith('www.youtube.com/@') or ident.startswith('youtube.com/@'):
                if not ident.startswith('http'):
                    url = 'https://' + ident
                else:
                    url = ident
            else:
                return None

            text = await self._fetch_text(url)
            if not text:
                return None
            # Look for canonical channel link or og:url containing /channel/UC...
            m = re.search(r'href="(/channel/(UC[A-Za-z0-9_-]{20,}))"', text)
            if m:
                return m.group(1).split('/')[-1]
            m = re.search(r'property="og:url" content="https?://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})"', text)
            if m:
                return m.group(1)
            # Another fallback: look for canonical link tag
            m = re.search(r'<link rel="canonical" href="https?://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})"', text)
            if m:
                return m.group(1)
        except Exception:
            logger.exception("[Follow] Error resolving YouTube handle")
        return None


    @app_commands.command(name="follow", description="Follow a YouTube or Twitch channel and post new content to a channel.")
    @app_commands.choices(platform=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
    ])
    @app_commands.choices(ping_target=[
        app_commands.Choice(name="No ping", value="none"),
        app_commands.Choice(name="@everyone", value="everyone"),
        app_commands.Choice(name="Choose a role", value="role"),
    ])
    @app_commands.describe(platform="Platform (choose YouTube or Twitch)", identifier="Channel id, username, or URL", post_channel="Text channel to post into", ping_target="Who to ping when posting updates", ping_role="Optional role to ping (required if you choose 'Choose a role')", message="Message template (use {url}, {title}, {channel})")
    async def follow(self, interaction: Interaction, platform: str, identifier: str, post_channel: discord.TextChannel, ping_target: app_commands.Choice[str], ping_role: discord.Role = None, message: str = "New content: {url}"):
        # Restrict this command to guild administrators or the bot owner
        # Defer early so the user sees a response promptly when unauthorized
        await interaction.response.defer(thinking=True)
        is_admin = interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        subs = self.followings.setdefault(guild_id, [])

        sub_id = f"{platform}:{identifier}:{post_channel.id}"
        # avoid duplicates
        for s in subs:
            if s.get("id") == sub_id:
                embed = discord.Embed(title="❌ Subscription Exists", description="This subscription already exists for this server and channel.", color=discord.Color.orange())
                await interaction.followup.send(embed=embed)
                return

        # build a friendly link for the identifier
        display_link = identifier
        try:
            if platform.lower() == 'youtube':
                if identifier.startswith('http'):
                    display_link = identifier
                elif identifier.startswith('UC'):
                    display_link = f'https://www.youtube.com/channel/{identifier}'
                else:
                    display_link = f'https://www.youtube.com/user/{identifier}'
            elif platform.lower() == 'twitch':
                if identifier.startswith('http'):
                    display_link = identifier
                else:
                    display_link = f"https://twitch.tv/{identifier.rstrip('/')}"
        except Exception:
            display_link = identifier

        # Validate that the target (YouTube/Twitch) exists before saving and try to fetch thumbnail
        thumb = None
        try:
            if platform.lower() == 'youtube':
                # Build feed URL similar to check_youtube
                # handle-style identifiers may be like youtube.com/@handle or @handle
                resolved_channel = None
                if ('@' in identifier) or identifier.startswith('@') or ('/@' in identifier):
                    try:
                        resolved_channel = await self._resolve_youtube_handle(identifier)
                    except Exception:
                        logger.exception("[Follow] Error resolving youtube handle during follow validation")
                if identifier.startswith('http'):
                    if 'channel/' in identifier:
                        channel_part = identifier.split('channel/')[-1].split('/')[0]
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_part}"
                    elif 'user/' in identifier:
                        user_part = identifier.split('user/')[-1].split('/')[0]
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?user={user_part}"
                    else:
                        # if we resolved a channel id from a handle, use that
                        if resolved_channel:
                            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={resolved_channel}"
                        else:
                            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={identifier}"
                else:
                    if identifier.startswith('UC'):
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={identifier}"
                    else:
                        # if we resolved a channel id from a handle, use that
                        if resolved_channel:
                            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={resolved_channel}"
                        else:
                            feed_url = f"https://www.youtube.com/feeds/videos.xml?user={identifier}"
                # after building feed_url, verify the feed is reachable
                feed_text = await self._fetch_text(feed_url)
                if not feed_text:
                    embed = discord.Embed(title="❌ YouTube Channel Not Found", description=f"Could not find a YouTube channel for `{identifier}`. Please check the identifier or URL and try again.", color=discord.Color.red())
                    await interaction.followup.send(embed=embed)
                    return
                thumb = await self._get_youtube_channel_thumbnail(identifier)

            elif platform.lower() == 'twitch':
                # try to resolve username
                if identifier.startswith('http'):
                    username = identifier.rstrip('/').split('/')[-1]
                else:
                    username = identifier

                client_id = os.getenv('TWITCH_CLIENT_ID')
                client_secret = os.getenv('TWITCH_CLIENT_SECRET')
                resolved = False
                if client_id and client_secret:
                    token = await self._get_twitch_token(client_id, client_secret)
                    headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'} if token else {'Client-ID': client_id}
                    j = await self._fetch_json('https://api.twitch.tv/helix/users', params={'login': username}, headers=headers)
                    if j and j.get('data'):
                        resolved = True
                        thumb = j['data'][0].get('profile_image_url')
                else:
                    # Fallback: try to fetch the twitch page and ensure it returns text
                    page = await self._fetch_text(f"https://twitch.tv/{username}")
                    if page:
                        resolved = True

                if not resolved:
                    embed = discord.Embed(title="❌ Twitch Channel Not Found", description=f"Could not find a Twitch channel for `{identifier}`. Please check the identifier or URL and try again.", color=discord.Color.red())
                    await interaction.followup.send(embed=embed)
                    return
        except Exception:
            logger.exception("[Follow] Error validating target identifier")
            embed = discord.Embed(title="❌ Validation Error", description="An error occurred while validating the provided identifier.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            return

    # try to fetch a thumbnail for the channel (YouTube or Twitch)
    # If already resolved above, keep that thumb
        try:
            if platform.lower() == 'youtube':
                if not thumb:
                    thumb = await self._get_youtube_channel_thumbnail(identifier)
            elif platform.lower() == 'twitch':
                # attempt to fetch via helix if creds exist
                client_id = os.getenv('TWITCH_CLIENT_ID')
                client_secret = os.getenv('TWITCH_CLIENT_SECRET')
                if client_id and client_secret:
                    token = await self._get_twitch_token(client_id, client_secret)
                    headers = {'Client-ID': client_id, 'Authorization': f'Bearer {token}'} if token else {'Client-ID': client_id}
                    j = await self._fetch_json('https://api.twitch.tv/helix/users', params={'login': username if 'username' in locals() else identifier}, headers=headers)
                    if j and j.get('data'):
                        thumb = j['data'][0].get('profile_image_url')
        except Exception:
            logger.exception("[Follow] Error fetching thumbnail")

        # store ping_target (none/everyone/role) and role id only when relevant
        new = {
            "id": sub_id,
            "platform": platform.lower(),
            "identifier": identifier,
            "post_channel": post_channel.id,
            "message": message,
            "ping_target": ping_target.value if ping_target else "none",
            "ping_role": ping_role.id if (ping_target and ping_target.value == 'role' and ping_role) else None,
            "thumbnail": thumb,
            "last_seen": None
        }
        # Confirm the bot can post in the target channel before saving. This keeps
        # the command to a single ephemeral confirmation message.
        try:
            bot_member = interaction.guild.me
            perms = post_channel.permissions_for(bot_member) if bot_member else post_channel.permissions_for(interaction.guild.get_member(self.bot.user.id))
            if not perms.send_messages:
                embed = discord.Embed(title="❌ Cannot Post To Channel", description=f"I don't have permission to send messages in {post_channel.mention}. Please grant Send Messages permission and try again.", color=discord.Color.red())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
        except Exception:
            # If anything goes wrong checking perms, log and continue to avoid blocking user
            logger.exception("[Follow] Error checking permissions for target channel")

        subs.append(new)
        save_followings(self.followings)

        # send embedded confirmation similar to misc
        embed = discord.Embed(title="✅ Subscribed", color=discord.Color.green())
        embed.add_field(name="Platform", value=platform, inline=True)
        embed.add_field(name="Identifier", value=identifier, inline=True)
        embed.add_field(name="Posting Channel", value=post_channel.mention, inline=True)
        embed.add_field(name="Link", value=display_link, inline=False)
        # show chosen ping target in confirmation
        if new.get('ping_target') == 'none' or not new.get('ping_target'):
            embed.add_field(name="Ping", value="None", inline=True)
        elif new.get('ping_target') == 'everyone':
            embed.add_field(name="Ping", value="@everyone", inline=True)
        elif new.get('ping_target') == 'role':
            if ping_role:
                embed.add_field(name="Ping", value=ping_role.name, inline=True)
            else:
                embed.add_field(name="Ping", value="Role (not provided)", inline=True)
        if new.get('thumbnail'):
            embed.set_thumbnail(url=new.get('thumbnail'))
        await interaction.followup.send(embed=embed, ephemeral=True)

        # log the subscription with the channel link we're following
        try:
            debug_command("follow", interaction.user, guild=interaction.guild, channel=post_channel, target=display_link, platform=platform)
        except Exception:
            logger.exception("[Follow] debug_command failed after follow")

        # Intentionally do NOT announce or ping the target channel at command time.
        # The subscription is saved and the background worker will post updates when new content
        # appears. This avoids pinging roles/users when nothing is being posted immediately.

    @app_commands.command(name="removefollow", description="Remove a follow subscription")
    @app_commands.describe(sub_id="Subscription id from /follow_list")
    async def follow_remove(self, interaction: Interaction, sub_id: str):
        # Restrict this command to guild administrators or the bot owner
        await interaction.response.defer(thinking=True, ephemeral=True)
        is_admin = interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)
            return

        # try to find the subscription and log the followed channel link
        import hashlib

        guild_id = str(interaction.guild.id)
        subs = self.followings.get(guild_id, [])

        # Resolve the subscription to remove. Support three input types:
        # 1) full id (platform:identifier:channel)
        # 2) short id (8-char sha1 prefix printed in /followlist)
        # 3) identifier (e.g. the channel username like 'jengfreak')
        found = None
        # short-id resolution (8 hex chars)
        if sub_id and len(sub_id) == 8 and all(c in '0123456789abcdef' for c in sub_id.lower()):
            matches = [s for s in subs if hashlib.sha1(s.get('id','').encode('utf-8')).hexdigest().startswith(sub_id.lower())]
            if len(matches) == 1:
                found = matches[0]
            elif len(matches) > 1:
                # ambiguous short id
                embed = discord.Embed(title="❌ Ambiguous ID", description=f"The short id `{sub_id}` matches multiple subscriptions:\n{choices}", color=discord.Color.orange())
                await interaction.response.defer(thinking=True)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # exact full-id match
        if not found:
            found = next((s for s in subs if s.get('id') == sub_id), None)

        # match by identifier (e.g. username) if still not found
        if not found:
            ident_matches = [s for s in subs if s.get('identifier') == sub_id]
            if len(ident_matches) == 1:
                found = ident_matches[0]
            elif len(ident_matches) > 1:
                # ambiguous identifier (multiple subs for this identifier)
                choices = '\n'.join([f"{hashlib.sha1(s.get('id','').encode('utf-8')).hexdigest()[:8]} — {s.get('id')}" for s in ident_matches])
                embed = discord.Embed(title="❌ Ambiguous Identifier", description=f"The identifier `{sub_id}` matches multiple subscriptions:\n{choices}", color=discord.Color.orange())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
        if found:
            ident = found.get('identifier')
            platform = found.get('platform')
            if platform == 'youtube':
                if ident.startswith('http'):
                    display_link = ident
                elif ident.startswith('UC'):
                    display_link = f'https://www.youtube.com/channel/{ident}'
                else:
                    display_link = f'https://www.youtube.com/user/{ident}'
            elif platform == 'twitch':
                if ident.startswith('http'):
                    display_link = ident
                else:
                    display_link = f"https://twitch.tv/{ident.rstrip('/')}"
        else:
            display_link = sub_id

        debug_command("removefollow", interaction.user, guild=interaction.guild, channel=interaction.channel, target=display_link)
        guild_id = str(interaction.guild.id)
        subs = self.followings.get(guild_id, [])

        # Determine the actual id to remove: if we resolved a subscription via short id,
        # use the full stored id (found.get('id')), otherwise use the provided sub_id.
        target_id = found.get('id') if found else sub_id

        new_subs = [s for s in subs if s.get("id") != target_id]
        if len(new_subs) == len(subs):
            embed = discord.Embed(title="❌ Subscription Not Found", description=f"No subscription with id `{sub_id}` was found for this server.", color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            return
        self.followings[guild_id] = new_subs
        save_followings(self.followings)
        # show the original id the user supplied (short or full) in the confirmation
        embed = discord.Embed(title="✅ Subscription Removed", description=f"Removed subscription: `{sub_id}`", color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="followlist", description="List follow subscriptions for this server")
    async def follow_list(self, interaction: Interaction):
        """Nicely format the follow subscriptions for the invoking server.

        Each subscription is shown as its own embed field (or its own embed if many),
        with a shortened id for readability, linked identifier, posting channel, template,
        and ping info. Long templates are truncated.
        """
        import hashlib

        # Restrict this command to guild administrators or the bot owner
        await interaction.response.defer(thinking=True)
        is_admin = interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.followup.send("❌ You do not have permission to use this command.", ephemeral=True)
            return

        debug_command("followlist", interaction.user, guild=interaction.guild, channel=interaction.channel)
        guild_id = str(interaction.guild.id)
        subs = self.followings.get(guild_id, [])
        if not subs:
            embed = discord.Embed(title="No Subscriptions", description="This server has no follow subscriptions.", color=discord.Color.dark_blue())
            await interaction.followup.send(embed=embed)
            return

        # helper to shorten long ids deterministically
        def short_id(full_id: str) -> str:
            if not full_id:
                return "-"
            # if already short-ish, keep it
            if len(full_id) <= 12:
                return full_id
            h = hashlib.sha1(full_id.encode('utf-8')).hexdigest()
            return h[:8]

        # build embeds in chunks to avoid exceeding field limits
        embeds = []
        current = discord.Embed(title="Follow Subscriptions", color=discord.Color.blurple())
        fields = 0

        for s in subs:
            sid = s.get('id')
            sid_short = short_id(sid)
            platform = s.get('platform') or "?"
            ident = s.get('identifier') or "?"
            # make a link for known platforms
            if platform == 'youtube':
                if ident.startswith('http'):
                    ident_link = ident
                elif ident.startswith('UC'):
                    ident_link = f'https://www.youtube.com/channel/{ident}'
                else:
                    ident_link = f'https://www.youtube.com/user/{ident}'
            elif platform == 'twitch':
                if ident.startswith('http'):
                    ident_link = ident
                else:
                    ident_link = f'https://twitch.tv/{ident.rstrip("/")}'
            else:
                ident_link = ident

            ch = interaction.guild.get_channel(s.get('post_channel'))
            dest = ch.mention if ch else f"Channel ID {s.get('post_channel')}"

            template = s.get('message') or ''
            if len(template) > 150:
                template = template[:147] + '...'

            # show ping target and role if configured
            pt = s.get('ping_target') or 'none'
            if pt == 'none':
                ping_text = 'None'
            elif pt == 'everyone':
                ping_text = '@everyone'
            elif pt == 'role':
                if s.get('ping_role'):
                    ping_text = f"Role: <@&{s.get('ping_role')}>"
                else:
                    ping_text = 'Role: (not set)'
            else:
                ping_text = 'Unknown'

            field_name = f"[{sid_short}] {platform.upper()} — {ident}"
            field_value = f"Posting: {dest}\nPing: {ping_text}\nTemplate: {template}"

            # add small thumbnail if available
            if s.get('thumbnail'):
                # set thumbnail on the embed itself for the first field
                if current.thumbnail is None:
                    try:
                        current.set_thumbnail(url=s.get('thumbnail'))
                    except Exception:
                        pass

            current.add_field(name=field_name, value=field_value, inline=False)
            fields += 1

            # Discord embeds limit: 25 fields. Keep a safe chunk size (10) for readability.
            if fields >= 10:
                embeds.append(current)
                current = discord.Embed(color=discord.Color.blurple())
                fields = 0

        if fields > 0 or not embeds:
            embeds.append(current)

        # send the embeds (if multiple, send them in order)
        for e in embeds:
            await interaction.followup.send(embed=e)

    @app_commands.command(name="follow_check", description="Force check all follows now (debug)")
    async def follow_check(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self.check_all()
            await interaction.followup.send("✅ Manual check done.", ephemeral=True)
        except Exception:
            logger.exception("[Follow] Manual follow_check failed")
            await interaction.followup.send("❌ Manual check failed; see logs.", ephemeral=True)
    

    async def worker(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("[Follow Worker] Error during check_all")
            await asyncio.sleep(180)  # poll every 3 minutes

    async def check_all(self):
        # iterate over follows and run checks in parallel with a semaphore
        tasks = []
        for guild_id, subs in list(self.followings.items()):
            for sub in subs:
                async def _run(sub=sub, guild_id=guild_id):
                    async with self._sem:
                        try:
                            platform = sub.get("platform")
                            sid = sub.get('id')
                            now = time.time()
                            # Throttle YouTube checks per-subscription to avoid rapid re-checks
                            if platform == "youtube":
                                last = self._last_checked.get(sid)
                                if last and (now - last) < self._youtube_min_interval:
                                    logger.debug(f"[Follow] Skipping YouTube check for {sid}; last checked {now-last:.1f}s ago")
                                    return
                                # mark as checked now (so concurrent runs won't duplicate work)
                                self._last_checked[sid] = now
                                await self.check_youtube(sub, guild_id)
                            elif platform == "twitch":
                                await self.check_twitch(sub, guild_id)
                        except Exception:
                            logger.exception(f"[Follow] Error checking {sub.get('id')}")
                tasks.append(_run())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def check_youtube(self, sub, guild_id, force: bool = False):
        # Use YouTube Data API v3 to fetch the latest upload for a channel.
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            logger.warning("[Follow] Skipping YouTube check: YOUTUBE_API_KEY not set")
            return

        ident = sub.get("identifier")
        # Resolve handle-style identifiers to a channel id starting with UC...
        try:
            if ident and (ident.startswith('@') or ('/@' in ident) or '/@' in ident or (ident.startswith('http') and '/@' in ident)):
                resolved = await self._resolve_youtube_handle(ident)
                if resolved:
                    ident = resolved
        except Exception:
            logger.exception("[Follow] Error resolving youtube handle in check_youtube")

        # If the identifier is a URL, try to pull out a channel id if present
        if ident and ident.startswith('http'):
            if 'channel/' in ident:
                ident = ident.split('channel/')[-1].split('/')[0]

        # Only channelId (UC...) is supported for the search endpoint with channel filtering
        if not ident or not str(ident).startswith('UC'):
            logger.debug(f"[Follow] YouTube check skipped: identifier {ident} is not a channel ID (UC...); please use a channel id or let handle resolution run during follow registration")
            return

        # update last-checked timestamp for this subscription unless this is a forced check
        sid = sub.get('id')
        if sid and not force:
            # note: the caller (check_all) already sets _last_checked before invoking
            # but ensure it's present for callers that call check_youtube directly
            self._last_checked.setdefault(sid, time.time())

        # Prefer using the uploads playlist for the channel (more efficient than search.list)
        vid = None
        title = None
        playlist_id = sub.get('uploads_playlist')
        try:
            if not playlist_id:
                playlist_id = await self._get_uploads_playlist(ident)
                if playlist_id:
                    sub['uploads_playlist'] = playlist_id
                    save_followings(self.followings)

            if playlist_id:
                res = await self._get_latest_from_playlist(playlist_id)
                if res:
                    vid, title = res
                    title = title or 'New video'
            # Fallback to search.list if uploads playlist approach failed
            if not vid:
                logger.debug(f"[Follow] Falling back to search.list for channel {ident}")
                url = 'https://www.googleapis.com/youtube/v3/search'
                params = {
                    'key': api_key,
                    'channelId': ident,
                    'part': 'snippet,id',
                    'order': 'date',
                    'maxResults': 1,
                    # restrict to video type only
                    'type': 'video'
                }
                data = await self._fetch_json(url, params=params)
                if not data or 'items' not in data or not data['items']:
                    logger.debug(f"[Follow] YouTube API returned no items for channel {ident}")
                    return
                item = data['items'][0]
                vid = item.get('id', {}).get('videoId')
                title = item.get('snippet', {}).get('title', 'New video')
                if not vid:
                    logger.debug(f"[Follow] YouTube API item missing videoId for channel {ident}")
                    return
        except Exception:
            logger.exception(f"[Follow] Exception while fetching latest YouTube video for {ident}")
            return

        vid_norm = str(vid).strip()
        last = sub.get('last_seen')
        if last is not None:
            try:
                last = str(last).strip()
            except Exception:
                pass

        if not force and last and vid_norm == last:
            logger.debug(f"[Follow] YouTube no-new: {ident} (video {vid_norm}) already seen")
            return

        video_url = f"https://youtu.be/{vid_norm}"

        # New video found → post
        try:
            await self._post_youtube(sub, guild_id, vid_norm, video_url, title, ident)
        except Exception:
            logger.exception(f"[Follow] Failed to post YouTube video for {ident}")

    async def check_twitch(self, sub, guild_id):
        # Twitch support requires client id/secret and is optional
        client_id = os.getenv('TWITCH_CLIENT_ID')
        client_secret = os.getenv('TWITCH_CLIENT_SECRET')
        if not client_id or not client_secret:
            logger.info(f"[Follow] Skipping Twitch check: missing credentials for {sub.get('identifier')}")
            return
        ident = sub.get('identifier')
        # try to extract username from URL
        if ident.startswith('http'):
            username = ident.rstrip('/').split('/')[-1]
        else:
            username = ident

        # get app token (cached)
        access_token = await self._get_twitch_token(client_id, client_secret)
        if not access_token:
            logger.warning(f"[Follow] Could not obtain Twitch token for checking {username}")
            return
        headers = {'Client-ID': client_id, 'Authorization': f'Bearer {access_token}'}

        # get user id
        j = await self._fetch_json('https://api.twitch.tv/helix/users', params={'login': username}, headers=headers)
        if not j:
            logger.debug(f"[Follow] Skipping Twitch check: failed to fetch user for {username}")
            return
        if not j.get('data'):
            logger.debug(f"[Follow] Twitch user not found for {username}")
            return
        user_id = j['data'][0]['id']

        # check streams
        j = await self._fetch_json('https://api.twitch.tv/helix/streams', params={'user_id': user_id}, headers=headers)
        if not j:
            logger.debug(f"[Follow] Skipping Twitch check: failed to fetch streams for {username}")
            return
        streams = j.get('data', [])
        if not streams:
            logger.debug(f"[Follow] Twitch no-live-stream for {username}")
            return
        stream = streams[0]
        stream_id = stream.get('id')
        last = sub.get('last_seen')
        if last == stream_id:
            logger.debug(f"[Follow] Twitch no-new: {username} stream {stream_id} already seen")
            return

        # post
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
        channel = guild.get_channel(sub.get('post_channel'))
        if not channel:
            return
        url = f"https://twitch.tv/{username}"
        title = stream.get('title')
        msg = sub.get('message', 'Live now: {url}')
        # build ping prefix from ping_target and ping_role
        ping_target = sub.get('ping_target') or 'none'
        ping_role_id = sub.get('ping_role')
        ping_parts = []
        if ping_target == 'everyone':
            ping_parts.append('@everyone')
        elif ping_target == 'role' and ping_role_id:
            try:
                role = guild.get_role(int(ping_role_id)) if guild else None
            except Exception:
                role = None
            if role:
                ping_parts.append(role.mention)
            else:
                ping_parts.append(f"<@&{ping_role_id}>")
        ping_prefix = ' '.join(ping_parts)

        # build content and embed text
        content_text = msg.replace('{url}', url).replace('{title}', title).replace('{channel}', username)
        # If the template doesn't already contain a twitch link, append the canonical channel URL so the link is always posted.
        contains_twitch_link = bool(re.search(r"(?i)(twitch\.tv/|clips\.twitch\.tv/)", content_text))
        if not contains_twitch_link:
            append_url = url
            content_text = content_text + ("\n" if content_text and not content_text.endswith("\n") else "") + append_url
            logger.info(f"[Follow] Appended Twitch channel URL for {username}: {append_url}")

        # avoid double-pinging if the template already contains a mention anywhere (including plain @role/user)
        # detect mentions, including repeated leading @ like @@everyone
        body_has_mention = bool(re.search(r"(?i)(<@|<@&|@+everyone|@+here|(?<!\S)@+[\w-]+)", content_text))
        logger.debug(f"[Follow] Twitch post ping_role={ping_role_id} body_has_mention={body_has_mention}")

        final_content = ping_prefix if (ping_prefix and not body_has_mention) else None
        # send ping+message under the channel lock to avoid interleaving with other subs
        lock = self._get_channel_lock(channel.id)
        async with lock:
            # send ping first if needed
            if final_content:
                try:
                    logger.info(f"[Follow] Sending ping to {channel} for Twitch {username}: {final_content}")
                    await channel.send(content=final_content)
                except Exception:
                    logger.exception(f"[Follow] Failed to send ping message to {channel}")

            # send plain message (no embed) with the template replacements
            try:
                if not content_text or not str(content_text).strip():
                    logger.info(f"[Follow] Skipping Twitch send: content_text empty for {username}")
                else:
                    logger.info(f"[Follow] Sending Twitch post to {channel} for {username}: title={title}")
                    await channel.send(content=content_text)
                    logger.info(f"[Follow] Posted Twitch live for {username} to {channel}")
            except Exception:
                logger.exception(f"[Follow] Failed to post twitch to {channel}")

        sub['last_seen'] = stream_id
        save_followings(self.followings)

    async def _fetch_text(self, url, params=None, headers=None, retries=2, backoff=1):
        for attempt in range(retries):
            try:
                async with self.session.get(url, params=params, headers=headers, timeout=30) as resp:
                    status = resp.status
                    if status != 200:
                        logger.info(f"[Follow] fetch_text status={status} for {url}")
                    if status == 200:
                        return await resp.text()
                    else:
                        logger.debug(f"[Follow] fetch_text non-200 {status} for {url}")
            except Exception as e:
                logger.info(f"[Follow] fetch_text error on attempt {attempt+1} for {url}: {e}")
            await asyncio.sleep(backoff * (attempt + 1))
        return None

    async def _fetch_json(self, url, params=None, headers=None, retries=2, backoff=1):
        text = await self._fetch_text(url, params=params, headers=headers, retries=retries, backoff=backoff)
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            logger.exception(f"[Follow] Failed to parse JSON from {url}")
            return None

    async def _get_uploads_playlist(self, channel_id: str) -> str | None:
        """Return the uploads playlistId for a channel id (UC...).

        Uses channels.list?part=contentDetails&id=<channelId>
        """
        api_key = os.getenv('YOUTUBE_API_KEY')
        if not api_key:
            return None
        url = 'https://www.googleapis.com/youtube/v3/channels'
        params = {'part': 'contentDetails', 'id': channel_id, 'key': api_key}
        j = await self._fetch_json(url, params=params)
        if not j or 'items' not in j or not j['items']:
            logger.debug(f"[Follow] channels.list returned no items for {channel_id}")
            return None
        try:
            uploads = j['items'][0]['contentDetails']['relatedPlaylists'].get('uploads')
            return uploads
        except Exception:
            logger.exception(f"[Follow] Failed to extract uploads playlist for {channel_id}")
            return None

    async def _get_latest_from_playlist(self, playlist_id: str) -> tuple[str, str] | None:
        """Return (videoId, title) for the newest item in a playlist using playlistItems.list."""
        api_key = os.getenv('YOUTUBE_API_KEY')
        if not api_key:
            return None
        url = 'https://www.googleapis.com/youtube/v3/playlistItems'
        params = {'part': 'snippet', 'playlistId': playlist_id, 'maxResults': 1, 'key': api_key}
        j = await self._fetch_json(url, params=params)
        if not j or 'items' not in j or not j['items']:
            logger.debug(f"[Follow] playlistItems.list returned no items for {playlist_id}")
            return None
        try:
            item = j['items'][0]
            video_id = item['snippet']['resourceId'].get('videoId')
            title = item['snippet'].get('title')
            return (video_id, title)
        except Exception:
            logger.exception(f"[Follow] Failed to parse playlistItems for {playlist_id}")
            return None

    async def _post_youtube(self, sub, guild_id, vid_norm, video_url, title, ident):
        """Send the YouTube post to the configured channel and update last_seen."""
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            logger.info(f"[Follow] Guild {guild_id} not found for posting YouTube {ident}")
            return
        channel = guild.get_channel(sub.get('post_channel'))
        if not channel:
            logger.info(f"[Follow] Channel {sub.get('post_channel')} not found for guild {guild_id}")
            return

        msg = sub.get('message', 'New content: {url}')
        # build ping prefix from ping_target and ping_role
        ping_target = sub.get('ping_target') or 'none'
        ping_role_id = sub.get('ping_role')
        ping_parts = []
        if ping_target == 'everyone':
            ping_parts.append('@everyone')
        elif ping_target == 'role' and ping_role_id:
            try:
                role = guild.get_role(int(ping_role_id)) if guild else None
            except Exception:
                role = None
            if role:
                ping_parts.append(role.mention)
            else:
                ping_parts.append(f"<@&{ping_role_id}>")
        ping_prefix = ' '.join(ping_parts)

        # build content text from template and ensure the video URL is present
        content_text = msg.replace('{url}', video_url).replace('{title}', title).replace('{channel}', ident)
        contains_youtube_link = bool(re.search(r"(?i)(youtu\.be/|youtube\.com/watch\?|youtube\.com/shorts/|youtube\.com/)", content_text))
        if vid_norm and not contains_youtube_link:
            append_url = f"https://youtu.be/{vid_norm}"
            content_text = content_text + ("\n" if content_text and not content_text.endswith("\n") else "") + append_url

        # detect mentions anywhere in the content_text
        body_has_mention = bool(re.search(r"(?i)(<@|<@&|@+everyone|@+here|(?<!\S)@+[\w-]+)", content_text))
        final_content = ping_prefix if (ping_prefix and not body_has_mention) else None

        # Serialize ping+message for this channel to avoid interleaving with other subs
        lock = self._get_channel_lock(channel.id)
        async with lock:
            # send ping first if needed
            if final_content:
                try:
                    logger.info(f"[Follow] Sending ping to {channel} for {ident}: {final_content}")
                    await channel.send(content=final_content)
                except Exception:
                    logger.exception(f"[Follow] Failed to send ping message to {channel}")

            # send the plain message with the link and template replacements
            try:
                # check bot perms before sending
                try:
                    bot_member = guild.me
                    perms = channel.permissions_for(bot_member) if bot_member else channel.permissions_for(guild.get_member(self.bot.user.id))
                except Exception:
                    logger.exception("[Follow] Failed to check bot perms")

                # guard against empty content
                if not content_text or not str(content_text).strip():
                    logger.info(f"[Follow] Skipping send: content_text empty for {ident} (vid={vid_norm})")
                else:
                    logger.info(f"[Follow] Sending YouTube post to {channel} for {ident}: vid={vid_norm} title={title}")
                    await channel.send(content=content_text)
                    # update last_seen after successful post (store id-only)
                    if vid_norm:
                        sub['last_seen'] = vid_norm
                    save_followings(self.followings)
                    logger.info(f"[Follow] Posted new YouTube video for {ident} to {channel} (vid={vid_norm} url={video_url})")
            except Exception:
                logger.exception(f"[Follow] Failed to post to channel {sub.get('post_channel')}")

        # end lock

    def _get_channel_lock(self, channel_id: int) -> asyncio.Lock:
        # create or return an asyncio.Lock for the given channel id
        try:
            cid = int(channel_id)
        except Exception:
            cid = channel_id
        lock = self._channel_locks.get(cid)
        if not lock:
            lock = asyncio.Lock()
            self._channel_locks[cid] = lock
        return lock

    def _extract_video_id(self, s: str) -> str | None:
        """Extract a YouTube video id from a full URL or return the id if already provided.

        Returns None if no id is found. Handles patterns like:
        - https://youtu.be/VIDEOID
        - https://www.youtube.com/watch?v=VIDEOID
        - /watch?v=VIDEOID&...
        - plain VIDEOID
        """
        if not s:
            return None
        try:
            txt = str(s).strip()
            # common patterns
            m = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})', txt)
            if m:
                return m.group(1)
            # try last path segment if it's a URL
            if '/' in txt:
                parts = txt.rstrip('/').split('/')
                last = parts[-1]
                if re.fullmatch(r'[A-Za-z0-9_-]{6,}', last):
                    return last
            # if it's already just an id
            if re.fullmatch(r'[A-Za-z0-9_-]{6,}', txt):
                return txt
        except Exception:
            pass
        return None

    async def _get_twitch_token(self, client_id, client_secret):
        now = time.time()
        if self._twitch_token and now < self._twitch_token_expiry:
            return self._twitch_token

        token_url = 'https://id.twitch.tv/oauth2/token'
        params = {'client_id': client_id, 'client_secret': client_secret, 'grant_type': 'client_credentials'}
        try:
            async with self.session.post(token_url, params=params, timeout=30) as r:
                if r.status != 200:
                    logger.warning(f"[Follow] Twitch token request failed: {r.status}")
                    return None
                data = await r.json()
        except Exception:
            logger.exception("[Follow] Exception while requesting twitch token")
            return None

        token = data.get('access_token')
        expires = data.get('expires_in', 3600)
        if token:
            self._twitch_token = token
            self._twitch_token_expiry = now + expires - 60
            return token
        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(Follow(bot))
