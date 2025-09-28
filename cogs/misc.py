import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction, Embed
import random
from datetime import datetime
import pytz
from utils.debug import debug_command
import asyncio
import logging

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
            await interaction.response.send_message("No roles have bot admin permissions.", ephemeral=True)
            return
        role_mentions = []
        for role_id in perms:
            role = interaction.guild.get_role(int(role_id))
            if role:
                role_mentions.append(role.mention)
        if role_mentions:
            await interaction.response.send_message("Roles with bot admin permissions: " + ", ".join(role_mentions), ephemeral=True)
        else:
            await interaction.response.send_message("No valid roles found in bot admin permissions.", ephemeral=True)
    
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
            await interaction.response.send_message(f"Role {role.mention} removed from bot admin permissions.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Role {role.mention} is not a bot admin.", ephemeral=True)
    
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
            await interaction.response.send_message(f"Role {role.mention} added as bot admin.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Role {role.mention} is already a bot admin.", ephemeral=True)

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

        pages = []

        # Music
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
        music_embed.set_footer(text="Page 1/5")
        pages.append(music_embed)

        # XP
        xp_embed = Embed(title="📈 XP System Commands", color=discord.Color.green())
        xp_embed.add_field(name="/level", value="Shows your XP level and server rank.", inline=False)
        xp_embed.add_field(name="/leaderboard", value="Shows the leaders in XP in this server.", inline=False)
        xp_embed.add_field(name="/xpset <amount>", value="Sets the amount of XP gained per message.", inline=False)
        xp_embed.add_field(name="/xpblock <channel>", value="Blocks XP in the given channel.", inline=False)
        xp_embed.add_field(name="/xpunblock <channel>", value="Unblocks XP in the given channel.", inline=False)
        xp_embed.add_field(name="/xpconfig", value="Shows the current XP settings.", inline=False)
        xp_embed.add_field(name="/setlevelrole <level> <role>", value="Set which role is given at a specific level.", inline=False)
        xp_embed.set_footer(text="Page 2/5")
        pages.append(xp_embed)

        # Misc
        misc_embed = Embed(title="😂 Miscellaneous Commands", color=discord.Color.purple())
        misc_embed.add_field(name="/snipe", value="Retrieves the last deleted message in the current channel.", inline=False)
        misc_embed.set_footer(text="Page 3/5")
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
        community_embed.add_field(name="/ticket <subject>", value="Open a private ticket channel for support. Staff and admins can close tickets.", inline=False)
        community_embed.add_field(name="/ticketlocation <category>", value="(Admin) Set the default category for new tickets in this server.", inline=False)
        community_embed.add_field(name="/reactionroles_create <count> [base_name]", value="Create 1-75 color roles under the bot's top role.", inline=False)
        community_embed.add_field(name="/reactionroles_post <config_id> <channel> <message>", value="Post a reaction-roles message for a previously created role set.", inline=False)
        community_embed.add_field(name="/reactionroles_remove <config_id>", value="Remove a previously created color role set (deletes roles).", inline=False)
        community_embed.add_field(name="/reaction_list", value="Lists reaction configurations in server.", inline=False)
        community_embed.set_footer(text="Page 4/5")
        pages.append(community_embed)

        # Quotes
        quotes_embed = Embed(title="💬 Quote System", color=discord.Color.teal())
        quotes_embed.add_field(name="/quote_add", value="Add a new quote.", inline=False)
        quotes_embed.add_field(name="/quote_get", value="Get a random quote.", inline=False)
        quotes_embed.add_field(name="/quote_list", value="View all saved quotes.", inline=False)
        quotes_embed.add_field(name="/quote_edit <index> <new_text>", value="Edit a quote by number.", inline=False)
        quotes_embed.add_field(name="/quote_delete <index>", value="Delete a quote by number.", inline=False)
        quotes_embed.set_footer(text="Page 5/5")
        pages.append(quotes_embed)

        try:
            view = HelpPaginator(pages)
            # send the help pages in-channel so others can see
            await interaction.response.send_message(embed=pages[0], view=view)
        except Exception:
            self.logger.exception('[Misc] Failed to send help in channel')
            error = Embed(
                title="❌ Couldn't Send Help",
                description="I couldn't post the help message in this channel. Check my permissions or try again.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Misc(bot))
