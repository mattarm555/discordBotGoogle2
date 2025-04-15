import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import json
import os

# --- Color Codes ---
RESET = "\033[0m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"

WELCOME_CONFIG = "welcome_config.json"

def load_welcome_config():
    if os.path.exists(WELCOME_CONFIG):
        with open(WELCOME_CONFIG, "r") as f:
            return json.load(f)
    return {}

def save_welcome_config(config):
    with open(WELCOME_CONFIG, "w") as f:
        json.dump(config, f, indent=4)

def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

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

        formatted_message = welcome_message.format(user=member.mention, server=member.guild.name)
        channel = member.guild.get_channel(int(channel_id))
        if channel:
            embed = Embed(
                title="🎉 Welcome!",
                description=formatted_message,
                color=discord.Color.purple()
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f"Member #{len(member.guild.members)}")
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed)

            # Debug log
            print(f"{GREEN}[WELCOME]{RESET} Welcomed {YELLOW}{member.display_name}{RESET} to {BLUE}{member.guild.name}{RESET}")

    @app_commands.command(name="setwelcome", description="Configure the welcome message settings.")
    @app_commands.describe(
        channel="The channel to send welcome messages to.",
        message="The welcome message. Use {user} and {server}.",
        role="Optional role to assign to new members."
    )
    async def set_welcome(self, interaction: Interaction, channel: discord.TextChannel, message: str, role: discord.Role = None):
        debug_command("setwelcome", interaction.user, interaction.guild, channel=channel.name, role=role.name if role else None)

        guild_id = str(interaction.guild.id)

        self.welcome_config[guild_id] = {
            "channel_id": str(channel.id),
            "message": message,
            "role_id": str(role.id) if role else None
        }

        save_welcome_config(self.welcome_config)

        embed = Embed(
            title="✅ Welcome Configuration Set",
            description=f"Welcome messages will be sent in {channel.mention}.\nMessage: `{message}`\nRole: {role.mention if role else 'None'}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="welcomeconfig", description="Show current welcome message configuration.")
    async def welcome_config_show(self, interaction: Interaction):
        debug_command("welcomeconfig", interaction.user, interaction.guild)

        guild_id = str(interaction.guild.id)
        config = self.welcome_config.get(guild_id)

        if not config:
            embed = Embed(
                title="❌ No Welcome Configuration",
                description="No welcome message has been set for this server.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        channel = self.bot.get_channel(int(config['channel_id']))
        role = interaction.guild.get_role(int(config['role_id'])) if config.get('role_id') else None
        message = config.get("message", "")

        embed = Embed(
            title="📋 Welcome Configuration",
            description=(
                f"**Channel:** {channel.mention if channel else 'Unknown'}\n"
                f"**Message:** `{message}`\n"
                f"**Role:** {role.mention if role else 'None'}"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(Welcome(bot))
