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
        # Twitch token cache
        self._twitch_token = None
        self._twitch_token_expiry = 0.0
        # background worker
        self.worker_task = bot.loop.create_task(self.worker())

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
        await interaction.response.defer(thinking=True)

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
                    display_link = f'https://twitch.tv/{identifier.rstrip('/')}'
        except Exception:
            display_link = identifier

        # Validate that the target (YouTube/Twitch) exists before saving and try to fetch thumbnail
        thumb = None
        try:
            if platform.lower() == 'youtube':
                # Build feed URL similar to check_youtube
                if identifier.startswith('http'):
                    if 'channel/' in identifier:
                        channel_part = identifier.split('channel/')[-1].split('/')[0]
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_part}"
                    elif 'user/' in identifier:
                        user_part = identifier.split('user/')[-1].split('/')[0]
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?user={user_part}"
                    else:
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={identifier}"
                else:
                    if identifier.startswith('UC'):
                        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={identifier}"
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
                choices = '\n'.join([f"{hashlib.sha1(s.get('id','').encode('utf-8')).hexdigest()[:8]} — {s.get('id')}" for s in matches])
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
                await interaction.response.defer(thinking=True)
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
                    display_link = f'https://twitch.tv/{ident.rstrip('/')}'
        else:
            display_link = sub_id

        debug_command("removefollow", interaction.user, guild=interaction.guild, channel=interaction.channel, target=display_link)
        await interaction.response.defer(thinking=True)
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

        debug_command("followlist", interaction.user, guild=interaction.guild, channel=interaction.channel)
        await interaction.response.defer(thinking=True)
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

    @app_commands.command(name="follow_force", description="(DEBUG) Force-post the latest entry for a subscription (bypasses last_seen). Admin/debug use only.")
    @app_commands.describe(sub_id="Subscription id (short or full) to force-post")
    async def follow_force(self, interaction: Interaction, sub_id: str):
        # restricted: only server admins or bot owner should use this; we keep it for testing
        await interaction.response.defer(thinking=True, ephemeral=True)
        import hashlib

        guild_id = str(interaction.guild.id)
        subs = self.followings.get(guild_id, [])

        # resolve short id
        found = None
        if sub_id and len(sub_id) == 8 and all(c in '0123456789abcdef' for c in sub_id.lower()):
            matches = [s for s in subs if hashlib.sha1(s.get('id','').encode('utf-8')).hexdigest().startswith(sub_id.lower())]
            if len(matches) == 1:
                found = matches[0]
        if not found:
            found = next((s for s in subs if s.get('id') == sub_id or s.get('identifier') == sub_id), None)

        if not found:
            await interaction.followup.send(f"❌ Subscription `{sub_id}` not found for this server.", ephemeral=True)
            return

        # Only allow guild admins or the bot owner to run this
        is_admin = interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.followup.send("❌ You do not have permission to use this debug command.", ephemeral=True)
            return

        # call check_youtube with force=True when platform is youtube
        try:
            if found.get('platform') == 'youtube':
                await self.check_youtube(found, guild_id, force=True)
                await interaction.followup.send(f"✅ Forced check executed for subscription `{found.get('id')}`.", ephemeral=True)
            else:
                await interaction.followup.send("❌ This debug command currently only supports YouTube subscriptions.", ephemeral=True)
        except Exception:
            logger.exception("[Follow] follow_force failed")
            await interaction.followup.send("❌ Forced check failed; see logs.", ephemeral=True)

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
                            if sub.get("platform") == "youtube":
                                await self.check_youtube(sub, guild_id)
                            elif sub.get("platform") == "twitch":
                                await self.check_twitch(sub, guild_id)
                        except Exception:
                            logger.exception(f"[Follow] Error checking {sub.get('id')}")
                tasks.append(_run())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def check_youtube(self, sub, guild_id, force: bool = False):
        # support channel id or user or full URL
        ident = sub.get("identifier")
        # minimal per-check logging: we'll log feed fetch and the final outcome
        if ident.startswith("http"):
            # try to extract channel_id or user param
            if "channel/" in ident:
                channel_part = ident.split("channel/")[-1].split("/")[0]
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_part}"
            elif "user/" in ident:
                user_part = ident.split("user/")[-1].split("/")[0]
                feed_url = f"https://www.youtube.com/feeds/videos.xml?user={user_part}"
            else:
                # fallback: attempt to use as channel_id
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ident}"
        else:
            # if looks like UC... treat as channel id, else treat as user
            if ident.startswith("UC"):
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ident}"
            else:
                feed_url = f"https://www.youtube.com/feeds/videos.xml?user={ident}"
        # log feed url for diagnostics
        try:
            logger.debug(f"[Follow] YouTube feed URL for {ident}: {feed_url}")
        except Exception:
            pass
        # RSS-only: fetch feed with retries/backoff
        vid = None
        title = None
        video_url = None
        # fetch feed with retries/backoff
        # Some servers (YouTube) may respond differently depending on User-Agent; provide a common UA
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; jengbot/1.0)'}
        text = await self._fetch_text(feed_url, headers=headers)
        if text:
            try:
                logger.debug(f"[Follow] Fetched feed for {ident}: {len(text)} bytes; preview: {text[:400]}")
            except Exception:
                pass
        if not text:
            logger.debug(f"[Follow] Skipping YouTube check: failed to fetch feed for {ident} ({feed_url})")
            return
        # parse XML
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            logger.exception(f"[Follow] Failed to parse XML for {feed_url}")
            logger.debug(f"[Follow] Raw feed content (truncated): {text[:2000]}")
            return
        # namespace handling (atom + youtube)
        ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
        # Find first entry
        entry = root.find('atom:entry', ns)
        if entry is None:
            # no videos
            return
        # Extract video id robustly: prefer yt:videoId, fallback to link href (v= or last path segment)
        try:
            video_id_elem = entry.find('yt:videoId', ns)
            if video_id_elem is not None and (video_id_elem.text and video_id_elem.text.strip()):
                vid = video_id_elem.text.strip()
            else:
                # try link href patterns
                link = entry.find('atom:link', ns)
                if link is not None:
                    href = link.attrib.get('href', '')
                    # common patterns: https://www.youtube.com/watch?v=VIDEOID or https://youtu.be/VIDEOID
                    if 'v=' in href:
                        vid = href.split('v=')[-1].split('&')[0]
                    else:
                        # try last path segment
                        parts = href.rstrip('/').split('/')
                        if parts:
                            vid = parts[-1]
                else:
                    # as a last resort, try parsing the entry text for youtube shortlinks
                    txt = ET.tostring(entry, encoding='unicode')
                    m = re.search(r'(?:youtu\.be/|v=)([A-Za-z0-9_-]{6,})', txt)
                    if m:
                        vid = m.group(1)

            # published date (if present) for diagnostics
            pub_elem = entry.find('atom:published', ns)
            published = pub_elem.text.strip() if (pub_elem is not None and pub_elem.text) else None

            # title and video_url
            title_elem = entry.find('title')
            title = title_elem.text.strip() if (title_elem is not None and title_elem.text) else None
            video_url = f"https://youtu.be/{vid}" if vid else None
            # keep parsing internal; we'll only log a short summary later to reduce noise
        except Exception:
            logger.exception(f"[Follow] Exception extracting video id/title for {feed_url}")
            logger.debug(f"[Follow] Entry raw XML: {ET.tostring(entry, encoding='unicode')}")
            return

        # Normalize last_seen and vid to strings for reliable comparison
        last = sub.get('last_seen')
        if last is not None:
            try:
                last = str(last).strip()
            except Exception:
                last = last
        vid_norm = str(vid).strip() if vid else None
        if not force and last and vid_norm and last == vid_norm:
            logger.debug(f"[Follow] YouTube no-new: {ident} (video {vid_norm}) already seen")
            return

        # new video — build url and message
        video_url = f"https://youtu.be/{vid}"
        title_elem = entry.find('title')
        title = title_elem.text if title_elem is not None else video_url

        # post to channel
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
        channel = guild.get_channel(sub.get('post_channel'))
        if not channel:
            return
        try:
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
            # If the template doesn't already contain any YouTube link (youtu.be or youtube.com/watch),
            # append the canonical youtu.be link to guarantee a clickable video URL appears.
            contains_youtube_link = bool(re.search(r"(?i)(youtu\.be/|youtube\.com/watch\?|youtube\.com/shorts/|youtube\.com/)", content_text))
            if vid_norm and not contains_youtube_link:
                append_url = f"https://youtu.be/{vid_norm}"
                content_text = content_text + ("\n" if content_text and not content_text.endswith("\n") else "") + append_url

            # detect mentions anywhere in the content_text (handles Discord mention tokens and plain @role/user text)
            body_has_mention = bool(re.search(r"(?i)(<@|<@&|@+everyone|@+here|(?<!\S)@+[\w-]+)", content_text))
            final_content = ping_prefix if (ping_prefix and not body_has_mention) else None

            # send ping first if needed (and template doesn't already include mention)
            if final_content:
                try:
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

                await channel.send(content=content_text)
                # update last_seen after successful post (store normalized vid)
                sub['last_seen'] = vid_norm
                save_followings(self.followings)
                logger.info(f"[Follow] Posted new YouTube video for {ident} to {channel} (vid={vid_norm} url={video_url})")
            except Exception:
                logger.exception(f"[Follow] Failed to post to channel {channel}")
        except Exception:
            logger.exception(f"[Follow] Failed to post to channel {channel}")

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
        # avoid double-pinging if the template already contains a mention anywhere (including plain @role/user)
        # detect mentions, including repeated leading @ like @@everyone
        body_has_mention = bool(re.search(r"(?i)(<@|<@&|@+everyone|@+here|(?<!\S)@+[\w-]+)", content_text))
        logger.debug(f"[Follow] Twitch post ping_role={ping_role_id} body_has_mention={body_has_mention}")

        final_content = ping_prefix if (ping_prefix and not body_has_mention) else None
        # send ping first if needed
        if final_content:
            try:
                await channel.send(content=final_content)
            except Exception:
                logger.exception(f"[Follow] Failed to send ping message to {channel}")

        # send plain message (no embed) with the template replacements
        try:
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
                    if resp.status == 200:
                        return await resp.text()
                    else:
                        logger.debug(f"[Follow] fetch_text non-200 {resp.status} for {url}")
            except Exception as e:
                logger.debug(f"[Follow] fetch_text error on attempt {attempt+1} for {url}: {e}")
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
