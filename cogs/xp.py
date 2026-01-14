import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed, ui
import json
import os
import time
from datetime import datetime, timedelta, timezone
from utils.economy import add_currency
from utils.economy import reset_guild_balances
from utils.botadmin import is_bot_admin

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"

XP_FILE = "xp_data.json"
CONFIG_FILE = "xp_config.json"
WEEKLY_MESSAGES_FILE = "weekly_messages.json"

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
    def has_bot_admin(self, member: discord.Member) -> bool:
        # Centralized check that ignores Discord-level perms and trusts saved role IDs.
        # Also allows guild owner and optional global owner from xp_config.json.
        try:
            return is_bot_admin(member)
        except Exception:
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
        self.weekly_messages = load_json(WEEKLY_MESSAGES_FILE)
        self._weekly_messages_dirty = False
        self._weekly_messages_loop.start()

    def cog_unload(self):
        try:
            self._weekly_messages_loop.cancel()
        except Exception:
            pass

    def _get_weekly_cfg(self, guild_id: str) -> dict:
        if guild_id not in self.weekly_messages:
            self.weekly_messages[guild_id] = {}
        cfg = self.weekly_messages[guild_id]
        cfg.setdefault("enabled", False)
        cfg.setdefault("channel_id", None)
        cfg.setdefault("message_id", None)
        cfg.setdefault("title", "🏆 Weekly Messages Leaderboard")
        cfg.setdefault("description", "Participate by chatting to earn rewards!")
        cfg.setdefault("xp_reward", 0)
        cfg.setdefault("coin_reward", 0)
        cfg.setdefault("start_ts", None)
        cfg.setdefault("end_ts", None)
        cfg.setdefault("counts", {})
        return cfg

    def _human_time_delta(self, seconds: float) -> str:
        seconds = max(0, int(seconds))
        days, rem = divmod(seconds, 86400)
        if days > 0:
            return f"{days} day{'s' if days != 1 else ''}"
        hours, rem = divmod(rem, 3600)
        if hours > 0:
            return f"{hours} hour{'s' if hours != 1 else ''}"
        minutes, _ = divmod(rem, 60)
        if minutes > 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        return "less than a minute"

    def _build_weekly_messages_embed(self, guild: discord.Guild, cfg: dict) -> Embed:
        now = time.time()
        start_ts = cfg.get("start_ts")
        end_ts = cfg.get("end_ts")

        title = cfg.get("title") or "🏆 Weekly Messages Leaderboard"
        desc = cfg.get("description") or "Participate by chatting to earn rewards!"
        xp_reward = int(cfg.get("xp_reward") or 0)
        coin_reward = int(cfg.get("coin_reward") or 0)
        reward_bits: list[str] = []
        if xp_reward:
            reward_bits.append(f"+{xp_reward} XP")
        if coin_reward:
            reward_bits.append(f"+{coin_reward} coins")
        if reward_bits:
            desc = f"{desc}\n\nParticipate by chatting to earn **{' and '.join(reward_bits)}**!"

        embed = Embed(title=title, description=desc, color=discord.Color.gold())

        counts = cfg.get("counts", {}) if isinstance(cfg.get("counts"), dict) else {}
        sorted_counts = sorted(counts.items(), key=lambda kv: int(kv[1]), reverse=True)
        top = sorted_counts[:5]
        if top:
            lines: list[str] = []
            for idx, (uid, cnt) in enumerate(top, start=1):
                lines.append(f"{idx}. <@{uid}>: **{int(cnt)}** messages")
            embed.add_field(name="Top 5", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Top 5", value="No messages yet.", inline=False)

        if start_ts:
            embed.add_field(name="Contest began", value=f"{self._human_time_delta(now - float(start_ts))} ago", inline=True)
        else:
            embed.add_field(name="Contest began", value="Not started", inline=True)
        if end_ts:
            embed.add_field(name="Contest ends", value=f"in {self._human_time_delta(float(end_ts) - now)}", inline=True)
        else:
            embed.add_field(name="Contest ends", value="Not scheduled", inline=True)

        return embed

    def _ensure_week_window(self, cfg: dict) -> None:
        now = time.time()
        if not cfg.get("start_ts") or not cfg.get("end_ts"):
            cfg["start_ts"] = now
            cfg["end_ts"] = now + 7 * 86400

    async def _upsert_weekly_message(self, guild: discord.Guild, cfg: dict) -> None:
        channel_id = cfg.get("channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return

        embed = self._build_weekly_messages_embed(guild, cfg)

        msg_id = cfg.get("message_id")
        msg = None
        if msg_id:
            try:
                msg = await channel.fetch_message(int(msg_id))
            except Exception:
                msg = None
        if msg is None:
            try:
                sent = await channel.send(embed=embed)
                cfg["message_id"] = str(sent.id)
                self._weekly_messages_dirty = True
            except Exception:
                return
        else:
            try:
                await msg.edit(embed=embed)
            except Exception:
                pass

    def _add_xp_record(self, guild_id: str, user_id: str, amount: int) -> int:
        if guild_id not in self.xp_data:
            self.xp_data[guild_id] = {}
        if user_id not in self.xp_data[guild_id]:
            self.xp_data[guild_id][user_id] = {"xp": 0, "level": 1}

        rec = self.xp_data[guild_id][user_id]
        rec["xp"] = int(rec.get("xp", 0)) + int(amount)
        rec["level"] = int(rec.get("level", 1))
        if rec["level"] < 1:
            rec["level"] = 1

        gained = 0
        while True:
            required = int(rec["level"]) * 100
            if rec["xp"] < required:
                break
            rec["xp"] -= required
            rec["level"] += 1
            gained += 1
        return gained

    def get_xp_config(self, guild_id):
        # Ensure the guild entry exists and provides expected keys with defaults
        if guild_id not in self.config:
            self.config[guild_id] = {}
        cfg = self.config[guild_id]
        cfg.setdefault("xp_per_message", 10)
        cfg.setdefault("blocked_channels", [])
        cfg.setdefault("level_roles", {})
        # New: level-up message routing
        cfg.setdefault("levelup_silent_channels", [])  # list of channel IDs where level-up embeds are not posted
        cfg.setdefault("levelup_channel", None)        # single channel ID to route level-up messages, or None for current channel
        return cfg

    def add_xp(self, member: discord.Member, amount: int):
        guild_id = str(member.guild.id)
        user_id = str(member.id)
        return self._add_xp_record(guild_id, user_id, int(amount))

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        config = self.get_xp_config(guild_id)

        if channel_id in config["blocked_channels"]:
            return

        # Weekly message contest tracking (separate from XP gain)
        try:
            weekly_cfg = self._get_weekly_cfg(guild_id)
            if weekly_cfg.get("enabled"):
                self._ensure_week_window(weekly_cfg)
                now = time.time()
                if float(weekly_cfg.get("start_ts") or 0) <= now < float(weekly_cfg.get("end_ts") or 0):
                    # Respect XP blocked channels for contest counting (keeps farming consistent)
                    if channel_id not in config["blocked_channels"]:
                        uid = str(message.author.id)
                        counts = weekly_cfg.setdefault("counts", {})
                        counts[uid] = int(counts.get(uid, 0)) + 1
                        self._weekly_messages_dirty = True
        except Exception:
            pass

        old_level = int(self.xp_data.get(guild_id, {}).get(str(message.author.id), {}).get("level", 1))
        levels_gained = self.add_xp(message.author, config["xp_per_message"])
        if levels_gained and int(levels_gained) > 0:
            try:
                new_level = int(self.xp_data[guild_id][str(message.author.id)]["level"])
                # Reward coins once per level gained (prevents under/overpay when XP jumps multiple levels)
                coin_reward = sum(100 * lvl for lvl in range(old_level + 1, new_level + 1))
                # Prepare level-up embed
                embed = Embed(
                    title="🎉 Level Up!",
                    description=f"{message.author.mention} leveled up to **Level {new_level}**!\n💰 Earned **{coin_reward}** coins!",
                    color=discord.Color.orange()
                )
                embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else message.author.default_avatar.url)
                # Decide where to send the level-up embed
                levelup_channel_id = config.get("levelup_channel")
                silent_channels = set(config.get("levelup_silent_channels", []))
                dest_channel = None
                if levelup_channel_id:
                    dest_channel = message.guild.get_channel(int(levelup_channel_id))
                elif str(message.channel.id) not in silent_channels:
                    dest_channel = message.channel
                # Send only if a destination is determined
                if dest_channel is not None:
                    await dest_channel.send(embed=embed)
                
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
        if self._weekly_messages_dirty:
            try:
                save_json(WEEKLY_MESSAGES_FILE, self.weekly_messages)
                self._weekly_messages_dirty = False
            except Exception:
                pass

    @tasks.loop(minutes=5)
    async def _weekly_messages_loop(self):
        now = time.time()
        # Flush any pending counts periodically even if we can't edit messages
        if self._weekly_messages_dirty:
            try:
                save_json(WEEKLY_MESSAGES_FILE, self.weekly_messages)
                self._weekly_messages_dirty = False
            except Exception:
                pass

        for gid, cfg in list(self.weekly_messages.items()):
            if not isinstance(cfg, dict):
                continue
            if not cfg.get("enabled"):
                continue
            try:
                guild = self.bot.get_guild(int(gid))
            except Exception:
                guild = None
            if not guild:
                continue

            self._ensure_week_window(cfg)
            end_ts = float(cfg.get("end_ts") or 0)
            start_ts = float(cfg.get("start_ts") or 0)

            # Rotate week + distribute participation rewards
            if end_ts and now >= end_ts:
                counts = cfg.get("counts", {}) if isinstance(cfg.get("counts"), dict) else {}
                participants = [uid for uid, cnt in counts.items() if int(cnt) > 0]
                xp_reward = int(cfg.get("xp_reward") or 0)
                coin_reward = int(cfg.get("coin_reward") or 0)

                if participants and (xp_reward or coin_reward):
                    for uid in participants:
                        if xp_reward:
                            try:
                                self._add_xp_record(str(guild.id), str(uid), xp_reward)
                            except Exception:
                                pass
                        if coin_reward:
                            try:
                                add_currency(str(uid), coin_reward, guild_id=str(guild.id))
                            except Exception:
                                pass

                    save_json(XP_FILE, self.xp_data)

                # Reset week
                cfg["counts"] = {}
                cfg["start_ts"] = end_ts
                cfg["end_ts"] = end_ts + 7 * 86400
                self._weekly_messages_dirty = True

            # Keep the leaderboard message fresh
            try:
                await self._upsert_weekly_message(guild, cfg)
            except Exception:
                pass

        if self._weekly_messages_dirty:
            try:
                save_json(WEEKLY_MESSAGES_FILE, self.weekly_messages)
                self._weekly_messages_dirty = False
            except Exception:
                pass

    @_weekly_messages_loop.before_loop
    async def _before_weekly_messages_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="weeklymessages_setup", description="Admin: Post a weekly top-5 message leaderboard and auto-reward participants each week.")
    @app_commands.describe(
        channel="Channel to post the leaderboard in",
        xp_reward="XP each participant earns at week end",
        coin_reward="Coins each participant earns at week end",
        title="Embed title",
        message="Embed message/description"
    )
    async def weeklymessages_setup(
        self,
        interaction: Interaction,
        channel: discord.TextChannel,
        xp_reward: int,
        coin_reward: int,
        title: str,
        message: str,
    ):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild.id)
        cfg = self._get_weekly_cfg(guild_id)
        cfg["enabled"] = True
        cfg["channel_id"] = str(channel.id)
        cfg["title"] = title
        cfg["description"] = message
        cfg["xp_reward"] = max(0, int(xp_reward))
        cfg["coin_reward"] = max(0, int(coin_reward))
        cfg["counts"] = {}

        now = time.time()
        cfg["start_ts"] = now
        cfg["end_ts"] = now + 7 * 86400
        cfg["message_id"] = None

        self._weekly_messages_dirty = True
        save_json(WEEKLY_MESSAGES_FILE, self.weekly_messages)

        try:
            await self._upsert_weekly_message(interaction.guild, cfg)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Weekly messages leaderboard enabled in {channel.mention}.\n"
            f"Rewards: {cfg['xp_reward']} XP, {cfg['coin_reward']} coins per participant.",
            ephemeral=True,
        )

    @app_commands.command(name="weeklymessages_disable", description="Admin: Disable the weekly message leaderboard (keeps saved config).")
    async def weeklymessages_disable(self, interaction: Interaction):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        guild_id = str(interaction.guild.id)
        cfg = self._get_weekly_cfg(guild_id)
        cfg["enabled"] = False
        self._weekly_messages_dirty = True
        save_json(WEEKLY_MESSAGES_FILE, self.weekly_messages)
        await interaction.response.send_message("✅ Weekly messages leaderboard disabled.", ephemeral=True)

    @app_commands.command(name="weeklymessages_postnow", description="Admin: Force an immediate leaderboard refresh.")
    async def weeklymessages_postnow(self, interaction: Interaction):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        cfg = self._get_weekly_cfg(guild_id)
        if not cfg.get("enabled"):
            await interaction.followup.send("❌ Weekly messages leaderboard is not enabled.", ephemeral=True)
            return
        self._ensure_week_window(cfg)
        await self._upsert_weekly_message(interaction.guild, cfg)
        await interaction.followup.send("✅ Leaderboard updated.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """When a member leaves, reset/remove their XP entry for that guild."""
        try:
            guild_id = str(member.guild.id)
            user_id = str(member.id)
            if guild_id in self.xp_data and user_id in self.xp_data[guild_id]:
                # Remove the user's XP record entirely for this guild
                self.xp_data[guild_id].pop(user_id, None)
                # If the guild mapping becomes empty, optionally clean it up
                if not self.xp_data[guild_id]:
                    self.xp_data.pop(guild_id, None)
                save_json(XP_FILE, self.xp_data)
        except Exception:
            # Avoid raising in event handler
            pass

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

    # ---- Level-up message routing commands ----
    @app_commands.command(name="levelup_silence", description="Admin: Mute level-up messages in a specific channel (toggle).")
    @app_commands.describe(channel="Channel to mute/unmute level-up messages")
    async def levelup_silence(self, interaction: Interaction, channel: discord.TextChannel):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("levelup_silence", interaction.user, interaction.guild, channel=channel.name)
        guild_id = str(interaction.guild.id)
        config = self.get_xp_config(guild_id)
        silents = config.setdefault("levelup_silent_channels", [])
        cid = str(channel.id)
        toggled_on = False
        if cid in silents:
            silents.remove(cid)
            action = "unmuted"
        else:
            silents.append(cid)
            action = "muted"
            toggled_on = True
        save_json(CONFIG_FILE, self.config)
        color = discord.Color.red() if toggled_on else discord.Color.green()
        await interaction.response.send_message(embed=Embed(
            title=("🔇 Level-up Muted" if toggled_on else "🔔 Level-up Unmuted"),
            description=f"Level-up messages are now {action} in {channel.mention}.",
            color=color,
        ))

    @app_commands.command(name="levelup_channel", description="Admin: Set or clear a dedicated channel for level-up messages.")
    @app_commands.describe(channel="Channel to send level-up messages; omit to clear and use current channels")
    async def levelup_channel(self, interaction: Interaction, channel: discord.TextChannel | None = None):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("levelup_channel", interaction.user, interaction.guild, channel=channel.mention if channel else "clear")
        guild_id = str(interaction.guild.id)
        config = self.get_xp_config(guild_id)
        if channel is None:
            config["levelup_channel"] = None
            msg = "Level-up messages will be sent in the current channel (unless muted)."
            color = discord.Color.blurple()
        else:
            config["levelup_channel"] = str(channel.id)
            msg = f"Level-up messages will now be sent in {channel.mention}."
            color = discord.Color.green()
        save_json(CONFIG_FILE, self.config)
        await interaction.response.send_message(embed=Embed(title="⚙️ Level-up Routing Updated", description=msg, color=color))

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

    @app_commands.command(name="coin_reset", description="Reset all coin balances for this server.")
    async def coin_reset(self, interaction: Interaction):
        if not self.has_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        debug_command("coin_reset", interaction.user, interaction.guild)
        guild_id = str(interaction.guild.id)
        reset_guild_balances(guild_id)
        embed = Embed(title="✅ Coins Reset", description="All coin balances for this server have been reset.", color=discord.Color.green())
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
        first_member = None
        # Use the global rank index regardless of cache presence
        for idx, (user_id, data) in enumerate(page_users, start=start + 1):
            member = self.guild.get_member(int(user_id))
            if member:
                if first_member is None:
                    first_member = member
                display_name = member.display_name
            else:
                # Fallback to a mention or raw ID if not a member/cached
                display_name = f"<@{user_id}>"
            embed.add_field(name=f"#{idx}: {display_name}", value=f"Level {data['level']} — {data['xp']} XP", inline=False)
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
