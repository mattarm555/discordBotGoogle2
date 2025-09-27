import discord
from discord.ext import commands
from discord import app_commands, Interaction
import os
import json
import logging
import hashlib
from typing import Optional
import random

logger = logging.getLogger('jeng.reactionroles')
logger.setLevel(logging.INFO)

REACTION_FILE = 'reaction_roles.json'

COLOR_EMOJIS = [
    '⬜', '⚪', '⚫', '⬛', '❤️', '🟥', '💛', '🟫', '🟩', '💚', '🌊', '🔷', '💙', '🔵', '💖'
]

# 15 color names and hex codes (from user's list)
COLOR_PALETTE = [
    ("White", "#FFFFFF"),
    ("Silver", "#C0C0C0"),
    ("Gray", "#808080"),
    ("Black", "#000000"),
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
        with open(REACTION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
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
    @app_commands.describe(count='Number of color roles to create (1-15)', base_name='Base name for the roles')
    async def create_roles(self, interaction: Interaction, count: int, base_name: Optional[str] = 'Color'):
        await interaction.response.defer(thinking=True)
        # permission check
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.followup.send('❌ You do not have permission to use this command.', ephemeral=True)
            return

        if count < 1 or count > 15:
            await interaction.followup.send('❌ Count must be between 1 and 15.', ephemeral=True)
            return

        guild = interaction.guild
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            await interaction.followup.send('❌ Could not determine bot member in this guild.', ephemeral=True)
            return

        # check manage_roles permission
        if not guild.me.guild_permissions.manage_roles:
            await interaction.followup.send('❌ I need the Manage Roles permission to create roles.', ephemeral=True)
            return

        # determine the top role position of the bot
        bot_top_pos = bot_member.top_role.position
        # pick a random subset of colors and emojis so repeated creations vary
        created = []
        try:
            color_choices = random.sample(COLOR_PALETTE, k=count)
            emoji_choices = random.sample(COLOR_EMOJIS, k=count)
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

            # persist this role set as a config
            cfg_id = self._make_config_id(guild.id, base_name)
            cfg = {
                'id': cfg_id,
                'base_name': base_name,
                # store role id and corresponding hex from the chosen colors
                'roles': [{'id': r.id, 'hex': color_choices[idx][1]} for idx, r in enumerate(created)],
                'emojis': emoji_choices
            }
            self.configs.setdefault(str(guild.id), []).append(cfg)
            save_reaction_configs(self.configs)

            # reply with mapping (embed)
            embed = discord.Embed(title='✅ Reaction Roles Created', color=discord.Color.blurple())
            embed.add_field(name='Config ID', value=f'`{cfg_id}`', inline=False)
            for e, r in zip(cfg['emojis'], created):
                embed.add_field(name=f'{e} — {r.name}', value=f'Role ID: {r.id}', inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            logger.exception('[ReactionRoles] Failed to create roles')
            embed = discord.Embed(title='❌ Failed to create roles', description='Check my permissions and role hierarchy.', color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name='reactionroles_post', description='Post a reaction-roles message for a previously created role set')
    @app_commands.describe(config_id='Config ID from reactionroles_create', channel='Channel to post in', message='Message to post')
    async def post_message(self, interaction: Interaction, config_id: str, channel: discord.TextChannel, message: str):
        await interaction.response.defer(thinking=True)
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.followup.send('❌ You do not have permission to use this command.', ephemeral=True)
            return

        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        cfg = next((c for c in guild_cfgs if c.get('id') == config_id), None)
        if not cfg:
            embed = discord.Embed(title='❌ Config Not Found', description='Config ID not found for this server.', color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ensure roles still exist (support stored role entries as either int or {'id':..})
        roles = []
        for rid_entry in cfg.get('roles', []):
            if isinstance(rid_entry, dict):
                rid = rid_entry.get('id')
            else:
                # legacy stored as int
                rid = int(rid_entry)
            r = interaction.guild.get_role(rid)
            if not r:
                embed = discord.Embed(title='❌ Role Missing', description=f'Role with ID {rid} no longer exists. Aborting.', color=discord.Color.red())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            roles.append(r)

        emojis = cfg.get('emojis', [])
        # send message and add reactions
        try:
            # build emoji->role mapping first (support legacy int entries)
            emoji_map = {}
            for e, rid_entry in zip(emojis, cfg.get('roles', [])):
                if isinstance(rid_entry, dict):
                    rid = rid_entry.get('id')
                else:
                    rid = int(rid_entry)
                emoji_map[e] = rid

            # send the user's message inside a single embed and include the mapping in the same embed
            main_embed = discord.Embed(description=message, color=discord.Color.blurple())
            # add mapping fields into the same embed so users see emoji -> role mapping in one place
            for emoji, role_id in emoji_map.items():
                role = interaction.guild.get_role(role_id)
                if not role:
                    continue
                # find hex if available
                hexcode = None
                for rid_entry in cfg.get('roles', []):
                    if isinstance(rid_entry, dict) and rid_entry.get('id') == role.id:
                        hexcode = rid_entry.get('hex')
                        break
                value = f"{role.mention} — {role.name}"
                if hexcode:
                    value += f" ({hexcode})"
                main_embed.add_field(name=str(emoji), value=value, inline=False)

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
            embed.add_field(name='Message ID', value=str(sent.id))
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            logger.exception('[ReactionRoles] Failed to post reaction roles message')
            embed = discord.Embed(title='❌ Failed to post message', description='Check my permissions in the channel.', color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name='reactionroles_remove', description='Remove a previously created color role set (deletes roles)')
    @app_commands.describe(config_id='Config ID from reactionroles_create')
    async def remove_roles(self, interaction: Interaction, config_id: str):
        await interaction.response.defer(thinking=True)
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            embed = discord.Embed(title='❌ Permission Denied', description='You do not have permission to use this command.', color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
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
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Delete the roles created by this config
        failed = []
        for rid_entry in cfg.get('roles', []):
            if isinstance(rid_entry, dict):
                rid = rid_entry.get('id')
            else:
                rid = int(rid_entry)
            role = interaction.guild.get_role(rid)
            if role:
                try:
                    await role.delete(reason=f'ReactionRoles removal by {interaction.user}')
                except Exception:
                    logger.exception(f'[ReactionRoles] Failed to delete role {rid}')
                    failed.append(rid)

        # remove config
        try:
            if cfg_index is not None:
                guild_cfgs.pop(cfg_index)
            self.configs[str(interaction.guild.id)] = guild_cfgs
            save_reaction_configs(self.configs)
        except Exception:
            logger.exception('[ReactionRoles] Failed to remove config')

        if failed:
            embed = discord.Embed(title='⚠️ Partial Failure', description=f'Failed to delete roles: {failed}', color=discord.Color.orange())
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(title='✅ Removed', description=f'Removed roles for config `{config_id}`', color=discord.Color.green())
            await interaction.followup.send(embed=embed, ephemeral=True)

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
