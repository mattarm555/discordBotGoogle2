import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction, Embed
import os
import re
import json
import logging
import asyncio
from typing import Optional

logger = logging.getLogger('jeng.tickets')
logger.setLevel(logging.INFO)

TICKETS_FILE = 'tickets.json'
XP_CONFIG = 'xp_config.json'


def load_json(file):
    if os.path.exists(file):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            logger.exception(f'Failed to read {file}')
            return {}
    return {}


def save_json(file, data):
    try:
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        logger.exception(f'Failed to write {file}')


class CloseTicketButton(ui.View):
    def __init__(self, ticket_id: str, owner_id: int, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.ticket_id = ticket_id
        self.owner_id = owner_id

    @ui.button(label='Close Ticket', style=discord.ButtonStyle.danger)
    async def close(self, interaction: Interaction, button: ui.Button):
        # permission check: only owner, guild admins, or configured admin roles
        guild = interaction.guild
        if not guild:
            err = Embed(title='❌ Not in a Server', description='This interaction must be used in a guild.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        # load configured admin roles
        cfg = load_json(XP_CONFIG).get(str(guild.id), {})
        admin_role_ids = {int(r) for r in cfg.get('permissions_roles', [])}

        is_owner = interaction.user.id == self.owner_id
        is_admin = interaction.user.guild_permissions.administrator or any(r.id in admin_role_ids for r in interaction.user.roles)

        if not (is_owner or is_admin):
            err = Embed(title='❌ Permission Denied', description='You do not have permission to close this ticket.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        # delete the ticket channel
        ch = interaction.channel
        if ch:
            info = Embed(title='Closing Ticket', description='Closing ticket...', color=discord.Color.orange())
            await interaction.response.send_message(embed=info, ephemeral=True)
            ticket_data = load_json(TICKETS_FILE)
            guild_tickets = ticket_data.get(str(guild.id), {})
            if self.ticket_id in guild_tickets:
                guild_tickets.pop(self.ticket_id, None)
                ticket_data[str(guild.id)] = guild_tickets
                save_json(TICKETS_FILE, ticket_data)
                # also update in-memory Tickets cog if present
                try:
                    tickets_cog = interaction.client.get_cog('Tickets')
                    if tickets_cog and hasattr(tickets_cog, 'tickets'):
                        tickets_cog.tickets.get(str(guild.id), {}).pop(self.ticket_id, None)
                except Exception:
                    logger.exception('[Tickets] Failed to update in-memory ticket store')
            try:
                await ch.delete(reason=f'Ticket {self.ticket_id} closed by {interaction.user}')
            except Exception:
                logger.exception('[Tickets] Failed to delete ticket channel')
        else:
            err = Embed(title='❌ Error', description='Could not determine ticket channel.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tickets = load_json(TICKETS_FILE)

    def _next_ticket_id(self, guild_id: int) -> str:
        guild_str = str(guild_id)
        guild_tickets = self.tickets.get(guild_str, {})
        # find next numeric id
        i = 1
        while str(i) in guild_tickets:
            i += 1
        return str(i)

    @app_commands.command(name='ticket', description='Open a private ticket channel for support. Provide a brief subject.')
    @app_commands.describe(subject='Short subject for your ticket')
    async def ticket(self, interaction: Interaction, subject: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        if not guild:
            err = Embed(title='❌ Not in a Server', description='This command must be used in a server.', color=discord.Color.red())
            await interaction.followup.send(embed=err, ephemeral=True)
            return

        # compute ticket id and channel name
        ticket_id = self._next_ticket_id(guild.id)
        # create a sanitized channel name based on the user's display name
        raw_name = interaction.user.display_name or interaction.user.name
        # lowercase, replace non-alphanum with hyphens, collapse multiple hyphens
        safe = re.sub(r'[^a-z0-9]+', '-', raw_name.lower())
        safe = re.sub(r'-{2,}', '-', safe).strip('-')
        if not safe:
            safe = f'user-{interaction.user.id}'
        # prefix with parchment emoji for clarity (no space/hyphen after emoji)
        base_chan = f"📜{safe}-ticket"
        # ensure unique channel name — append ticket id if duplicate exists
        chan_name = base_chan
        if discord.utils.get(guild.text_channels, name=chan_name):
            chan_name = f"{base_chan}-{ticket_id}"

        # load configured admin roles
        cfg = load_json(XP_CONFIG).get(str(guild.id), {})
        admin_role_ids = [int(r) for r in cfg.get('permissions_roles', [])]

        # build overwrites: deny @everyone read, allow ticket owner read/send, allow admins read/send
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        for rid in admin_role_ids:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # always allow guild administrators
        # Determine which category to create the ticket in.
        # Priority: per-guild default in XP_CONFIG -> fallbacks (Support/system/first)
        cfg = load_json(XP_CONFIG).get(str(guild.id), {})
        default_cat_id = cfg.get('ticket_default_category')
        category = None
        if default_cat_id:
            try:
                default_cat_id = int(default_cat_id)
                category = guild.get_channel(default_cat_id)
            except Exception:
                category = None

        if category is None:
            # find a place to create the channel: prefer a Category named "Support".
            # If none, try to use the category of the system channel or the first text channel (if they have a category).
            category = discord.utils.get(guild.categories, name='Support')
            if category is None:
                # try system channel's category
                sys_ch = guild.system_channel
                if sys_ch and getattr(sys_ch, 'category', None):
                    category = sys_ch.category
                else:
                    # try first text channel's category
                    if guild.text_channels:
                        first = guild.text_channels[0]
                        if getattr(first, 'category', None):
                            category = first.category
                        else:
                            category = None
                    else:
                        category = None

        try:
            ch = await guild.create_text_channel(chan_name, overwrites=overwrites, category=category, reason=f'Ticket {ticket_id} created by {interaction.user}')
        except Exception:
            logger.exception('[Tickets] Failed to create ticket channel')
            err = Embed(title='❌ Failed to Create Channel', description='Failed to create ticket channel. Check my permissions.', color=discord.Color.red())
            await interaction.followup.send(embed=err, ephemeral=True)
            return

        # try to move the ticket channel to the top of its category (or top of guild if no category)
        try:
            # position=0 moves it to the top among siblings; if in a category this is relative to that category
            await ch.edit(position=0)
        except Exception:
            # don't break the flow if we can't move it (missing permissions etc.)
            logger.exception('[Tickets] Failed to move ticket channel to top')

        # persist ticket
        guild_tickets = self.tickets.setdefault(str(guild.id), {})
        guild_tickets[ticket_id] = {
            'owner': interaction.user.id,
            'channel': ch.id,
            'subject': subject
        }
        save_json(TICKETS_FILE, self.tickets)

        # send initial embed with close button
        # Use the user's name in the title instead of a numeric ticket counter
        user_title = f"{interaction.user.display_name}'s ticket: {subject}"
        embed = Embed(title=user_title, description='Thanks for submitting a ticket! A staff member will be with you as soon as possible.', color=discord.Color.blurple())
        view = CloseTicketButton(ticket_id, interaction.user.id)
        try:
            # pinging the ticket opener is an allowed exception: include their mention along with the embed
            await ch.send(content=f'{interaction.user.mention}', embed=embed, view=view)
        except Exception:
            logger.exception('[Tickets] Failed to send initial ticket message')

        # send ephemeral embed to the ticket author with the channel link
        user_embed = Embed(title='Ticket Submitted', description=f'Thanks for submitting a ticket. You can access your ticket here: {ch.mention}', color=discord.Color.green())
        try:
            await interaction.followup.send(embed=user_embed, ephemeral=True)
        except Exception:
            # fallback to a plain message if embed fails for any reason (necessary fallback)
            await interaction.followup.send(content=f'Thanks for submitting a ticket. You can access your ticket here: {ch.mention}', ephemeral=True)

    # The closeticket app command has been removed. Ticket closure is handled via the Close Ticket button
    # to keep UI-based workflow simple. If you want a slash command again later, we can reintroduce it.

    @app_commands.command(name='ticketlocation', description='(Admin) Set the default category for new tickets in this server.')
    @app_commands.describe(category='Category to use by default for new tickets (leave empty to clear)')
    async def ticketlocation(self, interaction: Interaction, category: Optional[discord.CategoryChannel] = None):
        # permission check: only admins
        if not interaction.user.guild_permissions.administrator:
            err = Embed(title='❌ Permission Denied', description='You must be a server administrator to run this command.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            err = Embed(title='❌ Not in a Server', description='This command must be used in a server.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        cfg = load_json(XP_CONFIG)
        guild_cfg = cfg.get(str(guild.id), {})
        if category is None:
            # clear default
            guild_cfg.pop('ticket_default_category', None)
            cfg[str(guild.id)] = guild_cfg
            save_json(XP_CONFIG, cfg)
            info = Embed(title='Default Cleared', description='Cleared default ticket category.', color=discord.Color.green())
            await interaction.response.send_message(embed=info, ephemeral=True)
            return

        # ensure category belongs to guild
        if getattr(category, 'guild', None) is None or category.guild.id != guild.id:
            err = Embed(title='❌ Invalid Category', description='That category is not in this server.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        # If it's already set to this category, inform the admin instead of re-saving
        if guild_cfg.get('ticket_default_category') == category.id:
            info = Embed(title='No Change', description=f'The default ticket category is already set to {category.name}.', color=discord.Color.yellow())
            await interaction.response.send_message(embed=info, ephemeral=True)
            return

        guild_cfg['ticket_default_category'] = category.id
        cfg[str(guild.id)] = guild_cfg
        save_json(XP_CONFIG, cfg)
        info = Embed(title='Default Set', description=f'Set default ticket category to {category.name}.', color=discord.Color.green())
        await interaction.response.send_message(embed=info, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
