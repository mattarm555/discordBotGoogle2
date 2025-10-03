# ...existing code...
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
from typing import Optional
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

    def _format_template(self, template: str, member: discord.Member, mention: bool = False) -> str:
        """Safely format a template string with {user} and {server} using member context.
        If mention=True, use member.mention, otherwise use member.display_name (better for titles)."""
        if not template:
            return ""
        try:
            user_val = member.mention if mention else member.display_name
            return template.format(user=user_val, server=member.guild.name)
        except Exception:
            return template

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild_id = str(member.guild.id)
        config = self.welcome_config.get(guild_id)
        if not config:
            return

        channel_id = config.get("channel_id")
        welcome_message = config.get("message", "")
        role_id = config.get("role_id")

        # DM settings
        dm_enabled = bool(config.get("dm", False))
        dm_title = config.get("dm_title", "")
        dm_message = config.get("dm_message", "")

        # Give role if defined
        if role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role)
                except Exception:
                    pass

        formatted_message = welcome_message.format(user=member.mention, server=member.guild.name)
        channel = member.guild.get_channel(int(channel_id)) if channel_id else None
        # channel embed title template (supports {user} and {server})
        embed_title_template = config.get("title", "🎉 Welcome!")
        if channel:
            # use display name in title (no mention parsing in embed titles)
            embed_title = self._format_template(embed_title_template, member, mention=False) or "🎉 Welcome!"
            embed = Embed(
                title=embed_title,
                description=formatted_message,
                color=discord.Color.purple()
            )
            try:
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            except Exception:
                pass
            embed.set_footer(text=f"Member #{len(member.guild.members)}")
            embed.timestamp = discord.utils.utcnow()
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

            # Debug log
            print(f"{GREEN}[WELCOME]{RESET} Welcomed {YELLOW}{member.display_name}{RESET} to {BLUE}{member.guild.name}{RESET}")

        # Send DM if enabled
        if dm_enabled:
            try:
                dm_text = dm_message.format(user=member.mention, server=member.guild.name)
                # DM titles can also use the display name
                dm_title_formatted = self._format_template(dm_title, member, mention=False) or "Welcome!"
                dm_embed = Embed(
                    title=dm_title_formatted,
                    description=dm_text,
                    color=discord.Color.purple()
                )
                try:
                    dm_embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                except Exception:
                    pass
                dm_embed.timestamp = discord.utils.utcnow()
                await member.send(embed=dm_embed)
            except Exception:
                # best-effort: ignore if DMs are closed
                pass

    @app_commands.command(name="setwelcome", description="Configure the welcome message settings.")
    @app_commands.describe(
        channel="The channel to send welcome messages to.",
        message="The welcome message. Use {user} and {server}.",
        role="Optional role to assign to new members.",
        dm="Whether to send a DM to new members (true/false).",
        dm_title="Title for the DM embed (if DMs enabled).",
        dm_message="Message for the DM embed (if DMs enabled). Use {user} and {server}."
    )
    async def set_welcome(
        self,
        interaction: Interaction,
        channel: discord.TextChannel,
        message: str,
        role: Optional[discord.Role] = None,
        dm: bool = False,
        dm_title: Optional[str] = "",
        dm_message: Optional[str] = ""
    ):
        # Permission check
        if not interaction.user.guild_permissions.administrator and not (role and role in interaction.user.roles):
            await interaction.response.send_message(embed=Embed(title="❌ Permission Denied", description="You do not have permission to use this command.", color=discord.Color.red()), ephemeral=True)
            return

        debug_command("setwelcome", interaction.user, interaction.guild, channel=channel.name, role=role.name if role else None, dm=dm)

        guild_id = str(interaction.guild.id)
        self.welcome_config[guild_id] = {
            "channel_id": str(channel.id),
            "message": message,
            "role_id": str(role.id) if role else None,
            "dm": bool(dm),
            "dm_title": dm_title or "",
            "dm_message": dm_message or ""
        }
        save_welcome_config(self.welcome_config)

        embed = Embed(
            title="✅ Welcome Configuration Set",
            description=(
                f"Welcome messages will be sent in {channel.mention}.\n"
                f"Message: `{message}`\n"
                f"Role: {role.mention if role else 'None'}\n"
                f"DMs: {'On' if dm else 'Off'}"
            ),
            color=discord.Color.green()
        )
        if dm:
            embed.add_field(name="DM Title", value=dm_title or "None", inline=False)
            embed.add_field(name="DM Message", value=f"`{dm_message}`" if dm_message else "None", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="welcomeconfig", description="Show current welcome message configuration.")
    async def welcome_config_show(self, interaction: Interaction):
        # Permission check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=Embed(title="❌ Permission Denied", description="You do not have permission to use this command.", color=discord.Color.red()), ephemeral=True)
            return
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
        channel = self.bot.get_channel(int(config['channel_id'])) if config.get('channel_id') else None
        role = interaction.guild.get_role(int(config['role_id'])) if config.get('role_id') else None
        message = config.get("message", "")
        dm_on = bool(config.get("dm", False))
        dm_title = config.get("dm_title", "")
        dm_message = config.get("dm_message", "")

        embed = Embed(
            title="📋 Welcome Configuration",
            description=(
                f"**Channel:** {channel.mention if channel else 'Unknown'}\n"
                f"**Message:** `{message}`\n"
                f"**Role:** {role.mention if role else 'None'}\n"
                f"**DMs:** {'On' if dm_on else 'Off'}"
            ),
            color=discord.Color.blurple()
        )
        if dm_on:
            embed.add_field(name="DM Title", value=dm_title or "None", inline=False)
            embed.add_field(name="DM Message", value=f"`{dm_message}`" if dm_message else "None", inline=False)

        await interaction.response.send_message(embed=embed)

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(Welcome(bot))
# ...existing code...