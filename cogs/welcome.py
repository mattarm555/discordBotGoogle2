import discord
from discord.ext import commands
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
            embed = discord.Embed(
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

    @commands.slash_command(name="setwelcome", description="Configure the welcome message settings.")
    async def set_welcome(self, ctx: discord.ApplicationContext, channel: discord.TextChannel, message: str, role: discord.Role = None):
        debug_command("setwelcome", ctx.author, ctx.guild, channel=channel.name, role=role.name if role else None)

        guild_id = str(ctx.guild.id)

        self.welcome_config[guild_id] = {
            "channel_id": str(channel.id),
            "message": message,
            "role_id": str(role.id) if role else None
        }

        save_welcome_config(self.welcome_config)

        embed = discord.Embed(
            title="✅ Welcome Configuration Set",
            description=f"Welcome messages will be sent in {channel.mention}.\nMessage: `{message}`\nRole: {role.mention if role else 'None'}",
            color=discord.Color.green()
        )
        await ctx.respond(embed=embed)

    @commands.slash_command(name="welcomeconfig", description="Show current welcome message configuration.")
    async def welcome_config_show(self, ctx: discord.ApplicationContext):
        debug_command("welcomeconfig", ctx.author, ctx.guild)

        guild_id = str(ctx.guild.id)
        config = self.welcome_config.get(guild_id)

        if not config:
            embed = discord.Embed(
                title="❌ No Welcome Configuration",
                description="No welcome message has been set for this server.",
                color=discord.Color.red()
            )
            await ctx.respond(embed=embed)
            return

        channel = self.bot.get_channel(int(config['channel_id']))
        role = ctx.guild.get_role(int(config['role_id'])) if config.get('role_id') else None
        message = config.get("message", "")

        embed = discord.Embed(
            title="📋 Welcome Configuration",
            description=(
                f"**Channel:** {channel.mention if channel else 'Unknown'}\n"
                f"**Message:** `{message}`\n"
                f"**Role:** {role.mention if role else 'None'}"
            ),
            color=discord.Color.blue()
        )
        await ctx.respond(embed=embed)

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(Welcome(bot))
