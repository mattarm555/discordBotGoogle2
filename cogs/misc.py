import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction, Embed
import random
from datetime import datetime
from utils.debug import debug_command
import asyncio
import logging
from typing import Optional
from utils.botadmin import (
    app_check_bot_admin,
    app_check_can_manage_bot_permissions,
    add_bot_admin_role,
    remove_bot_admin_role,
    get_bot_admin_role_ids,
)

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
    @app_check_can_manage_bot_permissions()
    async def listpermissions(self, interaction: Interaction):
        guild_id = str(interaction.guild.id)
        perms = get_bot_admin_role_ids(guild_id)
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
    @app_check_can_manage_bot_permissions()
    async def removepermissions(self, interaction: Interaction, role: discord.Role):
        guild_id = str(interaction.guild.id)
        perms = set(get_bot_admin_role_ids(guild_id))
        if str(role.id) in perms:
            remove_bot_admin_role(guild_id, role.id)
            info = Embed(title='Role Removed', description=f'Role {role.mention} removed from bot admin permissions.', color=discord.Color.green())
            await interaction.response.send_message(embed=info, ephemeral=True)
        else:
            err = Embed(title='Not a Bot Admin', description=f'Role {role.mention} is not a bot admin.', color=discord.Color.red())
            await interaction.response.send_message(embed=err, ephemeral=True)
    
    @app_commands.command(name="setpermissions", description="Set a role as bot admin for this server.")
    @app_commands.describe(role="Role to grant bot admin permissions")
    @app_check_can_manage_bot_permissions()
    async def setpermissions(self, interaction: Interaction, role: discord.Role):
        guild_id = str(interaction.guild.id)
        perms = set(get_bot_admin_role_ids(guild_id))
        if str(role.id) not in perms:
            add_bot_admin_role(guild_id, role.id)
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

        def build_section_pages(title: str, color: discord.Color, fields: list[tuple[str, str]], max_fields: int = 25) -> list[Embed]:
            if not fields:
                return []
            chunks = [fields[i:i + max_fields] for i in range(0, len(fields), max_fields)]
            built: list[Embed] = []
            for idx, chunk in enumerate(chunks, start=1):
                page_title = title if len(chunks) == 1 else f"{title} (Part {idx}/{len(chunks)})"
                emb = Embed(title=page_title, color=color)
                for name, value in chunk:
                    emb.add_field(name=name, value=value, inline=False)
                built.append(emb)
            return built

        # Music (includes DJ commands) - owner-only commands intentionally excluded
        music_fields: list[tuple[str, str]] = [
            ("/play <url>", "Plays a song or playlist from the given URL."),
            ("/queue", "Shows the current music queue."),
            ("/skip", "Skips the current song."),
            ("/stop", "Pauses the music."),
            ("/start", "Resumes paused music."),
            ("/leave", "Clears the queue and makes the bot leave the voice channel."),
            ("/playplaylist <name>", "Play a previously saved playlist."),
            ("/saveplaylist <name> <link>", "Save a playlist link under a custom name."),
            ("/removeplaylist <name>", "Delete a saved playlist."),
            ("/listplaylists", "List saved playlists for this server."),
            ("/queueshuffle", "Shuffles the current queue."),
            ("/np", "Shows the currently playing song."),
            ("/setdj <role>", "Assign or update the DJ role (Manage Guild)."),
            ("/cleardj", "Remove the configured DJ role restriction."),
            ("/djinfo", "Show the current DJ role configuration."),
        ]
        pages.extend(build_section_pages("🎵 Music Commands", discord.Color.blue(), music_fields))

        # Gambling - owner-only commands intentionally excluded
        gambling_fields: list[tuple[str, str]] = [
            ("/daily", "Claim your daily coin reward (per-server range; 24h cooldown)."),
            ("/econinfo", "Show this server's /daily, /work, /shop, and rebirth settings."),
            ("/balance [user]", "Check your balance or another user's balance."),
            ("/balancetop", "Show the top balances in this server."),
            ("/pay <user> <amount>", "Pay another user some of your coins."),
            ("/blackjack <bet>", "Play a hand of blackjack (bet limits are server-configurable)."),
            ("/casino_set_interval <duration>", "Admin: Set cooldown for casino games (blackjack/roulette) (min 10s). E.g., 10s, 30s, 1m."),
            ("/slots <bet> [lines]", "Spin the slots (bet limits are server-configurable; 1–5 lines)."),
            ("/slots_set_cooldown <duration>", "Admin: Set cooldown between slot spins (min 1s). E.g., 1s, 10s, 1m."),
            ("/roulette <bet>", "Roulette (shares blackjack cooldown). Choose via buttons (red/black/green or number 0/00/1–36)."),
            ("/casino_bet_limit <min> <max>", "Admin: Set casino bet limits for blackjack/roulette."),
            ("/slots_bet_limit <min> <max>", "Admin: Set slots bet limits."),
            ("/slotstats", "View your slot stats and session delta."),
            ("/slotresetsession", "Reset your slot session baseline."),
            ("/work", "Work a random job to earn coins (per-server cooldown)."),
            ("/setworkcooldown <duration>", "Admin: Set /work cooldown (e.g., 15m, 2h, 1d)."),
            ("/setworkreward <min> <max>", "Admin: Set this server's /work reward range."),
            ("/setdailyreward <min> <max>", "Admin: Set this server's /daily reward range."),
            ("/rebirth [confirm]", "Reset your coins to gain a multiplier on /daily, /work, and shop passive income."),
            ("/setrebirthcost <amount>", "Admin: Set how many coins are required to /rebirth in this server."),
            ("/coin_reset", "Admin: Reset all coin balances for this server."),
            ("/shop [page]", "Browse passive income items (shows what you own)."),
            ("/buy <item_name> [amount]", "Buy a passive item by exact name (see /shop). Amount defaults to 1."),
            ("/inventory", "See the passive items you own and their income."),
            ("/shop_set_interval <duration>", "Admin: Set how often items pay (e.g., 15m, 1h, 2h30m)."),
            ("/item_add <name> <cost> <income> <description>", "Admin: Add a server-specific shop item."),
            ("/item_delete <name>", "Admin: Delete a server-specific shop item."),
            ("/item_list", "List this server's custom shop items."),
            ("/econ_wipe", "Admin: Wipe all users' coins and owned items for this server."),
        ]
        pages.extend(build_section_pages("🎰 Gambling", discord.Color.gold(), gambling_fields))

        # XP
        xp_fields: list[tuple[str, str]] = [
            ("/level", "Shows your XP level and server rank."),
            ("/xpleaderboard [page]", "Shows the leaders in XP in this server."),
            ("/xpset <amount>", "Sets the amount of XP gained per message."),
            ("/addxp <user> <amount>", "Admin: Add XP to a user (applies any earned level roles)."),
            ("/xpblock <channel>", "Blocks XP in the given channel."),
            ("/xpunblock <channel>", "Unblocks XP in the given channel."),
            ("/xpconfig", "Shows the current XP settings."),
            ("/setlevelrole <level> <role>", "Set which role is given at a specific level."),
            ("/resetxp", "Admin: Reset all XP and levels for this server."),
            ("/levelup_silence <channel>", "Admin: Toggle muting level-up messages in a channel."),
            ("/levelup_channel [channel]", "Admin: Set or clear a dedicated channel for level-up messages."),
        ]
        pages.extend(build_section_pages("📈 XP System", discord.Color.green(), xp_fields))

        # Misc
        misc_fields: list[tuple[str, str]] = [
            ("/snipe", "Retrieves the last deleted message in the current channel."),
            ("/bot_say", "Admin: Make the bot send a message (with embed options)."),
        ]
        pages.extend(build_section_pages("😂 Miscellaneous", discord.Color.purple(), misc_fields))

        # Community
        community_fields: list[tuple[str, str]] = [
            ("/poll", "Create a custom emoji poll with 2–6 options and a closing timer."),
            ("/event", "Create an interactive RSVP event."),
            ("/welcomeconfig", "Show current welcome message configuration."),
            ("/setwelcome", "Configure the welcome message settings."),
            ("/follow <platform> <identifier> <post_channel>", "Follow a YouTube or Twitch channel and post new content to a channel."),
            ("/removefollow <sub_id>", "Remove a follow subscription by ID (from /followlist)."),
            ("/followlist", "List follow subscriptions for this server."),
            ("/ticket <subject>", "Open a private ticket channel for support."),
            ("/ticketlocation <category>", "Set the default category for new tickets."),
            ("/reactionroles_create <count> <interactive> [base_name]", "Create reaction roles (max 50)."),
            ("/reactionroles_post <config_id> <channel> <message>", "Post a reaction-roles message."),
            ("/reactionroles_remove <config_id>", "Remove a color role set."),
            ("/reaction_list", "List reaction configurations."),
            ("/custom_reactionroles <role> <emoji> [config_id]", "Add your own role+emoji to a reaction-role config. If no config_id is provided, a personal default is created and reused."),
            ("/counting <name> [chances]", "Create a counting channel."),
            ("/delete_counting <channel>", "Delete a counting channel."),
        ]
        pages.extend(build_section_pages("📊 Community Tools", discord.Color.orange(), community_fields))

        # Moderating
        moderating_fields: list[tuple[str, str]] = [
            ("/mute <member> [duration] [reason]", "Mute a member (e.g. 10m, 1h, 1d)."),
            ("/mutestatus [member]", "Show remaining mute time."),
            ("/unmute <member>", "Unmute immediately."),
            ("/kick <member> [reason]", "Kick a member."),
            ("/ban <member> [reason]", "Ban a member."),
            ("/mutelist_add <phrase> <duration> [reason]", "Add auto-mute phrase."),
            ("/mutelist_remove <phrase>", "Remove auto-mute phrase."),
            ("/mutelist_list", "List auto-mute phrases."),
        ]
        pages.extend(build_section_pages("🛡️ Moderating", discord.Color.red(), moderating_fields))

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

    # Admin: Send a message as the bot with optional embed formatting
    @app_commands.command(name="bot_say", description="Admin: Make the bot send a message, with optional embed formatting.")
    @app_check_bot_admin()
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
