import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction, Embed
import random
from datetime import datetime
import pytz
from utils.debug import debug_command
import asyncio
import logging
import json
from pathlib import Path
from typing import Optional

# --- Color Codes ---
RESET = "\033[0m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Update debug_command to include guild
def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class HelpPaginator(ui.View):
    def __init__(self, pages):
        super().__init__(timeout=60)
        self.pages = pages
        self.index = 0

    def get_embed(self):
        return self.pages[self.index]

    @ui.button(label="⬅️ Prev", style=discord.ButtonStyle.blurple)
    async def prev_page(self, interaction: Interaction, button: ui.Button):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="➡️ Next", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: Interaction, button: ui.Button):
        if self.index < len(self.pages) - 1:
            self.index += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

class Misc(commands.Cog):
    logger = logging.getLogger('jeng.misc')
    logger.setLevel(logging.INFO)

    def __init__(self, bot):
        self.bot = bot
    @app_commands.command(name="listpermissions", description="List all roles with bot admin permissions for this server.")
    async def listpermissions(self, interaction: Interaction):
        CONFIG_FILE = "xp_config.json"
        def load_json(file):
            import os, json
            if os.path.exists(file):
                with open(file, "r") as f:
                    return json.load(f)
            return {}
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild.id)
        perms = config.get(guild_id, {}).get("permissions_roles", [])
        if not perms:
            err = Embed(title='No Roles', description='No roles have bot admin permissions.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
            return
        role_mentions = []
        for role_id in perms:
            role = interaction.guild.get_role(int(role_id))
            if role:
                role_mentions.append(role.mention)
        if role_mentions:
            info = Embed(title='Roles with Bot Admin Permissions', description=", ".join(role_mentions), color=discord.Color.green())
            await interaction.response.send_message(embed=info, ephemeral=True)
        else:
            err = Embed(title='No Valid Roles', description='No valid roles found in bot admin permissions.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
    
    @app_commands.command(name="removepermissions", description="Remove a role from bot admin permissions for this server.")
    @app_commands.describe(role="Role to remove from bot admin permissions")
    @app_commands.checks.has_permissions(administrator=True)
    async def removepermissions(self, interaction: Interaction, role: discord.Role):
        CONFIG_FILE = "xp_config.json"
        def load_json(file):
            import os, json
            if os.path.exists(file):
                with open(file, "r") as f:
                    return json.load(f)
            return {}
        def save_json(file, data):
            import json
            with open(file, "w") as f:
                json.dump(data, f, indent=4)
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild.id)
        perms = config.setdefault(guild_id, {}).setdefault("permissions_roles", [])
        if str(role.id) in perms:
            perms.remove(str(role.id))
            save_json(CONFIG_FILE, config)
            info = Embed(title='Role Removed', description=f'Role {role.mention} removed from bot admin permissions.', color=discord.Color.green())
            await interaction.response.send_message(embed=info, ephemeral=True)
        else:
            err = Embed(title='Not a Bot Admin', description=f'Role {role.mention} is not a bot admin.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
    
    @app_commands.command(name="setpermissions", description="Set a role as bot admin for this server.")
    @app_commands.describe(role="Role to grant bot admin permissions")
    @app_commands.checks.has_permissions(administrator=True)
    async def setpermissions(self, interaction: Interaction, role: discord.Role):
        # Load config
        CONFIG_FILE = "xp_config.json"
        def load_json(file):
            import os, json
            if os.path.exists(file):
                with open(file, "r") as f:
                    return json.load(f)
            return {}
        def save_json(file, data):
            import json
            with open(file, "w") as f:
                json.dump(data, f, indent=4)
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild.id)
        perms = config.setdefault(guild_id, {}).setdefault("permissions_roles", [])
        if str(role.id) not in perms:
            perms.append(str(role.id))
            save_json(CONFIG_FILE, config)
            info = Embed(title='Role Added', description=f'Role {role.mention} added as bot admin.', color=discord.Color.green())
            await interaction.response.send_message(embed=info, ephemeral=True)
        else:
            err = Embed(title='Already a Bot Admin', description=f'Role {role.mention} is already a bot admin.', color=discord.Color.yellow())
            await interaction.response.send_message(embed=err, ephemeral=True)

    # /champ and /spam commands removed per request

    @app_commands.command(name="snipe", description="Retrieves the last deleted message in the current channel.")
    async def snipe(self, interaction: Interaction):
        debug_command("snipe", interaction.user, interaction.guild)

        sniped_messages = self.bot.sniped_messages
        snipe_data = sniped_messages.get(interaction.channel.id)

        if not snipe_data:
            await interaction.response.send_message(embed=Embed(title="❌ Nothing to Snipe", description="No message to snipe here.", color=discord.Color.red()), ephemeral=True)
            return

        embed = Embed(
            title="Get sniped gang",
            description=snipe_data["content"],
            color=discord.Color.dark_red(),
            timestamp=snipe_data["time"]
        )
        embed.set_author(name=snipe_data["author"].display_name, icon_url=snipe_data["author"].avatar.url if snipe_data["author"].avatar else None)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Displays a list of available commands.")
    async def help(self, interaction: Interaction):
        debug_command("help", interaction.user, interaction.guild)
        pages: list[Embed] = []

        # Music (includes DJ commands)
        music_embed = Embed(title="🎵 Music Commands", color=discord.Color.blue())
        music_embed.add_field(name="/play <url>", value="Plays a song or playlist from the given URL.", inline=False)
        music_embed.add_field(name="/queue", value="Shows the current music queue.", inline=False)
        music_embed.add_field(name="/skip", value="Skips the current song.", inline=False)
        music_embed.add_field(name="/stop", value="Pauses the music.", inline=False)
        music_embed.add_field(name="/start", value="Resumes paused music.", inline=False)
        music_embed.add_field(name="/leave", value="Clears the queue and makes the bot leave the voice channel.", inline=False)
        music_embed.add_field(name="/playplaylist <name>", value="Play a previously saved playlist.", inline=False)
        music_embed.add_field(name="/saveplaylist <name> <link>", value="Save a playlist link under a custom name.", inline=False)
        music_embed.add_field(name="/removeplaylist <name>", value="Delete a saved playlist.", inline=False)
        music_embed.add_field(name="/listplaylists", value="List saved playlists for this server.", inline=False)
        music_embed.add_field(name="/queueshuffle", value="Shuffles the current queue.", inline=False)
        music_embed.add_field(name="/np", value="Shows the currently playing song.", inline=False)
        music_embed.add_field(name="/setdj <role>", value="Assign or update the DJ role (Manage Guild).", inline=False)
        music_embed.add_field(name="/cleardj", value="Remove the configured DJ role restriction.", inline=False)
        music_embed.add_field(name="/djinfo", value="Show the current DJ role configuration.", inline=False)
        music_embed.add_field(name="/refresh_cookies", value="Owner only: Run refresh_cookies.py and sync cookies for YouTube playback.", inline=False)
        pages.append(music_embed)

        # Gambling
        gambling_embed = Embed(title="🎰 Gambling", color=discord.Color.gold())
        gambling_embed.add_field(name="/daily", value="Claim your daily coin reward (24h cooldown).", inline=False)
        gambling_embed.add_field(name="/balance [user]", value="Check your balance or another user's balance.", inline=False)
        gambling_embed.add_field(name="/balancetop", value="Show the top balances in this server.", inline=False)
        gambling_embed.add_field(name="/pay <user> <amount>", value="Pay another user some of your coins.", inline=False)
        gambling_embed.add_field(name="/blackjack <bet>", value="Play a hand of blackjack (1–10000 bet).", inline=False)
        gambling_embed.add_field(name="/blackjack_set_cooldown <duration>", value="Admin: Set cooldown between blackjack hands (min 10s). E.g., 10s, 30s, 1m.", inline=False)
        gambling_embed.add_field(name="/slots <bet> [lines]", value="Spin the slots (1–10000 bet, 1–5 lines).", inline=False)
        gambling_embed.add_field(name="/slots_set_cooldown <duration>", value="Admin: Set cooldown between slot spins (min 3s). E.g., 3s, 10s, 1m.", inline=False)
        gambling_embed.add_field(name="/slotstats", value="View your slot stats and session delta.", inline=False)
        gambling_embed.add_field(name="/slotresetsession", value="Reset your slot session baseline.", inline=False)
        gambling_embed.add_field(name="/slotsim [spins] [wager] [lines]", value="Owner only: Simulate slot spins to estimate RTP (no balance impact).", inline=False)
        gambling_embed.add_field(name="/work", value="Work a random job to earn coins (per-server cooldown).", inline=False)
        gambling_embed.add_field(name="/setworkcooldown <duration>", value="Admin: Set /work cooldown (e.g., 15m, 2h, 1d).", inline=False)
        gambling_embed.add_field(name="/coin_reset", value="Admin: Reset all coin balances for this server.", inline=False)
        gambling_embed.add_field(name="/shop [page]", value="Browse passive income items (shows what you own).", inline=False)
        gambling_embed.add_field(name="/buy <item_name>", value="Buy a passive item by exact name (see /shop).", inline=False)
        gambling_embed.add_field(name="/inventory", value="See the passive items you own and their income.", inline=False)
        gambling_embed.add_field(name="/shop_set_interval <duration>", value="Admin: Set how often items pay (e.g., 15m, 1h, 2h30m).", inline=False)
        gambling_embed.add_field(name="/item_add <name> <cost> <income> <description>", value="Admin: Add a server-specific shop item.", inline=False)
        gambling_embed.add_field(name="/item_delete <name>", value="Admin: Delete a server-specific shop item.", inline=False)
        gambling_embed.add_field(name="/item_list", value="List this server's custom shop items.", inline=False)
        gambling_embed.add_field(name="/econ_wipe", value="Admin: Wipe all users' coins and owned items for this server.", inline=False)
        pages.append(gambling_embed)

        # XP
        xp_embed = Embed(title="📈 XP System", color=discord.Color.green())
        xp_embed.add_field(name="/level", value="Shows your XP level and server rank.", inline=False)
        xp_embed.add_field(name="/xpleaderboard [page]", value="Shows the leaders in XP in this server.", inline=False)
        xp_embed.add_field(name="/xpset <amount>", value="Sets the amount of XP gained per message.", inline=False)
        xp_embed.add_field(name="/xpblock <channel>", value="Blocks XP in the given channel.", inline=False)
        xp_embed.add_field(name="/xpunblock <channel>", value="Unblocks XP in the given channel.", inline=False)
        xp_embed.add_field(name="/xpconfig", value="Shows the current XP settings.", inline=False)
        xp_embed.add_field(name="/setlevelrole <level> <role>", value="Set which role is given at a specific level.", inline=False)
        xp_embed.add_field(name="/resetxp", value="Admin: Reset all XP and levels for this server.", inline=False)
        xp_embed.add_field(name="/levelup_silence <channel>", value="Admin: Toggle muting level-up messages in a channel.", inline=False)
        xp_embed.add_field(name="/levelup_channel [channel]", value="Admin: Set or clear a dedicated channel for level-up messages.", inline=False)
        pages.append(xp_embed)

        # Misc
        misc_embed = Embed(title="😂 Miscellaneous", color=discord.Color.purple())
        misc_embed.add_field(name="/snipe", value="Retrieves the last deleted message in the current channel.", inline=False)
        misc_embed.add_field(name="/bot_say", value="Admin: Make the bot send a message (with embed options).", inline=False)
        pages.append(misc_embed)

        # Community
        community_embed = Embed(title="📊 Community Tools", color=discord.Color.orange())
        community_embed.add_field(name="/poll", value="Create a custom emoji poll with 2–6 options and a closing timer.", inline=False)
        community_embed.add_field(name="/event", value="Create an interactive RSVP event.", inline=False)
        community_embed.add_field(name="/welcomeconfig", value="Show current welcome message configuration.", inline=False)
        community_embed.add_field(name="/setwelcome", value="Configure the welcome message settings.", inline=False)
        community_embed.add_field(name="/follow <platform> <identifier> <post_channel>", value="Follow a YouTube or Twitch channel and post new content to a channel.", inline=False)
        community_embed.add_field(name="/removefollow <sub_id>", value="Remove a follow subscription by ID (from /followlist).", inline=False)
        community_embed.add_field(name="/followlist", value="List follow subscriptions for this server.", inline=False)
        community_embed.add_field(name="/ticket <subject>", value="Open a private ticket channel for support.", inline=False)
        community_embed.add_field(name="/ticketlocation <category>", value="Set the default category for new tickets.", inline=False)
        community_embed.add_field(name="/reactionroles_create <count> <interactive> [base_name]", value="Create reaction roles (max 50).", inline=False)
        community_embed.add_field(name="/reactionroles_post <config_id> <channel> <message>", value="Post a reaction-roles message.", inline=False)
        community_embed.add_field(name="/reactionroles_remove <config_id>", value="Remove a color role set.", inline=False)
        community_embed.add_field(name="/reaction_list", value="List reaction configurations.", inline=False)
        community_embed.add_field(name="/counting <name> [chances]", value="Create a counting channel.", inline=False)
        community_embed.add_field(name="/delete_counting <channel>", value="Delete a counting channel.", inline=False)
        pages.append(community_embed)

        # Moderating
        moderating_embed = Embed(title="🛡️ Moderating", color=discord.Color.red())
        moderating_embed.add_field(name="/mute <member> [duration] [reason]", value="Mute a member (e.g. 10m, 1h, 1d).", inline=False)
        moderating_embed.add_field(name="/mutestatus [member]", value="Show remaining mute time.", inline=False)
        moderating_embed.add_field(name="/unmute <member>", value="Unmute immediately.", inline=False)
        moderating_embed.add_field(name="/kick <member> [reason]", value="Kick a member.", inline=False)
        moderating_embed.add_field(name="/ban <member> [reason]", value="Ban a member.", inline=False)
        moderating_embed.add_field(name="/banlist_add <phrase> [reason]", value="Add auto-ban phrase.", inline=False)
        moderating_embed.add_field(name="/banlist_remove <phrase>", value="Remove auto-ban phrase.", inline=False)
        moderating_embed.add_field(name="/banlist_list", value="List auto-ban phrases.", inline=False)
        moderating_embed.add_field(name="/mutelist_add <phrase> <duration> [reason]", value="Add auto-mute phrase.", inline=False)
        moderating_embed.add_field(name="/mutelist_remove <phrase>", value="Remove auto-mute phrase.", inline=False)
        moderating_embed.add_field(name="/mutelist_list", value="List auto-mute phrases.", inline=False)
        moderating_embed.add_field(name="/kicklist_add <phrase> [reason]", value="Add auto-kick phrase.", inline=False)
        moderating_embed.add_field(name="/kicklist_remove <phrase>", value="Remove auto-kick phrase.", inline=False)
        moderating_embed.add_field(name="/kicklist_list", value="List auto-kick phrases.", inline=False)
        moderating_embed.add_field(name="/help_message <message>", value="DM the bot owner feedback.", inline=False)
        pages.append(moderating_embed)

        # Quotes
        quotes_embed = Embed(title="💬 Quotes", color=discord.Color.teal())
        quotes_embed.add_field(name="/quote_add", value="Add a new quote.", inline=False)
        quotes_embed.add_field(name="/quote_get", value="Get a random quote.", inline=False)
        quotes_embed.add_field(name="/quote_list", value="View all quotes.", inline=False)
        quotes_embed.add_field(name="/quote_edit <index> <new_text>", value="Edit a quote.", inline=False)
        quotes_embed.add_field(name="/quote_delete <index>", value="Delete a quote.", inline=False)
        pages.append(quotes_embed)

        # Dynamic page numbering
        total = len(pages)
        for i, emb in enumerate(pages, start=1):
            emb.set_footer(text=f"Page {i}/{total}")

        try:
            view = HelpPaginator(pages)
            await interaction.response.send_message(embed=pages[0], view=view)
        except Exception:
            self.logger.exception('[Misc] Failed to send help in channel')
            error = Embed(
                title="❌ Couldn't Send Help",
                description="I couldn't post the help message in this channel. Check my permissions or try again.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error, ephemeral=True)

    @app_commands.command(name="help_message", description="Send a help message to the bot owner (DM)")
    @app_commands.describe(message='Message to send to the bot owner, reccomendations are welcome!')
    async def help_message(self, interaction: Interaction, message: str):
        debug_command('help_message', interaction.user, interaction.guild, message=message)

        # Try to read an owner_id from xp_config.json under top-level 'owner_id'
        owner_id = None
        try:
            cfg_path = Path('xp_config.json')
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding='utf-8') or '{}')
                owner_id = cfg.get('owner_id')
        except Exception:
            owner_id = None

        owner = None
        try:
            if owner_id:
                owner = await self.bot.fetch_user(int(owner_id))
            else:
                app_info = await self.bot.application_info()
                owner = app_info.owner
        except Exception:
            owner = None

        # build embed to DM the owner: only include user (no ID), server name, and message
        owner_emb = Embed(title=f'Help message from {interaction.user.display_name}', color=discord.Color.blue())
        owner_emb.add_field(name='User', value=f'{interaction.user}', inline=False)
        owner_emb.add_field(name='Server', value=f'{interaction.guild.name}', inline=False)
        owner_emb.add_field(name='Message', value=message, inline=False)
        owner_emb.set_footer(text=f'Sent via /help_message')

        sent = False
        if owner:
            try:
                await owner.send(embed=owner_emb)
                sent = True
            except Exception:
                sent = False

        if sent:
            emb = Embed(title='Message sent', description='Your message was delivered to the bot owner.', color=discord.Color.green())
            await interaction.response.send_message(embed=emb, ephemeral=True)
        else:
            emb = Embed(title='Delivery failed', description='Could not deliver your message to the bot owner. They may have DMs closed or an error occurred.', color=discord.Color.red())
            await interaction.response.send_message(embed=emb, ephemeral=True)

    # Admin: Send a message as the bot with optional embed formatting
    @app_commands.command(name="bot_say", description="Admin: Make the bot send a message, with optional embed formatting.")
    @app_commands.checks.has_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel to post in (defaults to current)",
        message="Plain text content (required if not using embed)",
        use_embed="Send as an embed instead of plain text",
        title="Embed title (optional)",
        description="Embed description (optional; if blank, message will be used)",
        color="Embed color (name like 'blue' or hex like #5865F2)",
        footer="Embed footer text (optional)",
        image_url="Embed image URL (optional)",
        thumbnail_url="Embed thumbnail URL (optional)",
        mention_everyone="Ping @everyone (use sparingly)"
    )
    async def say_as_bot(
        self,
        interaction: Interaction,
        channel: discord.TextChannel = None,
        message: Optional[str] = None,
        use_embed: bool = False,
        title: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        footer: Optional[str] = None,
        image_url: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        mention_everyone: bool = False,
    ):
        target_channel = channel or interaction.channel
        if target_channel is None:
            await interaction.response.send_message(
                embed=Embed(title="❌ No Channel", description="Couldn't resolve a target channel to send the message.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        # Helper: parse color
        def parse_color(val: Optional[str]) -> Optional[discord.Color]:
            if not val:
                return None
            v = val.strip().lower()
            NAMED = {
                'blue': discord.Color.blue(),
                'red': discord.Color.red(),
                'green': discord.Color.green(),
                'gold': discord.Color.gold(),
                'orange': discord.Color.orange(),
                'purple': discord.Color.purple(),
                'teal': discord.Color.teal(),
                'dark_grey': discord.Color.dark_grey(),
                'dark_gray': discord.Color.dark_grey(),
                'grey': discord.Color.greyple(),
                'gray': discord.Color.greyple(),
                'blurple': discord.Color.blurple(),
                'fuchsia': discord.Color.fuchsia(),
            }
            if v in NAMED:
                return NAMED[v]
            # hex forms #RRGGBB or RRGGBB or 0xRRGGBB
            try:
                if v.startswith('#'):
                    v = v[1:]
                if v.startswith('0x'):
                    v = v[2:]
                if len(v) == 6:
                    return discord.Color(int(v, 16))
            except Exception:
                return None
            return None

        # Validation: ensure we have something to send
        if not use_embed:
            if not message or not message.strip():
                await interaction.response.send_message(
                    embed=Embed(title="❌ Missing Message", description="Provide `message` when not using embed.", color=discord.Color.red()),
                    ephemeral=True,
                )
                return
        else:
            # For embed mode, allow description to fall back to message; but ensure at least one of them exists
            if (not description or not description.strip()) and (not message or not message.strip()) and (not title or not title.strip()) and not image_url and not thumbnail_url:
                await interaction.response.send_message(
                    embed=Embed(title="❌ Nothing To Send", description="Supply a title, description/message, or media when using embed.", color=discord.Color.red()),
                    ephemeral=True,
                )
                return

        # Compose allowed mentions
        allowed = discord.AllowedMentions(everyone=mention_everyone, users=False, roles=False, replied_user=False)

        try:
            if use_embed:
                em = Embed()
                col = parse_color(color)
                if col:
                    em.color = col
                if title:
                    em.title = title
                # Prefer explicit description; otherwise use message if provided
                if description and description.strip():
                    em.description = description
                elif message and message.strip():
                    em.description = message
                if footer:
                    em.set_footer(text=footer)
                if image_url:
                    em.set_image(url=image_url)
                if thumbnail_url:
                    em.set_thumbnail(url=thumbnail_url)
                ping_content = "@everyone" if mention_everyone else None
                await target_channel.send(content=ping_content, embed=em, allowed_mentions=allowed)
            else:
                out = message or ""
                if mention_everyone:
                    out = f"@everyone {out}"
                await target_channel.send(content=out, allowed_mentions=allowed)
        except Exception:
            await interaction.response.send_message(
                embed=Embed(title="❌ Send Failed", description="I couldn't send the message. Check channel permissions and inputs.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        # Acknowledge success
        where = f"#{target_channel.name}" if isinstance(target_channel, discord.TextChannel) else str(target_channel)
        await interaction.response.send_message(
            embed=Embed(title="✅ Sent", description=f"Message sent to {where}.", color=discord.Color.green()),
            ephemeral=True,
        )

async def setup(bot):
    await bot.add_cog(Misc(bot))
