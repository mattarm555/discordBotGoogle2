import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random

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
BOLD = "\033[1m"

# --- XP Settings ---
XP_FILE = "xp_data.json"
XP_PER_MESSAGE = 10
BASE_XP = 100

level_up_responses = [
    "Fuck you {user}, you're now level {level}!",
    "Keep yourself safe {user}, you leveled up to {level}!",
    "Die {user}! Level {level} reached!"
]

# --- JSON Load/Save Helpers ---
def load_xp_data():
    if os.path.exists(XP_FILE):
        try:
            with open(XP_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_xp_data(xp_data):
    with open(XP_FILE, "w") as f:
        json.dump(xp_data, f, indent=4)

def get_xp_needed(level):
    return BASE_XP * (level + 1)

# --- XP Cog ---
class XPSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.xp_data = load_xp_data()

    def ensure_user_entry(self, guild_id, user_id):
        guild_id = str(guild_id)
        user_id = str(user_id)

        if guild_id not in self.xp_data:
            self.xp_data[guild_id] = {}

        if user_id not in self.xp_data[guild_id]:
            self.xp_data[guild_id][user_id] = {"xp": 0, "level": 0}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        user_id = str(message.author.id)

        self.ensure_user_entry(guild_id, user_id)

        user_data = self.xp_data[guild_id][user_id]
        xp_amount = self.xp_data.get(guild_id, {}).get("config", {}).get("xp_per_message", XP_PER_MESSAGE)
        blocked = self.xp_data.get(guild_id, {}).get("config", {}).get("blocked_channels", [])
        if str(message.channel.id) in blocked:
            return  # Skip XP in blocked channels

        user_data["xp"] += xp_amount


        if user_data["xp"] >= get_xp_needed(user_data["level"]):
            user_data["xp"] = 0
            user_data["level"] += 1

            embed = discord.Embed(
                title="🎮 Level Up!",
                description=random.choice(level_up_responses).format(user=message.author.mention, level=user_data["level"]),
                color=discord.Color.gold()
            )
            await message.channel.send(embed=embed)

            print(f"{BOLD}{GREEN}[LEVEL UP]{RESET} {message.author.display_name} is now level {user_data['level']}")

        save_xp_data(self.xp_data)

    @app_commands.command(name="level", description="Check your current level and XP.")
    async def level(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)

    # Ensure the command user has an entry
        self.ensure_user_entry(guild_id, user_id)

    # Ensure all members in the guild have entries to avoid KeyErrors
        for member in interaction.guild.members:
            if not member.bot:
                self.ensure_user_entry(guild_id, str(member.id))

        user_data = self.xp_data[guild_id][user_id]

        # Sort all users in the guild
        all_users = sorted(
            self.xp_data[guild_id].items(),
            key=lambda x: (x[1].get("level", 0), x[1].get("xp", 0)),
            reverse=True
        )

    # Determine the rank
        rank = next((i for i, (uid, _) in enumerate(all_users, 1) if uid == user_id), "Unknown")

        print(f"{BOLD}{CYAN}[COMMAND] /level{RESET} used by {YELLOW}{interaction.user.display_name}{RESET}")

        embed = discord.Embed(
            title="🏆 XP Level",
            description=(
                f"{interaction.user.mention}\n"
                f"**Level:** {user_data['level']}\n"
                f"**XP:** {user_data['xp']}\n"
                f"**Rank:** #{rank}"
            ),
            color=discord.Color.green()
        )

        # 🔥 Add user profile picture to embed
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.response.send_message(embed=embed)



    @app_commands.command(name="leaderboard", description="See the top 10 users by level and XP.")
    async def leaderboard(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)

        print(f"{BOLD}{CYAN}[COMMAND] /leaderboard{RESET} used by {YELLOW}{interaction.user.display_name}{RESET}")

    # If there's no data yet
        if guild_id not in self.xp_data or not self.xp_data[guild_id]:
            embed = discord.Embed(
                title="🏆 Leaderboard",
                description="No XP data for this server yet.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    # Ensure all users have valid XP/level data
        for user_id, data in self.xp_data[guild_id].items():
            if not isinstance(data, dict):
                self.xp_data[guild_id][user_id] = {"xp": 0, "level": 0}
            else:
                data.setdefault("xp", 0)
                data.setdefault("level", 0)

    # Sort safely using fallback values
        def safe_sort_key(item):
            data = item[1]
            return (data.get("level", 0), data.get("xp", 0))

        sorted_users = sorted(
            self.xp_data[guild_id].items(),
            key=safe_sort_key,
            reverse=True
        )

    # Create embed
        embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.blue())

        for i, (user_id, data) in enumerate(sorted_users[:10], start=1):
            try:
                user = await self.bot.fetch_user(int(user_id))
                name = user.display_name
            except:
                name = f"<Unknown User {user_id}>"

            embed.add_field(
                name=f"{i}. {name}",
                value=f"Level {data['level']} ({data['xp']} XP)",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="xpset", description="Set the amount of XP given per message in this server.")
    @app_commands.describe(amount="XP amount per message (positive integer)")
    async def xpset(self, interaction: discord.Interaction, amount: int):
        guild_id = str(interaction.guild.id)

        if amount <= 0:
            embed = discord.Embed(title="❌ Invalid Value", description="XP amount must be greater than 0.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if "config" not in self.xp_data.get(guild_id, {}):
            self.xp_data.setdefault(guild_id, {})["config"] = {}

        self.xp_data[guild_id]["config"]["xp_per_message"] = amount
        save_xp_data(self.xp_data)

        embed = discord.Embed(
            title="🛠️ XP Updated",
            description=f"Set XP per message to **{amount}** in this server.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpblock", description="Block a channel from giving XP.")
    @app_commands.describe(channel="The channel to block XP in")
    async def xpblock(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild.id)

        config = self.xp_data.setdefault(guild_id, {}).setdefault("config", {})
        blocked = config.setdefault("blocked_channels", [])

        if str(channel.id) not in blocked:
            blocked.append(str(channel.id))
            save_xp_data(self.xp_data)

            embed = discord.Embed(
                title="🔕 XP Blocked",
                description=f"Users will no longer gain XP in {channel.mention}.",
                color=discord.Color.orange()
            )
        else:
            embed = discord.Embed(
                title="⚠️ Already Blocked",
                description=f"{channel.mention} is already blocked from giving XP.",
                color=discord.Color.red()
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpunblock", description="Unblock a channel from giving XP.")
    @app_commands.describe(channel="The channel to unblock XP in")
    async def xpunblock(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild.id)

        config = self.xp_data.setdefault(guild_id, {}).setdefault("config", {})
        blocked = config.setdefault("blocked_channels", [])

        if str(channel.id) in blocked:
            blocked.remove(str(channel.id))
            save_xp_data(self.xp_data)

            embed = discord.Embed(
                title="✅ XP Unblocked",
                description=f"{channel.mention} is now allowed to give XP again.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ Not Blocked",
                description=f"{channel.mention} was not blocked.",
                color=discord.Color.red()
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpconfig", description="Shows current XP system settings for this server.")
    async def xpconfig(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        config = self.xp_data.get(guild_id, {}).get("config", {})
        xp_amount = config.get("xp_per_message", XP_PER_MESSAGE)
        blocked_channels = config.get("blocked_channels", [])

        embed = discord.Embed(title="⚙️ XP System Config", color=discord.Color.blurple())
        embed.add_field(name="XP per Message", value=f"**{xp_amount}**", inline=False)
        if blocked_channels:
            mentions = ", ".join(f"<#{cid}>" for cid in blocked_channels)
            embed.add_field(name="Blocked Channels", value=mentions, inline=False)
        else:
            embed.add_field(name="Blocked Channels", value="None", inline=False)

        await interaction.response.send_message(embed=embed)
                                                

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(XPSystem(bot))
