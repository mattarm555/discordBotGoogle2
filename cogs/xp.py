import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import json
import os
from utils.economy import add_currency

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"

XP_FILE = "xp_data.json"
CONFIG_FILE = "xp_config.json"

def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class XP(commands.Cog):
    def has_bot_admin(self, member: discord.Member):
        guild_id = str(member.guild.id)
        config = self.get_xp_config(guild_id)
        perms = config.get("permissions_roles", [])
        # Check if user is admin or has a bot-admin role
        if member.guild_permissions.administrator:
            return True
        for role in member.roles:
            if str(role.id) in perms:
                return True
        return False

    @app_commands.command(name="setlevelrole", description="Set which role is given at a specific level.")
    @app_commands.describe(level="Level number", role="Role to assign")
    async def setlevelrole(self, interaction: Interaction, level: int, role: discord.Role):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        guild_id = str(interaction.guild.id)
        config = self.get_xp_config(guild_id)
        config.setdefault("level_roles", {})[str(level)] = str(role.id)
        save_json(CONFIG_FILE, self.config)
        await interaction.response.send_message(f"Role {role.mention} will now be assigned at level {level}.", ephemeral=True)
    def __init__(self, bot):
        self.bot = bot
        self.xp_data = load_json(XP_FILE)
        self.config = load_json(CONFIG_FILE)

    def get_xp_config(self, guild_id):
        # Ensure the guild entry exists and provides expected keys with defaults
        if guild_id not in self.config:
            self.config[guild_id] = {}
        cfg = self.config[guild_id]
        cfg.setdefault("xp_per_message", 10)
        cfg.setdefault("blocked_channels", [])
        cfg.setdefault("level_roles", {})
        return cfg

    def add_xp(self, member: discord.Member, amount: int):
        guild_id = str(member.guild.id)
        user_id = str(member.id)

        if guild_id not in self.xp_data:
            self.xp_data[guild_id] = {}

        if user_id not in self.xp_data[guild_id]:
            self.xp_data[guild_id][user_id] = {"xp": 0, "level": 1}

        self.xp_data[guild_id][user_id]["xp"] += amount

        current_level = self.xp_data[guild_id][user_id]["level"]
        required_xp = current_level * 100

        if self.xp_data[guild_id][user_id]["xp"] >= required_xp:
            self.xp_data[guild_id][user_id]["level"] += 1
            self.xp_data[guild_id][user_id]["xp"] = 0
            return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        config = self.get_xp_config(guild_id)

        if channel_id in config["blocked_channels"]:
            return

        leveled_up = self.add_xp(message.author, config["xp_per_message"])
        if leveled_up:
            try:
                new_level = self.xp_data[guild_id][str(message.author.id)]["level"]
                coin_reward = 100 * new_level
                
                embed = Embed(
                    title="🎉 Level Up!",
                    description=f"{message.author.mention} leveled up to **Level {new_level}**!\n💰 Earned **{coin_reward}** coins!",
                    color=discord.Color.orange()
                )
                embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else message.author.default_avatar.url)
                await message.channel.send(embed=embed)
                
                # Award currency on level up: 100 * new_level
                try:
                    add_currency(str(message.author.id), coin_reward, guild_id=guild_id)
                except Exception:
                    pass
                # Assign role if configured for this level
                level_roles = config.get("level_roles", {})
                new_level = self.xp_data[guild_id][str(message.author.id)]["level"]
                role_id = level_roles.get(str(new_level))
                if role_id:
                    role = message.guild.get_role(int(role_id))
                    if role and role not in message.author.roles:
                        await message.author.add_roles(role, reason="Level up reward")
            except discord.Forbidden:
                pass

        save_json(XP_FILE, self.xp_data)

    @app_commands.command(name="level", description="Shows your current XP level and rank.")
    async def level(self, interaction: Interaction):
        debug_command("level", interaction.user, interaction.guild)

        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)

        user_data = self.xp_data.get(guild_id, {}).get(user_id, {"xp": 0, "level": 1})
        xp = user_data["xp"]
        level = user_data["level"]
        required_xp = level * 100

        all_users = self.xp_data.get(guild_id, {})
        sorted_users = sorted(
            all_users.items(), key=lambda item: (item[1]["level"], item[1]["xp"]), reverse=True
        )
        rank = next((i for i, (uid, _) in enumerate(sorted_users, start=1) if uid == user_id), None)

        embed = Embed(title="📈 XP Level", color=discord.Color.green())
        embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        # Show only the mention (no parenthetical display name)
        embed.add_field(name="User", value=f"{interaction.user.mention}", inline=False)
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="XP", value=f"{xp} / {required_xp}")
        embed.add_field(name="Rank", value=f"#{rank}" if rank else "Unranked")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpleaderboard", description="Shows the XP leaderboard with optional page (10 per page).")
    @app_commands.describe(page="Page number to view (default 1)")
    async def xpleaderboard(self, interaction: Interaction, page: int = 1):
        debug_command("xpleaderboard", interaction.user, interaction.guild, page=page)

        guild_id = str(interaction.guild.id)
        all_users = self.xp_data.get(guild_id, {})

        if not all_users:
            await interaction.response.send_message(embed=Embed(
                title="❌ Empty Leaderboard",
                description="No XP data yet!",
                color=discord.Color.red()
            ))
            return

        sorted_users = sorted(
            all_users.items(), key=lambda item: (item[1]["level"], item[1]["xp"]), reverse=True
        )
        page_size = 10
        total = len(sorted_users)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        # Validate page
        if page < 1:
            page = 1
        if page > total_pages:
            await interaction.response.send_message(embed=Embed(
                title="❌ Page Out of Range",
                description=f"There are only **{total_pages}** page(s) (total **{total}** users). Try a smaller page number.",
                color=discord.Color.red()
            ), ephemeral=True)
            return

        # Build a paginator view with buttons
        view = XPLeaderboardView(interaction.guild, sorted_users, page_size=page_size, page=page)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    @app_commands.command(name="xpset", description="Set how much XP is earned per message.")
    @app_commands.describe(amount="XP amount per message")
    async def xpset(self, interaction: Interaction, amount: int):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("xpset", interaction.user, interaction.guild, amount=amount)
        guild_id = str(interaction.guild.id)
        self.get_xp_config(guild_id)["xp_per_message"] = amount
        save_json(CONFIG_FILE, self.config)
        embed = Embed(
            title="✅ XP Updated",
            description=f"XP per message set to {amount}.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpblock", description="Block XP gain in a channel.")
    @app_commands.describe(channel="The channel to block")
    async def xpblock(self, interaction: Interaction, channel: discord.TextChannel):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("xpblock", interaction.user, interaction.guild, blocked=channel.name)
        guild_id = str(interaction.guild.id)
        config = self.get_xp_config(guild_id)
        if str(channel.id) not in config["blocked_channels"]:
            config["blocked_channels"].append(str(channel.id))
            save_json(CONFIG_FILE, self.config)
        embed = Embed(
            title="🚫 XP Blocked",
            description=f"XP disabled in {channel.mention}.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpunblock", description="Unblock XP gain in a channel.")
    @app_commands.describe(channel="The channel to unblock")
    async def xpunblock(self, interaction: Interaction, channel: discord.TextChannel):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("xpunblock", interaction.user, interaction.guild, unblocked=channel.name)
        guild_id = str(interaction.guild.id)
        config = self.get_xp_config(guild_id)
        if str(channel.id) in config["blocked_channels"]:
            config["blocked_channels"].remove(str(channel.id))
            save_json(CONFIG_FILE, self.config)
        embed = Embed(
            title="✅ XP Unblocked",
            description=f"XP enabled in {channel.mention}.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resetxp", description="Reset all XP and levels for this server.")
    async def resetxp(self, interaction: Interaction):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("resetxp", interaction.user, interaction.guild)
        guild_id = str(interaction.guild.id)
        # remove guild entry
        if guild_id in self.xp_data:
            self.xp_data.pop(guild_id, None)
            save_json(XP_FILE, self.xp_data)
            embed = Embed(title="✅ XP Reset", description="All XP and levels for this server have been reset.", color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
        else:
            embed = Embed(title="ℹ️ No XP Data", description="This server has no XP data to reset.", color=discord.Color.blurple())
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="xpconfig", description="Show current XP settings.")
    async def xpconfig(self, interaction: Interaction):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("xpconfig", interaction.user, interaction.guild)
        guild_id = str(interaction.guild.id)
        config = self.get_xp_config(guild_id)
        amount = config.get("xp_per_message", 10)
        blocked = config.get("blocked_channels", [])
        blocked_channels = [f"<#{cid}>" for cid in blocked]
        embed = Embed(title="⚙️ XP Settings", color=discord.Color.blurple())
        embed.add_field(name="XP per message", value=amount, inline=False)
        embed.add_field(
            name="Blocked Channels",
            value=", ".join(blocked_channels) if blocked_channels else "None",
            inline=False
        )
        await interaction.response.send_message(embed=embed)

# --- Cog Setup ---
async def setup(bot):
    await bot.add_cog(XP(bot))

# ---- XP Leaderboard View with Buttons ----
class XPLeaderboardView(ui.View):
    def __init__(self, guild: discord.Guild, sorted_users: list[tuple[str, dict]], page_size: int = 10, page: int = 1, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.guild = guild
        self.sorted_users = sorted_users
        self.page_size = page_size
        self.total = len(sorted_users)
        self.total_pages = max(1, (self.total + page_size - 1) // page_size)
        self.page = max(1, min(page, self.total_pages))
        self._update_buttons()

    def _slice(self):
        start = (self.page - 1) * self.page_size
        end = min(start + self.page_size, self.total)
        return start, end, self.sorted_users[start:end]

    def make_embed(self) -> Embed:
        start, end, page_users = self._slice()
        embed = Embed(title=f"🏆 XP Leaderboard — Page {self.page}/{self.total_pages}", color=discord.Color.gold())
        display_index = start + 1
        first_member = None
        for user_id, data in page_users:
            member = self.guild.get_member(int(user_id))
            if member:
                if first_member is None:
                    first_member = member
                embed.add_field(name=f"#{display_index}: {member.display_name}", value=f"Level {data['level']} — {data['xp']} XP", inline=False)
                display_index += 1
        if first_member:
            embed.set_thumbnail(url=first_member.avatar.url if first_member.avatar else first_member.default_avatar.url)
        return embed

    def _update_buttons(self):
        # Disable/enable buttons based on current page
        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == 'xp_prev':
                    child.disabled = self.page <= 1
                elif child.custom_id == 'xp_next':
                    child.disabled = self.page >= self.total_pages
                elif child.custom_id == 'xp_back5':
                    child.disabled = self.page <= 1
                elif child.custom_id == 'xp_fwd5':
                    child.disabled = self.page >= self.total_pages

    @ui.button(label="⏮ -5", style=discord.ButtonStyle.gray, custom_id='xp_back5')
    async def back5(self, interaction: Interaction, button: ui.Button):
        old = self.page
        self.page = max(1, self.page - 5)
        if self.page == old:
            await interaction.response.defer()
            return
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="⬅️ Prev", style=discord.ButtonStyle.blurple, custom_id='xp_prev')
    async def prev(self, interaction: Interaction, button: ui.Button):
        if self.page <= 1:
            await interaction.response.defer()
            return
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="Next ➡️", style=discord.ButtonStyle.blurple, custom_id='xp_next')
    async def next(self, interaction: Interaction, button: ui.Button):
        if self.page >= self.total_pages:
            await interaction.response.defer()
            return
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="+5 ⏭", style=discord.ButtonStyle.gray, custom_id='xp_fwd5')
    async def fwd5(self, interaction: Interaction, button: ui.Button):
        old = self.page
        self.page = min(self.total_pages, self.page + 5)
        if self.page == old:
            await interaction.response.defer()
            return
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)
