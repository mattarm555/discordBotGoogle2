import discord
from discord.ext import commands
from discord import app_commands, Interaction
import json
import os

# --- Console Colors ---
RESET = "\033[0m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"


WELCOME_CONFIG = "welcome_config.json"

def load_welcome_config():
    if os.path.exists(WELCOME_CONFIG):
        with open(WELCOME_CONFIG, "r") as f:
            return json.load(f)
    return {}

def save_welcome_config(config):
    with open(WELCOME_CONFIG, "w") as f:
        json.dump(config, f, indent=4)

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.welcome_config = load_welcome_config()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild_id = str(member.guild.id)

        config = self.welcome_config.get(guild_id)
        if not config:
            return

        channel_id = config.get("channel_id")
        welcome_message = config.get("message", "")
        role_id = config.get("role_id")

        # Give role if defined
        if role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                await member.add_roles(role)

        # Format the welcome message
        formatted_message = welcome_message.format(user=member.mention, server=member.guild.name)

        # Send the welcome embed
        channel = member.guild.get_channel(int(channel_id))
        if channel:
            embed = discord.Embed(
                title="🎉 Welcome!",
                description=formatted_message,
                color=discord.Color.purple()
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f"Member #{len(member.guild.members)}")
            embed.timestamp = discord.utils.utcnow()

            await channel.send(embed=embed)

            # DEBUG LOG
            print(f"{BOLD}{RED}[WELCOME]{RESET} Welcomed {BOLD}{YELLOW}{member.name}{RESET} to {BOLD}{BLUE}{member.guild.name}{RESET}")

    @app_commands.command(name="setwelcome", description="Configure the welcome message settings.")
    @app_commands.describe(channel="The channel to send welcome messages to.", message="The welcome message. Use {user} and {server}.", role="Optional role to assign to new members.")
    async def set_welcome(self, interaction: Interaction, channel: discord.TextChannel, message: str, role: discord.Role = None):
        guild_id = str(interaction.guild.id)

        self.welcome_config[guild_id] = {
            "channel_id": str(channel.id),
            "message": message,
            "role_id": str(role.id) if role else None
        }

        print(f"{BOLD}{RED}[COMMAND] /set_welcome{RESET}  used by {YELLOW}{interaction.user.display_name}{RESET}")
        
        save_welcome_config(self.welcome_config)

        embed = discord.Embed(
            title="✅ Welcome Configuration Set",
            description=f"Welcome messages will be sent in {channel.mention}.\nMessage: `{message}`\nRole: {role.mention if role else 'None'}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="welcomeconfig", description="Show current welcome message configuration.")
    async def welcome_config_show(self, interaction: Interaction):
        guild_id = str(interaction.guild.id)
        config = self.welcome_config.get(guild_id)

        if not config:
            embed = discord.Embed(
                title="❌ No Welcome Configuration",
                description="No welcome message has been set for this server.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return


        print(f"{BOLD}{RED}[COMMAND] /level{RESET} used by {YELLOW}{interaction.user.display_name}{RESET}")

        channel = self.bot.get_channel(int(config['channel_id']))
        role = interaction.guild.get_role(int(config['role_id'])) if config.get('role_id') else None
        message = config.get("message", "")

        embed = discord.Embed(
            title="📋 Welcome Configuration",
            description=f"**Channel:** {channel.mention if channel else 'Unknown'}\n**Message:** `{message}`\n**Role:** {role.mention if role else 'None'}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(Welcome(bot))
