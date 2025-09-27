import discord
from discord.ext import commands
from discord import app_commands, Interaction
import os
import json
import logging
import hashlib
from typing import Optional

logger = logging.getLogger('jeng.reactionroles')
logger.setLevel(logging.INFO)

REACTION_FILE = 'reaction_roles.json'

COLOR_EMOJIS = [
    '🔴','🟠','🟡','🟢','🔵','🟣','🟤','⚫','⚪','🟥','🟧','🟨','🟩','🟦','🟪'
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
        # create roles
        created = []
        colors = [
            discord.Color.red(), discord.Color.orange(), discord.Color.gold(), discord.Color.green(),
            discord.Color.blue(), discord.Color.purple(), discord.Color.dark_gold(), discord.Color.default(),
            discord.Color.light_grey(), discord.Color.from_rgb(183,28,28), discord.Color.from_rgb(230,81,0),
            discord.Color.from_rgb(255,235,59), discord.Color.from_rgb(139,195,74), discord.Color.from_rgb(3,169,244),
            discord.Color.from_rgb(171,71,188)
        ]
        try:
            for i in range(count):
                name = f"{base_name} {i+1}"
                color = colors[i % len(colors)]
                role = await guild.create_role(name=name, colour=color, reason=f'Reaction roles created by {interaction.user}')
                created.append(role)

            # attempt to move roles to just under the bot's top role
            positions = []
            # we want the highest created role to be just below bot_top_pos - 1, then lower for subsequent
            start_pos = max(0, bot_top_pos - 1)
            for idx, role in enumerate(created):
                positions.append({'id': role.id, 'position': start_pos - idx})
            try:
                await guild.edit_role_positions(positions=positions)
            except Exception:
                # best-effort; ignore failures
                logger.exception('[ReactionRoles] Failed to reorder roles')

            # persist this role set as a config
            cfg_id = self._make_config_id(guild.id, base_name)
            cfg = {
                'id': cfg_id,
                'base_name': base_name,
                'roles': [r.id for r in created],
                'emojis': COLOR_EMOJIS[:len(created)]
            }
            self.configs.setdefault(str(guild.id), []).append(cfg)
            save_reaction_configs(self.configs)

            # reply with mapping
            lines = [f"Config ID: `{cfg_id}`"]
            for e, r in zip(cfg['emojis'], created):
                lines.append(f"{e} — {r.name}")

            await interaction.followup.send('\n'.join(lines), ephemeral=True)
        except Exception:
            logger.exception('[ReactionRoles] Failed to create roles')
            await interaction.followup.send('❌ Failed to create roles; check my permissions and role hierarchy.', ephemeral=True)

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
            await interaction.followup.send('❌ Config ID not found for this server.', ephemeral=True)
            return

        # ensure roles still exist
        roles = []
        for rid in cfg.get('roles', []):
            r = interaction.guild.get_role(rid)
            if not r:
                await interaction.followup.send(f'❌ Role with ID {rid} no longer exists. Aborting.', ephemeral=True)
                return
            roles.append(r)

        emojis = cfg.get('emojis', [])
        # send message and add reactions
        try:
            sent = await channel.send(message)
            for e in emojis:
                try:
                    await sent.add_reaction(e)
                except Exception:
                    logger.exception(f'[ReactionRoles] Failed to add reaction {e} to message')

            # persist mapping: message_id -> guild, channel, emoji->role
            mapping = {
                'guild_id': interaction.guild.id,
                'channel_id': channel.id,
                'message_id': sent.id,
                'emoji_map': {e: rid for e, rid in zip(emojis, cfg.get('roles', []))}
            }
            self.configs.setdefault(str(interaction.guild.id), []).append({'posted': mapping})
            save_reaction_configs(self.configs)

            await interaction.followup.send('✅ Reaction roles message posted.', ephemeral=True)
        except Exception:
            logger.exception('[ReactionRoles] Failed to post reaction roles message')
            await interaction.followup.send('❌ Failed to post message; check my permissions in the channel.', ephemeral=True)

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
