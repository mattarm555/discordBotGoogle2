import discord
from discord.ext import commands
from discord import app_commands, Interaction
import os
import json
import logging
import hashlib
from typing import Optional
import random
from utils.debug import debug_command

logger = logging.getLogger('jeng.reactionroles')
logger.setLevel(logging.INFO)

REACTION_FILE = 'reaction_roles.json'

COLOR_EMOJIS = [
    '⬜',  # White
    '🟧',  # Orange
    '▫️',  # Sand (small pale square)
    '⬛',  # Black
    '🟥',  # Red
    '🍷',  # Maroon (wine glass)
    '🟨',  # Yellow
    '🌿',  # Olive (leaf)
    '🟩',  # Lime
    '💚',  # Green
    '🌊',  # Aqua
    '🔹',  # Teal-ish diamond
    '💙',  # Blue
    '🔵',  # Navy (blue circle)
    '💖',  # Pink
]

# 15 color names and hex codes (from user's list)
COLOR_PALETTE = [
    ("White", "#FFFFFF"),
    ("Orange", "#FF8C00"),
    ("Sand", "#EDC9AF"),
    ("Black", "#020202"),
    ("Red", "#FF0000"),
    ("Maroon", "#800000"),
    ("Yellow", "#FFFF00"),
    ("Olive", "#808000"),
    ("Lime", "#00FF00"),
    ("Green", "#008000"),
    ("Aqua", "#00FFFF"),
    ("Teal", "#008080"),
    ("Blue", "#0000FF"),
    ("Navy", "#000080"),
    ("Pink", "#FF00FF"),
]


def load_reaction_configs():
    if os.path.exists(REACTION_FILE):
        try:
            with open(REACTION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            # file is empty or corrupted; log and return empty config map
            logger.exception('[ReactionRoles] Failed to parse reaction_roles.json; starting with empty configs')
            try:
                # attempt to move the bad file aside
                os.replace(REACTION_FILE, REACTION_FILE + '.bak')
            except Exception:
                pass
            return {}
    return {}


def save_reaction_configs(data):
    with open(REACTION_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


class ReactionRoles(commands.Cog):
    """Create color roles and post reaction-role messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.configs = load_reaction_configs()  # guild_id -> list of configs

    async def cog_unload(self):
        pass

    def _make_config_id(self, guild_id: int, base_name: str) -> str:
        h = hashlib.sha1(f"{guild_id}:{base_name}:{os.urandom(8)}".encode('utf-8')).hexdigest()
        return h[:8]

    @app_commands.command(name='reactionroles_create', description='Create 1-15 color roles under the bot\'s top role')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(count='Number of color roles to create (1-15)', base_name='Base name for the roles')
    async def create_roles(self, interaction: Interaction, count: int, base_name: Optional[str] = 'Color'):
        # Defer immediately (public response) so we can edit it later.
        await interaction.response.defer(thinking=True, ephemeral=False)
        debug_command('reactionroles_create', interaction.user, guild=interaction.guild, count=count, base_name=base_name)
        # permission check
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            # edit the original (deferred) ephemeral response with an error
            await interaction.edit_original_response(content='❌ You do not have permission to use this command.')
            return

        if count < 1 or count > 15:
            await interaction.edit_original_response(content='❌ Count must be between 1 and 15.')
            return

        guild = interaction.guild
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            await interaction.edit_original_response(content='❌ Could not determine bot member in this guild.')
            return

        # check manage_roles permission
        if not guild.me.guild_permissions.manage_roles:
            await interaction.edit_original_response(content='❌ I need the Manage Roles permission to create roles.')
            return

        # determine the top role position of the bot
        bot_top_pos = bot_member.top_role.position
        # pick a random subset of colors while preserving the universal emoji->color mapping
        created = []
        try:
            # sample indices so emojis remain tied to their matching colors
            indices = random.sample(range(len(COLOR_PALETTE)), k=count)
            color_choices = [COLOR_PALETTE[i] for i in indices]
            emoji_choices = [COLOR_EMOJIS[i] for i in indices]
            for idx, (color_name, hexcode) in enumerate(color_choices):
                name = f"{color_name}"
                # parse hex to int for discord.Color
                try:
                    v = int(hexcode.lstrip('#'), 16)
                    colour = discord.Color(v)
                except Exception:
                    colour = discord.Color.default()
                role = await guild.create_role(name=name, colour=colour, reason=f'Reaction roles created by {interaction.user}')
                created.append(role)

            # attempt to move roles to just under the bot's top role
            # Build a dict mapping Role -> new_position as required by discord.py
            start_pos = max(0, bot_top_pos - 1)
            positions = {}
            for idx, role in enumerate(created):
                positions[role] = start_pos - idx
            try:
                await guild.edit_role_positions(positions=positions)
            except Exception:
                # best-effort; ignore failures but log
                logger.exception('[ReactionRoles] Failed to reorder roles')

            # persist this role set as a config. store choices as paired entries
            cfg_id = self._make_config_id(guild.id, base_name)
            cfg = {
                'id': cfg_id,
                'base_name': base_name,
                # choices is a list of {'emoji', 'id', 'hex', 'name'} so emoji/color/role stay together
                'choices': [
                    {
                        'emoji': emoji_choices[idx],
                        'id': r.id,
                        'hex': color_choices[idx][1],
                        'name': color_choices[idx][0]
                    }
                    for idx, r in enumerate(created)
                ]
            }
            self.configs.setdefault(str(guild.id), []).append(cfg)
            save_reaction_configs(self.configs)

            # reply with mapping (embed) arranged in 3 columns to reduce vertical scrolling
            embed = discord.Embed(title='✅ Reaction Roles Created', color=discord.Color.blurple())
            embed.add_field(name='Config ID', value=f'`{cfg_id}`', inline=False)
            # build rows of up to 3 inline fields
            row = []
            for choice in cfg['choices']:
                role = guild.get_role(choice['id'])
                if not role:
                    continue
                row.append((f"{choice['emoji']} — {role.name}", '\u200b'))
                if len(row) == 3:
                    for name, val in row:
                        embed.add_field(name=name, value=val, inline=True)
                    row = []
            # flush remaining
            if row:
                # pad to 3 so columns align visually
                while len(row) < 3:
                    row.append(('\u200b', '\u200b'))
                for name, val in row:
                    embed.add_field(name=name, value=val, inline=True)
            # replace the deferred response with the success embed
            await interaction.edit_original_response(embed=embed)
        except Exception:
            logger.exception('[ReactionRoles] Failed to create roles')
            embed = discord.Embed(title='❌ Failed to create roles', description='Check my permissions and role hierarchy.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='reactionroles_post', description='Post a reaction-roles message for a previously created role set')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(config_id='Config ID from reactionroles_create', channel='Channel to post in', message='Message to post', title='Optional title for the posted embed')
    async def post_message(self, interaction: Interaction, config_id: str, channel: discord.TextChannel, message: str, title: Optional[str] = None):
        # Defer immediately (public response) so we can edit it later.
        await interaction.response.defer(thinking=True, ephemeral=False)
        debug_command('reactionroles_post', interaction.user, guild=interaction.guild, channel=channel, config_id=config_id)
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.edit_original_response(content='❌ You do not have permission to use this command.')
            return

        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        cfg = next((c for c in guild_cfgs if c.get('id') == config_id), None)
        if not cfg:
            embed = discord.Embed(title='❌ Config Not Found', description='Config ID not found for this server.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

        # support new 'choices' format, fall back to legacy 'roles'/'emojis'
        choices = cfg.get('choices')
        if not choices:
            # legacy: rebuild choices from roles + emojis
            roles_list = cfg.get('roles', [])
            emojis = cfg.get('emojis', [])
            choices = []
            for idx, rid_entry in enumerate(roles_list):
                if isinstance(rid_entry, dict):
                    rid = rid_entry.get('id')
                    hexv = rid_entry.get('hex')
                else:
                    rid = int(rid_entry)
                    hexv = None
                emoji = emojis[idx] if idx < len(emojis) else None
                choices.append({'emoji': emoji, 'id': rid, 'hex': hexv, 'name': None})
        # send message and add reactions
        try:
            # build emoji->role mapping from choices list (preserves pairing)
            emoji_map = {c['emoji']: c['id'] for c in choices if c.get('emoji')}

            # send the user's message inside a single embed and include the mapping in the same embed
            # include title if provided
            if title:
                main_embed = discord.Embed(title=title, description=message, color=discord.Color.blurple())
            else:
                main_embed = discord.Embed(description=message, color=discord.Color.blurple())
            # add mapping fields into the same embed so users see emoji -> role mapping in one place
            # arrange into 3 columns (inline fields) so the message is compact
            row = []
            for c in choices:
                emoji = c.get('emoji')
                role_id = c.get('id')
                role = interaction.guild.get_role(role_id)
                if not role or not emoji:
                    continue
                row.append((f"{emoji} — {role.name}", '\u200b'))
                if len(row) == 3:
                    for name, val in row:
                        main_embed.add_field(name=name, value=val, inline=True)
                    row = []
            if row:
                while len(row) < 3:
                    row.append(('\u200b', '\u200b'))
                for name, val in row:
                    main_embed.add_field(name=name, value=val, inline=True)

            sent = await channel.send(embed=main_embed)

            # add reactions after sending
            for e in emoji_map.keys():
                try:
                    await sent.add_reaction(e)
                except Exception:
                    logger.exception(f'[ReactionRoles] Failed to add reaction {e} to message')

            # persist mapping: message_id -> guild, channel, emoji->role
            mapping = {
                'guild_id': interaction.guild.id,
                'channel_id': channel.id,
                'message_id': sent.id,
                'emoji_map': emoji_map
            }
            self.configs.setdefault(str(interaction.guild.id), []).append({'posted': mapping})
            save_reaction_configs(self.configs)
            embed = discord.Embed(title='✅ Reaction Roles Posted', description=f'Embedded message posted in {channel.mention}', color=discord.Color.green())
            # edit the original deferred ephemeral response with confirmation
            await interaction.edit_original_response(embed=embed)
        except Exception:
            logger.exception('[ReactionRoles] Failed to post reaction roles message')
            embed = discord.Embed(title='❌ Failed to post message', description='Check my permissions in the channel.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='reactionroles_remove', description='Remove a previously created color role set (deletes roles)')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(config_id='Config ID from reactionroles_create')
    async def remove_roles(self, interaction: Interaction, config_id: str):
        # Defer immediately (public response) so we can edit it later.
        await interaction.response.defer(thinking=True, ephemeral=False)
        debug_command('reactionroles_remove', interaction.user, guild=interaction.guild, config_id=config_id)
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            embed = discord.Embed(title='❌ Permission Denied', description='You do not have permission to use this command.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        cfg_index = None
        cfg = None
        for idx, c in enumerate(guild_cfgs):
            if c.get('id') == config_id:
                cfg_index = idx
                cfg = c
                break

        if cfg is None:
            embed = discord.Embed(title='❌ Config Not Found', description='Config ID not found for this server.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    

        # Delete the roles created by this config
        failed = []
        # collect role ids from either legacy 'roles' or new 'choices'
        removed_role_ids = set()
        # new format: choices list with entries having 'id'
        for choice in cfg.get('choices', []):
            rid = choice.get('id') if isinstance(choice, dict) else None
            if rid:
                removed_role_ids.add(int(rid))
        # legacy format: roles may be list of ids or dicts
        for rid_entry in cfg.get('roles', []):
            if isinstance(rid_entry, dict):
                rid = rid_entry.get('id')
            else:
                try:
                    rid = int(rid_entry)
                except Exception:
                    rid = None
            if rid:
                removed_role_ids.add(int(rid))

        failed = []
        for rid in list(removed_role_ids):
            role = interaction.guild.get_role(rid)
            if role:
                try:
                    await role.delete(reason=f'ReactionRoles removal by {interaction.user}')
                except Exception:
                    logger.exception(f'[ReactionRoles] Failed to delete role {rid}')
                    failed.append(rid)

        # remove config and any posted mappings that referenced the removed roles
        try:
            if cfg_index is not None:
                guild_cfgs.pop(cfg_index)

            # remove posted entries that reference the removed role ids
            to_remove = []
            for idx, entry in enumerate(list(guild_cfgs)):
                if entry.get('posted'):
                    mapping = entry['posted']
                    emoji_map = mapping.get('emoji_map', {})
                    # if any role id in emoji_map matches removed roles, remove this posted mapping
                    mapped_role_ids = {int(v) for v in emoji_map.values() if isinstance(v, int) or (isinstance(v, str) and v.isdigit())}
                    if removed_role_ids & mapped_role_ids:
                        # attempt to delete the posted message from the channel (best-effort)
                        try:
                            ch = self.bot.get_channel(mapping.get('channel_id'))
                            if ch:
                                msg = await ch.fetch_message(mapping.get('message_id'))
                                try:
                                    await msg.delete()
                                except Exception:
                                    # ignore delete failures
                                    logger.exception('[ReactionRoles] Failed to delete posted reaction roles message')
                        except Exception:
                            # ignore fetch/delete failures and continue to remove mapping
                            logger.exception('[ReactionRoles] Error while attempting to remove posted mapping')
                        to_remove.append(entry)

            for entry in to_remove:
                try:
                    guild_cfgs.remove(entry)
                except ValueError:
                    pass

            self.configs[str(interaction.guild.id)] = guild_cfgs
            save_reaction_configs(self.configs)
        except Exception:
            logger.exception('[ReactionRoles] Failed to remove config')

        if failed:
            embed = discord.Embed(title='⚠️ Partial Failure', description=f'Failed to delete roles: {failed}', color=discord.Color.orange())
            await interaction.edit_original_response(embed=embed)
        else:
            embed = discord.Embed(title='✅ Removed', description=f'Removed roles for config `{config_id}`', color=discord.Color.green())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='reaction_list', description='List reaction-role configs and posted mappings for this server')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def reaction_list(self, interaction: Interaction):
        # Defer immediately (public response)
        await interaction.response.defer(thinking=True, ephemeral=False)
        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        if not guild_cfgs:
            embed = discord.Embed(title='No Reaction Roles', description='No reaction role configs found for this server.', color=discord.Color.orange())
            await interaction.edit_original_response(embed=embed)
            return

        embed = discord.Embed(title='Reaction Role Configs', color=discord.Color.blurple())
        for c in guild_cfgs:
            # created configs
            if c.get('id'):
                cid = c.get('id')
                base = c.get('base_name') or ''
                # build a compact representation of choices
                choices = c.get('choices') or []
                if choices:
                    parts = []
                    for ch in choices:
                        emoji = ch.get('emoji') or ''
                        name = ch.get('name') or ''
                        # if name missing, try to resolve via guild
                        try:
                            rid = ch.get('id')
                            role = interaction.guild.get_role(rid) if rid else None
                            if role:
                                name = role.name
                        except Exception:
                            pass
                        parts.append(f"{emoji} {name}" if name else f"{emoji}")
                    # join with bullets, truncate if too long
                    summary = ' · '.join(parts)
                    if len(summary) > 500:
                        summary = summary[:497] + '...'
                else:
                    summary = '(no choices)'
                embed.add_field(name=f'Config {cid} — {base}', value=summary, inline=False)

            # posted mappings
            if c.get('posted'):
                posted = c['posted']
                ch = self.bot.get_channel(posted.get('channel_id'))
                chname = ch.mention if ch else f"Channel ID {posted.get('channel_id')}"
                # don't show numeric message id
                emoji_map = posted.get('emoji_map', {})
                # show emoji list only
                emojis = ', '.join(list(emoji_map.keys())) if emoji_map else '(no reactions)'
                embed.add_field(name=f'Posted in {chname}', value=f'Reactions: {emojis}', inline=False)

        await interaction.edit_original_response(embed=embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # handle role assignment
        try:
            guild_id = str(payload.guild_id)
            cfgs = self.configs.get(guild_id, [])
            # find a posted mapping containing this message
            mapping = None
            for c in cfgs:
                if c.get('posted') and c['posted'].get('message_id') == payload.message_id:
                    mapping = c['posted']
                    break
            if not mapping:
                return

            emoji = str(payload.emoji)
            role_id = mapping['emoji_map'].get(emoji)
            if not role_id:
                return
            guild = self.bot.get_guild(int(mapping['guild_id']))
            if not guild:
                return
            member = guild.get_member(payload.user_id)
            if not member or member.bot:
                return
            role = guild.get_role(role_id)
            if not role:
                return
            await member.add_roles(role, reason='Reaction role added')
        except Exception:
            logger.exception('[ReactionRoles] Error in on_raw_reaction_add')

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # handle role removal when reaction removed
        try:
            guild_id = str(payload.guild_id)
            cfgs = self.configs.get(guild_id, [])
            mapping = None
            for c in cfgs:
                if c.get('posted') and c['posted'].get('message_id') == payload.message_id:
                    mapping = c['posted']
                    break
            if not mapping:
                return
            emoji = str(payload.emoji)
            role_id = mapping['emoji_map'].get(emoji)
            if not role_id:
                return
            guild = self.bot.get_guild(int(mapping['guild_id']))
            if not guild:
                return
            member = guild.get_member(payload.user_id)
            if not member or member.bot:
                return
            role = guild.get_role(role_id)
            if not role:
                return
            await member.remove_roles(role, reason='Reaction role removed')
        except Exception:
            logger.exception('[ReactionRoles] Error in on_raw_reaction_remove')


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
