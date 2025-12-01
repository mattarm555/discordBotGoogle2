"""Moderator cog

Provides slash commands for server moderation: /mute, /kick, /ban and management of
auto-ban and auto-mute word lists. Stores lists as JSON files at the repository root:
- word_banlist.json
- word_mutelist.json

Required bot permissions (varies by command):
- manage_roles (to create/apply Muted role)
- kick_members
- ban_members
- manage_guild (to manage lists)
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time
import json
from pathlib import Path
import os
from typing import Optional
import re

# --- Color Codes (match other cogs) ---
RESET = "\033[0m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"


def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name if guild else 'DM'}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")


def automod_log(action: str, message: discord.Message, matched_phrase: str = None, duration: Optional[int] = None, reason: Optional[str] = None):
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    guild = message.guild.name if message.guild else 'DM'
    author = f"{message.author} ({message.author.id})"
    content = (message.content or '').replace('\n', '\\n')[:800]
    dur = format_duration(duration) if duration else 'N/A'
    print(f"{GREEN}[AUTOMOD]{RESET} {ts} - {action} in {BLUE}{guild}{RESET} - author={YELLOW}{author}{RESET} phrase={CYAN}{matched_phrase}{RESET} duration={dur} reason={reason}")
    print(f"    content: {content}")


ROOT = Path(__file__).resolve().parents[1]
BANLIST_PATH = ROOT / 'word_banlist.json'
MUTELIST_PATH = ROOT / 'word_mutelist.json'
MUTED_SCHEDULE_PATH = ROOT / 'muted_schedule.json'
KICKLIST_PATH = ROOT / 'word_kicklist.json'
XP_CONFIG_PATH = ROOT / 'xp_config.json'


def load_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


def save_json(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


def parse_duration(duration_str: Optional[str]) -> Optional[int]:
    """Parse a duration like '10m', '1h', '30s', '1d' into seconds.
    Returns None if parsing fails or duration_str is falsy.
    """
    if not duration_str:
        return None
    s = duration_str.strip().lower()
    try:
        if s.endswith('s'):
            return int(s[:-1])
        if s.endswith('m'):
            return int(s[:-1]) * 60
        if s.endswith('h'):
            return int(s[:-1]) * 3600
        if s.endswith('d'):
            return int(s[:-1]) * 86400
        # plain number -> seconds
        return int(s)
    except Exception:
        return None


def format_duration(seconds: Optional[int]) -> str:
    """Convert seconds into a compact human string like '1h 5m 3s'."""
    if not seconds or seconds <= 0:
        return 'indefinitely'
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return ' '.join(parts)


class Moderator(commands.Cog):
    """Moderator utilities: mute/kick/ban and word lists for auto-moderation.

    Commands
    - /mute member duration reason notify notify_message
    - /kick member reason notify notify_message
    - /ban member reason notify notify_message
    - /banlist_add, /banlist_remove, /banlist_list
    - /mutelist_add, /mutelist_remove, /mutelist_list

    Notes: Commands check the invoking user's guild permissions. Muting uses a 'Muted' role.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # mapping: (guild_id, user_id) -> {"task": asyncio.Task, "unmute_at": epoch_seconds}
        self._unmute_tasks = {}
        # track guilds where we've applied Muted role channel overwrites to avoid repeating heavy ops
        self._muted_role_initialized = set()
        self.banlist = load_json(BANLIST_PATH, [])
        # mutelist stored as list of dicts: {"phrase":..., "duration":seconds, "reason":...}
        self.mutelist = load_json(MUTELIST_PATH, [])
        # kicklist mirrors banlist but performs a kick instead of an immediate ban
        self.kicklist = load_json(KICKLIST_PATH, [])
        # load persisted mute schedule and reconcile
        self._persisted_mutes = load_json(MUTED_SCHEDULE_PATH, [])
        # compile regex patterns for quick automod checking
        self._compile_all_patterns()
        # Start background reconciliation
        asyncio.create_task(self._reconcile_persisted_mutes())

    def _phrase_to_pattern(self, phrase: str) -> re.Pattern:
        """Convert a stored phrase into a compiled regex that matches whole words
        and allows repetition of the final character. Examples:
        - 'hur' -> r"\bh u r+\b" (escaped properly) so it matches 'hur','hurr','hurrr' but not 'hurt'.
        - multi-word phrases repeat the last token's final char only.
        """
        if not phrase or not isinstance(phrase, str):
            return re.compile(r"^$")
        phrase = phrase.strip()
        # split tokens on whitespace for multi-word phrases
        tokens = phrase.split()
        last = tokens[-1]
        # if last token ends with an alnum character, make it repeatable
        if last and last[-1].isalnum():
            core = re.escape(last[:-1]) if len(last) > 1 else ''
            last_char = re.escape(last[-1])
            last_pattern = f"{core}{last_char}+"
        else:
            last_pattern = re.escape(last)

        if len(tokens) == 1:
            pat = rf"\b{last_pattern}\b"
        else:
            middle = [re.escape(t) for t in tokens[:-1]]
            pat = r"\b" + r"\s+".join(middle + [last_pattern]) + r"\b"

        try:
            return re.compile(pat, re.IGNORECASE)
        except re.error:
            # fallback to a safe substring match escaped
            return re.compile(re.escape(phrase), re.IGNORECASE)

    def _compile_all_patterns(self):
        # augment entries with compiled pattern objects for quick checks
        try:
            # normalize and compile banlist patterns; ensure entries are dicts
            normalized = []
            for e in self.banlist:
                if isinstance(e, dict):
                    entry = dict(e)
                else:
                    entry = {'phrase': str(e), 'reason': None, 'guild': None}
                entry['pattern'] = self._phrase_to_pattern(entry.get('phrase', ''))
                normalized.append(entry)
            self.banlist = normalized

            normalized = []
            for e in self.kicklist:
                if isinstance(e, dict):
                    entry = dict(e)
                else:
                    entry = {'phrase': str(e), 'reason': None, 'guild': None}
                entry['pattern'] = self._phrase_to_pattern(entry.get('phrase', ''))
                normalized.append(entry)
            self.kicklist = normalized

            normalized = []
            for e in self.mutelist:
                if isinstance(e, dict):
                    entry = dict(e)
                else:
                    entry = {'phrase': str(e), 'duration': None, 'reason': None, 'guild': None}
                entry['pattern'] = self._phrase_to_pattern(entry.get('phrase', ''))
                normalized.append(entry)
            self.mutelist = normalized
        except Exception:
            # best-effort; ignore pattern compilation errors
            pass

    def _is_bot_admin(self, member: discord.Member) -> bool:
        """Return True if member is server admin or in the bot-admin roles listed in xp_config.json."""
        try:
            # Check if user is a server administrator
            if member.guild_permissions.administrator:
                return True
            
            # Check if xp_config.json exists
            if not XP_CONFIG_PATH.exists():
                print(f"{YELLOW}[PERM CHECK]{RESET} xp_config.json not found for {member.display_name}")
                return False
            
            # Load and parse config
            try:
                cfg = json.loads(XP_CONFIG_PATH.read_text(encoding='utf-8') or '{}')
            except json.JSONDecodeError as e:
                print(f"{YELLOW}[PERM CHECK]{RESET} Failed to parse xp_config.json: {e}")
                return False
            
            guild_cfg = cfg.get(str(member.guild.id), {})
            perms = guild_cfg.get('permissions_roles', [])
            
            # Debug: print what roles we're checking
            print(f"{CYAN}[PERM CHECK]{RESET} Checking {member.display_name} in {member.guild.name}")
            print(f"{CYAN}[PERM CHECK]{RESET} Configured permission role IDs: {perms}")
            print(f"{CYAN}[PERM CHECK]{RESET} User's role IDs: {[str(r.id) for r in member.roles]}")
            
            # Check if user has any of the permission roles
            for role in member.roles:
                if str(role.id) in perms:
                    print(f"{GREEN}[PERM CHECK]{RESET} ✓ User has permission role: {role.name} ({role.id})")
                    return True
            
            print(f"{YELLOW}[PERM CHECK]{RESET} ✗ User does not have any permission roles")
            return False
            
        except AttributeError as e:
            print(f"{YELLOW}[PERM CHECK]{RESET} AttributeError (member might not be a Member object): {e}")
            return False
        except Exception as e:
            print(f"{YELLOW}[PERM CHECK]{RESET} Unexpected error in _is_bot_admin: {e}")
            return False

    async def _safe_send_dm(self, user: discord.abc.User, embed: discord.Embed):
        try:
            await user.send(embed=embed)
        except Exception:
            # ignore failures to DM
            pass

    async def _perform_unmute_if_needed(self, guild_id: int, user_id: int, notify: bool = True):
        """Remove Muted role from the user if present and cleanup persisted/task entries.

        If notify is True (the default) the bot will send an embedded notice in a guild
        text channel announcing the automatic unmute. When unmuting manually via the
        /unmute command, callers should pass notify=False to avoid duplicate notices.
        """
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return
            member = guild.get_member(int(user_id))
            role = discord.utils.get(guild.roles, name='Muted')
            unmuted = False
            if member and role and role in member.roles:
                try:
                    await member.remove_roles(role, reason='Mute duration expired / manual unmute')
                    unmuted = True
                except Exception:
                    # couldn't remove role (permission or hierarchy)
                    pass
            # If this was an automatic unmute and we actually removed the role, announce it
            if notify and unmuted:
                try:
                    # prefer system channel, otherwise find the first text channel we can send to
                    channel = guild.system_channel
                    gm = getattr(guild, 'me', None) or guild.get_member(self.bot.user.id)
                    can_send = False
                    if channel and gm:
                        try:
                            can_send = channel.permissions_for(gm).send_messages
                        except Exception:
                            can_send = False
                    if not channel or not can_send:
                        channel = None
                        for ch in guild.text_channels:
                            try:
                                if gm and ch.permissions_for(gm).send_messages:
                                    channel = ch
                                    break
                            except Exception:
                                continue
                    # fetch duration and original channel from persisted mutes if available
                    duration_seconds = None
                    source_channel_id = None
                    try:
                        for e in list(self._persisted_mutes):
                            if int(e.get('guild')) == int(guild_id) and int(e.get('user')) == int(user_id):
                                duration_seconds = e.get('duration')
                                source_channel_id = e.get('channel')
                                break
                    except Exception:
                        duration_seconds = None
                        source_channel_id = None

                    # Prefer to announce in the same channel where the mute occurred
                    target_channel = None
                    try:
                        if source_channel_id:
                            try:
                                target_channel = guild.get_channel(int(source_channel_id))
                            except Exception:
                                target_channel = None
                    except Exception:
                        target_channel = None

                    gm = getattr(guild, 'me', None) or guild.get_member(self.bot.user.id)
                    # verify we can send in target_channel
                    can_send = False
                    if target_channel and gm:
                        try:
                            can_send = target_channel.permissions_for(gm).send_messages
                        except Exception:
                            can_send = False

                    # fallback to system channel / first available text channel
                    if not target_channel or not can_send:
                        channel = guild.system_channel
                        can_send = False
                        if channel and gm:
                            try:
                                can_send = channel.permissions_for(gm).send_messages
                            except Exception:
                                can_send = False
                        if not channel or not can_send:
                            channel = None
                            for ch in guild.text_channels:
                                try:
                                    if gm and ch.permissions_for(gm).send_messages:
                                        channel = ch
                                        break
                                except Exception:
                                    continue
                        target_channel = target_channel if (target_channel and can_send) else channel

                    if target_channel:
                        emb = discord.Embed(description=f'✅ {member.mention} has been unmuted.', color=discord.Color.green())
                        dur_text = format_duration(duration_seconds)
                        emb.set_footer(text=f'Muted duration: {dur_text}')
                        try:
                            await target_channel.send(embed=emb)
                        except Exception:
                            # best-effort announcement; ignore failures
                            pass
                except Exception:
                    # best-effort announcement; ignore failures
                    pass
        finally:
            key = (int(guild_id), int(user_id))
            # cancel in-memory task if present
            t = self._unmute_tasks.get(key)
            if t and t.get('task'):
                try:
                    t['task'].cancel()
                except Exception:
                    pass
            self._unmute_tasks.pop(key, None)
            # remove persisted entry
            try:
                self._persisted_mutes = [e for e in self._persisted_mutes if not (int(e.get('guild')) == int(guild_id) and int(e.get('user')) == int(user_id))]
                self._save_persisted_mutes()
            except Exception:
                pass

    def _save_persisted_mutes(self):
        try:
            MUTED_SCHEDULE_PATH.write_text(json.dumps(self._persisted_mutes, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    async def _reconcile_persisted_mutes(self):
        # Recreate unmute tasks for persisted mutes (called at startup)
        entries = list(self._persisted_mutes)
        for entry in entries:
            guild_id = entry.get('guild')
            user_id = entry.get('user')
            unmute_at = entry.get('unmute_at')
            try:
                # If expired, attempt immediate unmute
                if unmute_at <= int(time.time()):
                    await self._perform_unmute_if_needed(int(guild_id), int(user_id), notify=True)
                    # remove from persisted list
                    self._persisted_mutes = [e for e in self._persisted_mutes if not (e.get('guild') == guild_id and e.get('user') == user_id)]
                    self._save_persisted_mutes()
                else:
                    # schedule task
                    key = (int(guild_id), int(user_id))

                    async def _unmute_later(key=key, unmute_at=unmute_at):
                        try:
                            await asyncio.sleep(max(0, unmute_at - int(time.time())))
                            await self._perform_unmute_if_needed(key[0], key[1], notify=True)
                        finally:
                            self._unmute_tasks.pop(key, None)
                            # remove persisted entry
                            self._persisted_mutes = [e for e in self._persisted_mutes if not (int(e.get('guild')) == key[0] and int(e.get('user')) == key[1])]
                            self._save_persisted_mutes()

                    task = asyncio.create_task(_unmute_later())
                    self._unmute_tasks[key] = {"task": task, "unmute_at": unmute_at}
            except Exception:
                # ignore bad entries
                pass

    # -------------------- Helpers --------------------
    async def _ensure_muted_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        role = discord.utils.get(guild.roles, name='Muted')
        created = False
        # Create role if missing
        if not role:
            try:
                # create role with no base permissions; we'll explicitly ensure it cannot send/connect
                role = await guild.create_role(name='Muted', permissions=discord.Permissions.none(), reason='ModeratorCog: create muted role')
                created = True
            except discord.Forbidden:
                return None

        # Make sure role base permissions do not allow sending messages or connecting to voice
        try:
            perms = role.permissions
            # explicitly clear send_messages and connect in the role's base permissions
            perms.update(send_messages=False, connect=False)
            await role.edit(permissions=perms, reason='Ensure Muted role has no send/connect')
        except Exception:
            # ignore if we can't edit the role
            pass

        # Apply serverwide overwrites where possible so the Muted role can't send messages or connect to voice
        # This is potentially expensive on large servers; only do this when the role was just created
        # or when we haven't initialized this guild yet.
        if created or (guild.id not in self._muted_role_initialized):
            for channel in guild.channels:
                try:
                    # Text-based channels
                    if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                        await channel.set_permissions(role, send_messages=False, add_reactions=False, speak=False)
                    # Threads inherit from parent but setting for completeness
                    elif isinstance(channel, discord.Thread):
                        await channel.set_permissions(role, send_messages=False, add_reactions=False)
                    # Voice/Stage channels
                    elif isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                        await channel.set_permissions(role, connect=False, speak=False)
                except Exception:
                    # ignore channels we can't touch
                    pass
            try:
                self._muted_role_initialized.add(guild.id)
            except Exception:
                pass
        return role

    async def _apply_mute(self, member: discord.Member, duration_seconds: Optional[int], reason: Optional[str], source_channel: Optional[int] = None):
        role = await self._ensure_muted_role(member.guild)
        if not role:
            raise discord.Forbidden('Missing permission to create or manage Muted role')
        try:
            await member.add_roles(role, reason=reason or 'Muted by ModeratorCog')
        except discord.Forbidden:
            raise
        if duration_seconds and duration_seconds > 0:
            key = (member.guild.id, member.id)
            unmute_at = int(time.time()) + int(duration_seconds)

            async def _unmute_later(key=key):
                try:
                    await asyncio.sleep(max(0, unmute_at - int(time.time())))
                    await self._perform_unmute_if_needed(key[0], key[1], notify=True)
                finally:
                    self._unmute_tasks.pop(key, None)
                    # remove from persisted list
                    self._persisted_mutes = [e for e in self._persisted_mutes if not (int(e.get('guild')) == key[0] and int(e.get('user')) == key[1])]
                    self._save_persisted_mutes()

            # cancel existing task if present
            old = self._unmute_tasks.get(key)
            if old and old.get('task') and not old['task'].done():
                old['task'].cancel()
            task = asyncio.create_task(_unmute_later())
            self._unmute_tasks[key] = {"task": task, "unmute_at": unmute_at}

                # persist the schedule
            try:
                self._persisted_mutes = [e for e in self._persisted_mutes if not (int(e.get('guild')) == key[0] and int(e.get('user')) == key[1])]
                # store duration and source channel so we can report how long they were muted and where to announce unmute
                # Note: source channel may not be provided for some callers; leave as None in that case
                # use provided source_channel if available
                ch_val = None
                try:
                    if source_channel:
                        ch_val = str(int(source_channel))
                except Exception:
                    ch_val = None
                self._persisted_mutes.append({"guild": str(key[0]), "user": str(key[1]), "unmute_at": unmute_at, "duration": int(duration_seconds) if duration_seconds else None, "channel": ch_val})
                self._save_persisted_mutes()
            except Exception:
                pass

    # -------------------- Commands --------------------
    @app_commands.command(name='mute', description='Mute a member for an optional duration. Duration examples: 10m, 1h, 1d')
    @app_commands.describe(member='Member to mute', duration='Duration (e.g. 10m, 1h). Leave empty for indefinite.', reason='Reason for the mute')
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: Optional[str] = None, reason: Optional[str] = None):
        if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.manage_roles or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to mute members.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('mute', interaction.user, interaction.guild, member=member.display_name, duration=duration, reason=reason)

        await interaction.response.defer(thinking=True)

        secs = parse_duration(duration)
        try:
            await self._apply_mute(member, secs, reason, source_channel=interaction.channel.id if interaction.channel else None)
        except discord.Forbidden:
            emb = discord.Embed(description='❌ I lack permissions to mute that user (role hierarchy or manage_roles).', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)
            return
        except Exception as e:
            emb = discord.Embed(description=f'❌ Failed to mute: {e}', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)
            return

        # Always send a confirmation embed (include reason only if provided)
        length_text = f'{duration}' if duration else 'indefinitely'
        emb = discord.Embed(title='Member muted', color=discord.Color.orange())
        emb.add_field(name='Member', value=f'{member.mention}', inline=True)
        emb.add_field(name='Duration', value=length_text, inline=True)
        if reason:
            emb.add_field(name='Reason', value=reason, inline=False)
        emb.set_footer(text=f'Muted by {interaction.user.display_name}')
        await interaction.followup.send(embed=emb)

    @app_commands.command(name='mutestatus', description='Show mute remaining time for a member')
    @app_commands.describe(member='Member to check (defaults to yourself)')
    async def mutestatus(self, interaction: discord.Interaction, member: discord.Member = None):
        if member is None:
            member = interaction.user
        debug_command('mutestatus', interaction.user, interaction.guild, member=member.display_name)
        key = (interaction.guild.id, member.id)
        entry = self._unmute_tasks.get(key)
        if entry and entry.get('unmute_at'):
            # unmute_at is stored as epoch seconds (time.time()), so compare using the same
            now = int(time.time())
            remaining = int(entry['unmute_at']) - now
            if remaining > 0:
                # format remaining
                m, s = divmod(remaining, 60)
                h, m = divmod(m, 60)
                parts = []
                if h: parts.append(f"{h}h")
                if m: parts.append(f"{m}m")
                parts.append(f"{s}s")
                emb = discord.Embed(title='🔇 Mute status', color=discord.Color.orange())
                emb.add_field(name='Member', value=member.mention)
                emb.add_field(name='Remaining', value=' '.join(parts))
                await interaction.response.send_message(embed=emb)
                return
        # check persisted list (maybe no in-memory task due to restart)
        for e in self._persisted_mutes:
            if int(e.get('guild')) == interaction.guild.id and int(e.get('user')) == member.id:
                remaining = int(e.get('unmute_at')) - int(time.time())
                if remaining > 0:
                    m, s = divmod(remaining, 60)
                    h, m = divmod(m, 60)
                    parts = []
                    if h: parts.append(f"{h}h")
                    if m: parts.append(f"{m}m")
                    parts.append(f"{s}s")
                    emb = discord.Embed(title='🔇 Mute status', color=discord.Color.orange())
                    emb.add_field(name='Member', value=member.mention)
                    emb.add_field(name='Remaining', value=' '.join(parts))
                    await interaction.response.send_message(embed=emb)
                    return
        emb = discord.Embed(title='🔇 Mute status', description='No active mute / indefinite mute', color=discord.Color.blurple())
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name='kick', description='Kick a member from the server')
    @app_commands.describe(member='Member to kick', reason='Reason for the kick')
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = None):
        if not (interaction.user.guild_permissions.kick_members or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to kick members.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('kick', interaction.user, interaction.guild, member=member.display_name, reason=reason)
        await interaction.response.defer(thinking=True)
        # DM the user only if a reason was provided
        if reason:
            try:
                dm_emb = discord.Embed(title='You have been kicked', color=discord.Color.dark_red())
                dm_emb.add_field(name='Server', value=f'{interaction.guild.name}', inline=True)
                dm_emb.add_field(name='Reason', value=reason, inline=False)
                await member.send(embed=dm_emb)
            except Exception:
                pass
        try:
            await member.kick(reason=reason)
            emb = discord.Embed(description=f'✅ {member} has been kicked.', color=discord.Color.green())
            if reason:
                emb.add_field(name='Reason', value=reason, inline=False)
            emb.set_footer(text=f'Kicked by {interaction.user.display_name}')
            await interaction.followup.send(embed=emb)
        except discord.Forbidden:
            emb = discord.Embed(description='❌ I do not have permission to kick that user.', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)
        except Exception as e:
            emb = discord.Embed(description=f'❌ Failed to kick: {e}', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name='ban', description='Ban a member from the server')
    @app_commands.describe(member='Member to ban', reason='Reason for the ban')
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = None):
        if not (interaction.user.guild_permissions.ban_members or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to ban members.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('ban', interaction.user, interaction.guild, member=member.display_name, reason=reason)
        await interaction.response.defer(thinking=True)
        # DM the user only if a reason was provided
        if reason:
            try:
                dm_emb = discord.Embed(title='You have been banned', color=discord.Color.dark_red())
                dm_emb.add_field(name='Server', value=f'{interaction.guild.name}', inline=True)
                dm_emb.add_field(name='Reason', value=reason, inline=False)
                await member.send(embed=dm_emb)
            except Exception:
                pass
        try:
            await member.ban(reason=reason)
            emb = discord.Embed(description=f'✅ {member} has been banned.', color=discord.Color.green())
            if reason:
                emb.add_field(name='Reason', value=reason, inline=False)
            emb.set_footer(text=f'Banned by {interaction.user.display_name}')
            await interaction.followup.send(embed=emb)
        except discord.Forbidden:
            emb = discord.Embed(description='❌ I do not have permission to ban that user.', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)
        except Exception as e:
            emb = discord.Embed(description=f'❌ Failed to ban: {e}', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name='unmute', description='Unmute a member immediately')
    @app_commands.describe(member='Member to unmute')
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        # Permission check: moderators or manage_roles or bot-admins
        if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.manage_roles or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to unmute members.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('unmute', interaction.user, interaction.guild, member=member.display_name)
        await interaction.response.defer(thinking=True)
        try:
            # Check whether the member appears muted: either has the Muted role or is in persisted mutes
            role = discord.utils.get(interaction.guild.roles, name='Muted')
            has_role = (role in member.roles) if (role and member) else False
            in_persist = False
            try:
                for e in self._persisted_mutes:
                    if int(e.get('guild')) == interaction.guild.id and int(e.get('user')) == member.id:
                        in_persist = True
                        break
            except Exception:
                in_persist = False

            if not has_role and not in_persist:
                emb = discord.Embed(title='Not muted', description=f'{member.mention} is not currently muted.', color=discord.Color.blurple())
                emb.set_footer(text=f'Checked by {interaction.user.display_name}')
                await interaction.followup.send(embed=emb)
                return

            await self._perform_unmute_if_needed(interaction.guild.id, member.id, notify=False)
            emb = discord.Embed(description=f'✅ {member.mention} has been unmuted.', color=discord.Color.green())
            emb.set_footer(text=f'Unmuted by {interaction.user.display_name}')
            await interaction.followup.send(embed=emb)
        except Exception as e:
            emb = discord.Embed(description=f'❌ Failed to unmute: {e}', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)

    # -------------------- Word list management --------------------
    @app_commands.command(name='banlist_add', description='Add a phrase to the auto-ban list')
    @app_commands.describe(phrase='Phrase to ban', reason='Optional reason/message to DM when auto-banning')
    async def banlist_add(self, interaction: discord.Interaction, phrase: str, reason: Optional[str] = None):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to manage the banlist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('banlist_add', interaction.user, interaction.guild, phrase=phrase, reason=reason)
        await interaction.response.defer(thinking=True)
        entry = {'phrase': phrase.lower(), 'reason': reason, 'guild': str(interaction.guild.id)}
        # compile pattern for this entry
        try:
            entry['pattern'] = self._phrase_to_pattern(entry['phrase'])
        except Exception:
            entry['pattern'] = re.compile(re.escape(entry['phrase']), re.IGNORECASE)

        if any(e.get('phrase') == entry['phrase'] and (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id)) for e in self.banlist):
            emb = discord.Embed(description='⚠️ That phrase is already in the banlist.', color=discord.Color.orange())
            await interaction.followup.send(embed=emb, ephemeral=True)
            return

        self.banlist.append(entry)
        # persist without compiled patterns
        save_json(BANLIST_PATH, [{'phrase': e.get('phrase'), 'reason': e.get('reason'), 'guild': e.get('guild')} for e in self.banlist])
        emb = discord.Embed(description=f'✅ Added to banlist: "{phrase}"', color=discord.Color.green())
        await interaction.followup.send(embed=emb)

    @app_commands.command(name='banlist_remove', description='Remove a phrase from the auto-ban list')
    async def banlist_remove(self, interaction: discord.Interaction, phrase: str):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to manage the banlist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('banlist_remove', interaction.user, interaction.guild, phrase=phrase)
        await interaction.response.defer(thinking=True)
        phrase_l = phrase.lower()
        before = len(self.banlist)
        self.banlist = [e for e in self.banlist if not (e.get('phrase') == phrase_l and (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id)))]
        save_json(BANLIST_PATH, [{'phrase': e.get('phrase'), 'reason': e.get('reason'), 'guild': e.get('guild')} for e in self.banlist])
        if len(self.banlist) < before:
            emb = discord.Embed(description=f'✅ Removed from banlist: "{phrase}"', color=discord.Color.green())
            await interaction.followup.send(embed=emb)
        else:
            emb = discord.Embed(description='⚠️ Phrase not found in banlist.', color=discord.Color.orange())
            await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name='banlist_list', description='List auto-ban phrases')
    async def banlist_list(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to view the banlist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('banlist_list', interaction.user, interaction.guild)
        await interaction.response.defer(thinking=True)
        if not self.banlist:
            emb = discord.Embed(title='Banlist', description='Banlist is empty.', color=discord.Color.blurple())
            await interaction.followup.send(embed=emb)
            return
        # show only entries for this guild
        lines = [f'- "{e["phrase"]}"' + (f' (reason: {e["reason"]})' if e.get('reason') else '') for e in self.banlist if (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id))]
        emb = discord.Embed(title='Banlist', description='\n'.join(lines), color=discord.Color.blurple())
        await interaction.followup.send(embed=emb)

    @app_commands.command(name='kicklist_add', description='Add a phrase to the auto-kick list')
    @app_commands.describe(phrase='Phrase to kick on', reason='Optional reason/message to DM when auto-kicking')
    async def kicklist_add(self, interaction: discord.Interaction, phrase: str, reason: Optional[str] = None):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to manage the kicklist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('kicklist_add', interaction.user, interaction.guild, phrase=phrase, reason=reason)
        await interaction.response.defer(thinking=True)
        entry = {'phrase': phrase.lower(), 'reason': reason, 'guild': str(interaction.guild.id)}
        try:
            entry['pattern'] = self._phrase_to_pattern(entry['phrase'])
        except Exception:
            entry['pattern'] = re.compile(re.escape(entry['phrase']), re.IGNORECASE)

        if any(e.get('phrase') == entry['phrase'] and (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id)) for e in self.kicklist):
            emb = discord.Embed(description='⚠️ That phrase is already in the kicklist.', color=discord.Color.orange())
            await interaction.followup.send(embed=emb, ephemeral=True)
            return

        self.kicklist.append(entry)
        save_json(KICKLIST_PATH, [{'phrase': e.get('phrase'), 'reason': e.get('reason'), 'guild': e.get('guild')} for e in self.kicklist])
        emb = discord.Embed(description=f'✅ Added to kicklist: "{phrase}"', color=discord.Color.green())
        await interaction.followup.send(embed=emb)

    @app_commands.command(name='kicklist_remove', description='Remove a phrase from the auto-kick list')
    async def kicklist_remove(self, interaction: discord.Interaction, phrase: str):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to manage the kicklist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('kicklist_remove', interaction.user, interaction.guild, phrase=phrase)
        await interaction.response.defer(thinking=True)
        phrase_l = phrase.lower()
        before = len(self.kicklist)
        self.kicklist = [e for e in self.kicklist if not (e.get('phrase') == phrase_l and (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id)))]
        save_json(KICKLIST_PATH, [{'phrase': e.get('phrase'), 'reason': e.get('reason'), 'guild': e.get('guild')} for e in self.kicklist])
        if len(self.kicklist) < before:
            emb = discord.Embed(description=f'✅ Removed from kicklist: "{phrase}"', color=discord.Color.green())
            await interaction.followup.send(embed=emb)
        else:
            emb = discord.Embed(description='⚠️ Phrase not found in kicklist.', color=discord.Color.orange())
            await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name='kicklist_list', description='List auto-kick phrases')
    async def kicklist_list(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to view the kicklist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('kicklist_list', interaction.user, interaction.guild)
        await interaction.response.defer(thinking=True)
        if not self.kicklist:
            emb = discord.Embed(title='Kicklist', description='Kicklist is empty.', color=discord.Color.blurple())
            await interaction.followup.send(embed=emb)
            return
        lines = [f'- "{e["phrase"]}"' + (f' (reason: {e["reason"]})' if e.get('reason') else '') for e in self.kicklist if (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id))]
        emb = discord.Embed(title='Kicklist', description='\n'.join(lines), color=discord.Color.blurple())
        await interaction.followup.send(embed=emb)

    @app_commands.command(name='mutelist_add', description='Add phrase to auto-mute list')
    @app_commands.describe(phrase='Phrase to mute on', duration='Mute duration like 10m, 1h', reason='Reason to include in DM when muting')
    async def mutelist_add(self, interaction: discord.Interaction, phrase: str, duration: str, reason: Optional[str] = None):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to manage the mutelist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('mutelist_add', interaction.user, interaction.guild, phrase=phrase, duration=duration, reason=reason)
        await interaction.response.defer(thinking=True)
        secs = parse_duration(duration)
        if secs is None:
            emb = discord.Embed(description='❌ Invalid duration. Examples: 10m, 1h, 1d, 30s', color=discord.Color.red())
            await interaction.followup.send(embed=emb, ephemeral=True)
            return
        entry = {'phrase': phrase.lower(), 'duration': secs, 'reason': reason, 'guild': str(interaction.guild.id)}
        try:
            entry['pattern'] = self._phrase_to_pattern(entry['phrase'])
        except Exception:
            entry['pattern'] = re.compile(re.escape(entry['phrase']), re.IGNORECASE)

        if any(e.get('phrase') == entry['phrase'] and (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id)) for e in self.mutelist):
            emb = discord.Embed(description='⚠️ That phrase is already in the mutelist.', color=discord.Color.orange())
            await interaction.followup.send(embed=emb, ephemeral=True)
            return

        self.mutelist.append(entry)
        save_json(MUTELIST_PATH, [{'phrase': e.get('phrase'), 'duration': e.get('duration'), 'reason': e.get('reason'), 'guild': e.get('guild')} for e in self.mutelist])
        emb = discord.Embed(description=f'✅ Added to mutelist: "{phrase}" (duration {duration})', color=discord.Color.green())
        await interaction.followup.send(embed=emb)

    @app_commands.command(name='mutelist_remove', description='Remove phrase from auto-mute list')
    async def mutelist_remove(self, interaction: discord.Interaction, phrase: str):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to manage the mutelist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('mutelist_remove', interaction.user, interaction.guild, phrase=phrase)
        await interaction.response.defer(thinking=True)
        phrase_l = phrase.lower()
        before = len(self.mutelist)
        self.mutelist = [e for e in self.mutelist if not (e.get('phrase') == phrase_l and (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id)))]
        save_json(MUTELIST_PATH, [{'phrase': e.get('phrase'), 'duration': e.get('duration'), 'reason': e.get('reason'), 'guild': e.get('guild')} for e in self.mutelist])
        if len(self.mutelist) < before:
            emb = discord.Embed(description=f'✅ Removed from mutelist: "{phrase}"', color=discord.Color.green())
            await interaction.followup.send(embed=emb)
        else:
            emb = discord.Embed(description='⚠️ Phrase not found in mutelist.', color=discord.Color.orange())
            await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name='mutelist_list', description='List auto-mute phrases')
    async def mutelist_list(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.manage_guild or self._is_bot_admin(interaction.user)):
            emb = discord.Embed(description='❌ You do not have permission to view the mutelist.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        debug_command('mutelist_list', interaction.user, interaction.guild)
        await interaction.response.defer(thinking=True)
        if not self.mutelist:
            emb = discord.Embed(title='Mutelist', description='Mutelist is empty.', color=discord.Color.blurple())
            await interaction.followup.send(embed=emb)
            return
        lines = [f'- "{e["phrase"]}" -> {e["duration"]}s' + (f' (reason: {e["reason"]})' if e.get('reason') else '') for e in self.mutelist if (e.get('guild') is None or str(e.get('guild')) == str(interaction.guild.id))]
        emb = discord.Embed(title='Mutelist', description='\n'.join(lines), color=discord.Color.blurple())
        await interaction.followup.send(embed=emb)

    # -------------------- Automod listener --------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        content = (message.content or '')
        # check banlist using compiled patterns when available
        for entry in list(self.banlist):
            pat = entry.get('pattern')
            try:
                matched = bool(pat.search(content)) if pat is not None else (entry.get('phrase', '') in content.lower())
            except Exception:
                matched = entry.get('phrase', '') in content.lower()
            if matched:
                # attempt to ban - delete message immediately so chat cleans up fast
                try:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    reason = entry.get('reason')
                    # DM in background so we don't block
                    try:
                        if reason:
                            dm_emb = discord.Embed(title='You have been banned', color=discord.Color.dark_red())
                            dm_emb.add_field(name='Server', value=f'{message.guild.name}', inline=True)
                            dm_emb.add_field(name='Reason', value=reason, inline=False)
                            asyncio.create_task(self._safe_send_dm(message.author, dm_emb))
                    except Exception:
                        pass
                    # debug log
                    try:
                        automod_log('BAN', message, matched_phrase=entry.get('phrase'), duration=None, reason=reason)
                    except Exception:
                        pass
                    await message.guild.ban(message.author, reason=reason)
                    ban_emb = discord.Embed(description=f'🔨 {message.author.mention} was banned for using a banned phrase.', color=discord.Color.red())
                    await message.channel.send(embed=ban_emb)
                except Exception:
                    # can't ban; try to delete message
                    try:
                        await message.delete()
                        warn_emb = discord.Embed(description=f'⚠️ Deleted message from {message.author.mention} containing a banned phrase.', color=discord.Color.orange())
                        await message.channel.send(embed=warn_emb)
                    except Exception:
                        pass
                return

        # check kicklist using compiled patterns when available
        for entry in list(self.kicklist):
            pat = entry.get('pattern')
            try:
                matched = bool(pat.search(content)) if pat is not None else (entry.get('phrase', '') in content.lower())
            except Exception:
                matched = entry.get('phrase', '') in content.lower()
            if matched:
                # attempt to kick - delete message immediately for responsiveness
                try:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    reason = entry.get('reason')
                    # DM in background so it doesn't block
                    try:
                        if reason:
                            dm_emb = discord.Embed(title='You have been kicked', color=discord.Color.dark_red())
                            dm_emb.add_field(name='Server', value=f'{message.guild.name}', inline=True)
                            dm_emb.add_field(name='Reason', value=reason, inline=False)
                            asyncio.create_task(self._safe_send_dm(message.author, dm_emb))
                    except Exception:
                        pass
                    # debug log
                    try:
                        automod_log('KICK', message, matched_phrase=entry.get('phrase'), duration=None, reason=reason)
                    except Exception:
                        pass
                    await message.guild.kick(message.author, reason=reason)
                    kick_emb = discord.Embed(description=f'👢 {message.author.mention} was kicked for using a kicklisted phrase.', color=discord.Color.orange())
                    await message.channel.send(embed=kick_emb)
                except Exception:
                    # can't kick; try to delete message
                    try:
                        await message.delete()
                        warn_emb = discord.Embed(description=f'⚠️ Deleted message from {message.author.mention} containing a kicklisted phrase.', color=discord.Color.orange())
                        await message.channel.send(embed=warn_emb)
                    except Exception:
                        pass
                return

        # check mutelist using compiled patterns when available
        for entry in list(self.mutelist):
            pat = entry.get('pattern')
            try:
                matched = bool(pat.search(content)) if pat is not None else (entry.get('phrase', '') in content.lower())
            except Exception:
                matched = entry.get('phrase', '') in content.lower()
            if matched:
                # Delete message immediately for responsiveness, then handle mute in background
                try:
                    try:
                        await message.delete()
                    except Exception:
                        pass

                    async def _do_mute_and_announce(entry_local, author, channel):
                        try:
                            duration = entry_local.get('duration')
                            reason = entry_local.get('reason')
                            # log the mute intention before applying
                            try:
                                automod_log('MUTE', message, matched_phrase=entry_local.get('phrase'), duration=duration, reason=reason)
                            except Exception:
                                pass
                            await self._apply_mute(author, duration, reason, source_channel=channel.id if channel else None)
                            # only send the detailed embed when reason exists
                            if reason:
                                try:
                                    length_text = format_duration(duration) if duration else 'indefinitely'
                                    emb = discord.Embed(title='Member muted', color=discord.Color.orange())
                                    emb.add_field(name='Member', value=f'{author.mention}', inline=True)
                                    emb.add_field(name='Duration', value=length_text, inline=True)
                                    emb.add_field(name='Reason', value=reason, inline=False)
                                    emb.set_footer(text=f'Muted by {message.guild.me.display_name if message.guild.me else self.bot.user.name}')
                                    await channel.send(embed=emb)
                                except Exception:
                                    pass
                        except Exception:
                            # If mute failed, nothing else to do
                            pass

                    # bind current values into the task to avoid closure capture of loop variables
                    asyncio.create_task(_do_mute_and_announce(entry, message.author, message.channel))
                except Exception:
                    # If delete failed, try to mute anyway (best-effort)
                    try:
                        await self._apply_mute(message.author, entry.get('duration'), entry.get('reason'), source_channel=message.channel.id if message.channel else None)
                    except Exception:
                        pass
                return


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderator(bot))
