import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import random
import json
import os
from datetime import datetime, timedelta
from utils.economy import add_currency, get_balance

COOLDOWN_FILE = "work_cooldowns.json"
CONFIG_FILE = "work_config.json"  # per-guild config, e.g., cooldown seconds
DEFAULT_COOLDOWN = timedelta(hours=1)


def load_cooldowns():
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_cooldowns(data: dict):
    try:
        with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


class Work(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # cooldowns structure: { guild_id: { user_id: iso_timestamp } }
        self.cooldowns = load_cooldowns()
        # config structure: { guild_id: { "cooldown_seconds": int } }
        self.config = load_config()

    def _get_next_allowed(self, guild_id: int, user_id: int) -> datetime | None:
        gid = str(guild_id)
        uid = str(user_id)
        iso = self.cooldowns.get(gid, {}).get(uid)
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except Exception:
            return None

    def _set_next_allowed(self, guild_id: int, user_id: int, when: datetime):
        gid = str(guild_id)
        uid = str(user_id)
        self.cooldowns.setdefault(gid, {})[uid] = when.isoformat()
        save_cooldowns(self.cooldowns)

    def _get_guild_cooldown(self, guild_id: int) -> timedelta:
        gid = str(guild_id)
        secs = 0
        try:
            secs = int(self.config.get(gid, {}).get("cooldown_seconds", 0))
        except Exception:
            secs = 0
        return timedelta(seconds=secs) if secs > 0 else DEFAULT_COOLDOWN

    def _set_guild_cooldown(self, guild_id: int, td: timedelta):
        gid = str(guild_id)
        secs = max(60, int(td.total_seconds()))  # enforce minimum 60s at storage level
        self.config.setdefault(gid, {})["cooldown_seconds"] = secs
        save_config(self.config)

    # Parse strings like "15m", "2h", "1d"; support compound like "1h30m" and space-separated
    def _parse_duration(self, s: str) -> timedelta | None:
        import re
        try:
            s = (s or "").strip().lower()
            if not s:
                return None
            total_seconds = 0
            # Find pairs of number + optional unit across the whole string
            for num, unit in re.findall(r"(\d+)\s*([a-zA-Z]?)", s):
                if not num:
                    continue
                n = int(num)
                u = (unit or 's').lower()[0]
                if u == 'd':
                    total_seconds += n * 86400
                elif u == 'h':
                    total_seconds += n * 3600
                elif u == 'm':
                    total_seconds += n * 60
                elif u == 's':
                    total_seconds += n
                else:
                    # Unknown unit, ignore this token
                    continue
            if total_seconds <= 0:
                return None
            return timedelta(seconds=total_seconds)
        except Exception:
            return None

    def _format_timedelta_mm_ss(self, delta: timedelta) -> str:
        total = int(max(0, delta.total_seconds()))
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _pick_job(self) -> tuple[str, int]:
        # Expanded job list with ranges; some can be negative for risk
        jobs = [
            ("Pizza Delivery Driver", random.randint(100, 300)),
            ("Software Engineer", random.randint(300, 600)),
            ("Streamer", random.randint(200, 400)),
            ("Janitor", random.randint(80, 200)),
            ("Teacher", random.randint(150, 350)),
            ("Barista", random.randint(120, 250)),
            ("Taxi Driver", random.randint(150, 300)),
            ("Fast Food Worker", random.randint(90, 200)),
            ("Construction Worker", random.randint(200, 400)),
            ("Electrician", random.randint(250, 500)),
            ("Doctor", random.randint(500, 900)),
            ("Lawyer", random.randint(400, 800)),
            ("Cashier", random.randint(100, 220)),
            ("Chef", random.randint(200, 450)),
            ("Artist", random.randint(150, 500)),
            ("Graphic Designer", random.randint(200, 400)),
            ("Actor", random.randint(100, 800)),
            ("Musician", random.randint(50, 700)),
            ("Influencer", random.randint(-100, 600)),
            ("Gambler", random.randint(-200, 1000)),
            ("Mechanic", random.randint(200, 450)),
            ("Taxi Dispatcher", random.randint(180, 350)),
            ("Firefighter", random.randint(300, 600)),
            ("Police Officer", random.randint(250, 500)),
            ("Detective", random.randint(400, 700)),
            ("Game Developer", random.randint(250, 650)),
            ("Data Analyst", random.randint(300, 550)),
            ("Delivery Drone Operator", random.randint(180, 360)),
            ("AI Prompt Engineer", random.randint(400, 800)),
            ("Politician", random.randint(-200, 1200)),
            ("Stock Trader", random.randint(-500, 1200)),
            ("Thief", random.randint(-300, 900)),
            ("Bounty Hunter", random.randint(300, 800)),
            ("Farmer", random.randint(120, 300)),
            ("Fisherman", random.randint(80, 220)),
            ("Journalist", random.randint(150, 400)),
            ("Soldier", random.randint(200, 500)),
            ("Scientist", random.randint(300, 700)),
            ("Astronaut", random.randint(500, 1000)),
            ("YouTuber", random.randint(-150, 900)),
            ("Comedian", random.randint(100, 600)),
            ("Bank Robber", random.randint(-1000, 2000)),
            ("Movie Director", random.randint(400, 900)),
            ("Streamer’s Editor", random.randint(180, 400)),
            ("Bot Developer", random.randint(250, 500)),
            ("Crypto Miner", random.randint(-400, 1000)),
            ("Ice Cream Truck Driver", random.randint(120, 300)),
            ("Meme Lord", random.randint(50, 600)),
        ]
        return random.choice(jobs)

    @app_commands.command(name="work", description="Work a random job and earn some coins!")
    async def work(self, interaction: Interaction):
        now = datetime.utcnow()
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=Embed(title="Guild Only", description="This command can only be used in a server.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        next_allowed = self._get_next_allowed(guild.id, interaction.user.id)
        if next_allowed and now < next_allowed:
            remaining = next_allowed - now
            await interaction.response.send_message(
                embed=Embed(
                    title="⏳ You’re tired!",
                    description=f"Come back in {self._format_timedelta_mm_ss(remaining)} before working again.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        job, reward = self._pick_job()
        # Optional tweak: random multiplier 0.8–1.2
        multiplier = random.uniform(0.8, 1.2)
        reward = int(reward * multiplier)
        # Ensure rewards end with a 0 by scaling by 10
        reward *= 10

        # Apply reward via guild-scoped balance
        uid = str(interaction.user.id)
        gid = str(guild.id)
        add_currency(uid, reward, guild_id=gid)
        balance = get_balance(uid, guild_id=gid)

        # Set cooldown (use per-guild configured or default)
        cooldown_td = self._get_guild_cooldown(guild.id)
        if cooldown_td.total_seconds() < 60:
            cooldown_td = timedelta(seconds=60)
        self._set_next_allowed(guild.id, interaction.user.id, now + cooldown_td)

        # Build embed output
        color = discord.Color.green() if reward >= 0 else discord.Color.red()
        desc = f"You earned **{reward}** coins!"
        # Fun flavor text for negatives
        if reward < 0:
            desc += "\n(Things didn't go well this time...)"

        embed = Embed(
            title=f"💼 You worked as a {job}!",
            description=desc,
            color=color,
        )
        embed.set_footer(text=f"Balance: {balance} coins")
        await interaction.response.send_message(embed=embed)

    # Admin command to set work cooldown per guild
    @app_commands.command(name="setworkcooldown", description="Admin: Set /work cooldown (e.g., 15m, 2h, 1d, 1h30m). Minimum 1m.")
    @app_commands.describe(duration="Duration like 15m, 2h, 1d, or combined like 1h30m")
    async def set_work_cooldown(self, interaction: Interaction, duration: str):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=Embed(title="Guild Only", description="This command can only be used in a server.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        # Require admin role/permission
        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.manage_guild):
            await interaction.response.send_message(
                embed=Embed(title="❌ Missing Permission", description="You need Administrator or Manage Server to change the cooldown.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        td = self._parse_duration(duration)
        if not td or td.total_seconds() < 60:
            await interaction.response.send_message(
                embed=Embed(title="⏳ Invalid Duration", description="Please supply a duration of at least 1m. Examples: 15m, 2h, 1d, 1h30m, or '1h 30m'.", color=discord.Color.orange()),
                ephemeral=True,
            )
            return

        self._set_guild_cooldown(guild.id, td)
        pretty = self._format_timedelta_mm_ss(td)
        await interaction.response.send_message(
            embed=Embed(title="✅ Work Cooldown Updated", description=f"Set /work cooldown to {pretty}.", color=discord.Color.green()),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Work(bot))
