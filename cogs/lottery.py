import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, button
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils.economy import get_balance, add_currency, remove_currency
from utils.botadmin import is_bot_admin


def parse_duration_str(s: str) -> Optional[timedelta]:
    if not s:
        return None
    s = s.strip().lower()
    total = timedelta()
    # support combined forms like 1d2h30m15s
    for amount, unit in re.findall(r"(\d+)\s*([dhms])", s):
        val = int(amount)
        if unit == 'd':
            total += timedelta(days=val)
        elif unit == 'h':
            total += timedelta(hours=val)
        elif unit == 'm':
            total += timedelta(minutes=val)
        elif unit == 's':
            total += timedelta(seconds=val)
    return total if total.total_seconds() > 0 else None


class LotteryView(View):
    def __init__(self, cog: 'Lottery', guild: discord.Guild, channel: discord.TextChannel, buy_in: int, end_at: datetime):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild = guild
        self.channel = channel
        self.buy_in = int(buy_in)
        self.end_at = end_at
        self.message_id: Optional[int] = None
        self.participants: set[str] = set()
        self.finished: bool = False

    def make_embed(self) -> discord.Embed:
        pool = self.buy_in * len(self.participants)
        ends = int(self.end_at.replace(tzinfo=timezone.utc).timestamp())
        desc = (
            f"Buy-in: **{self.buy_in}** coins\n"
            f"Participants: **{len(self.participants)}**\n"
            f"Pool: **{pool}** coins\n"
            f"Ends: <t:{ends}:R>"
        )
        emb = discord.Embed(title="🎟️ Lottery", description=desc, color=discord.Color.gold())
        return emb

    def _update_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = self.finished or datetime.utcnow() >= self.end_at

    async def end_and_award(self):
        if self.finished:
            return
        self.finished = True
        self._update_buttons()
        # Try to disable button on the original message
        try:
            await self.channel.fetch_message(self.message_id)
            await self.channel.send(embed=discord.Embed(title="⏳ Lottery Closed", description="Entries are now closed. Selecting a winner...", color=discord.Color.blurple()))
        except Exception:
            pass

        # Determine winner
        participants = list(self.participants)
        guild_id = str(self.guild.id)
        if not participants:
            try:
                await self.channel.send(embed=discord.Embed(title="😕 No Entries", description="The lottery ended with no participants.", color=discord.Color.dark_gray()))
            except Exception:
                pass
            return

        import random
        winner_id = random.choice(participants)
        pool = self.buy_in * len(participants)
        add_currency(winner_id, pool, guild_id=guild_id)

        winner_mention = f"<@{winner_id}>"
        emb = discord.Embed(title="🎉 Lottery Winner!", description=f"{winner_mention} won the lottery!! They won **{pool}** coins!!", color=discord.Color.green())
        try:
            await self.channel.send(embed=emb)
        except Exception:
            pass

        # Edit the original lottery message to show disabled button and final state
        try:
            self._update_buttons()
            msg = await self.channel.fetch_message(self.message_id)
            await msg.edit(embed=self.make_embed(), view=self)
        except Exception:
            pass

    @button(label="Buy-in", style=discord.ButtonStyle.green)
    async def buy_in_button(self, interaction: Interaction, button: discord.ui.Button):
        # Ensure still open
        if self.finished or datetime.utcnow() >= self.end_at:
            await interaction.response.send_message(embed=discord.Embed(title="⏳ Lottery Ended", description="Entries are closed. Please wait for the announcement.", color=discord.Color.blurple()), ephemeral=True)
            return
        if interaction.user.bot or not interaction.guild:
            await interaction.response.defer()
            return
        uid = str(interaction.user.id)
        if uid in self.participants:
            await interaction.response.send_message(embed=discord.Embed(title="ℹ️ Already Entered", description="You're already in this lottery.", color=discord.Color.blue()), ephemeral=True)
            return
        # Check funds
        guild_id = str(interaction.guild.id)
        bal = get_balance(uid, guild_id=guild_id)
        if bal < self.buy_in:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Insufficient Funds", description=f"You need {self.buy_in} coins to join but only have {bal}.", color=discord.Color.red()), ephemeral=True)
            return
        # Charge buy-in
        if not remove_currency(uid, self.buy_in, guild_id=guild_id):
            await interaction.response.send_message(embed=discord.Embed(title="❌ Buy-in Failed", description="Failed to process your buy-in. Please try again.", color=discord.Color.red()), ephemeral=True)
            return
        self.participants.add(uid)
        # Update message embed with new count/pool
        try:
            self._update_buttons()
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        except Exception:
            try:
                await interaction.followup.send(embed=discord.Embed(title="✅ You're In!", description="Your buy-in was successful.", color=discord.Color.green()), ephemeral=True)
            except Exception:
                pass


class Lottery(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track one active lottery per guild
        # guild_id -> { 'view': LotteryView, 'task': asyncio.Task }
        self.active: dict[str, dict] = {}

    @app_commands.command(name="lottery", description="Start a server lottery (bot-admin only)")
    @app_commands.describe(buy_in="Buy-in amount per user (coins)", duration="Duration (e.g. 15m, 2h, 1d, or combos like 1h30m)")
    async def lottery(self, interaction: Interaction, buy_in: app_commands.Range[int, 1, 1_000_000], duration: str):
        # Permission check using bot-admin roles
        if not isinstance(interaction.user, discord.Member) or not is_bot_admin(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ This must be used in a text channel in a server.", ephemeral=True)
            return
        guild = interaction.guild
        guild_id = str(guild.id)
        if guild_id in self.active:
            await interaction.response.send_message("⚠️ There is already an active lottery in this server.", ephemeral=True)
            return

        td = parse_duration_str(duration)
        if not td:
            await interaction.response.send_message("❌ Invalid duration. Use formats like 15m, 2h, 1d, or combinations like 1h30m.", ephemeral=True)
            return
        # Optional: clamp to sensible bounds (1 minute to 30 days)
        if td < timedelta(minutes=1) or td > timedelta(days=30):
            await interaction.response.send_message("❌ Duration must be between 1 minute and 30 days.", ephemeral=True)
            return

        end_at = datetime.utcnow() + td
        view = LotteryView(self, guild, interaction.channel, int(buy_in), end_at)

        embed = view.make_embed()
        await interaction.response.send_message(embed=embed, view=view)
        try:
            msg = await interaction.original_response()
            view.message_id = msg.id
        except Exception:
            view.message_id = None

        # Schedule end task
        async def _end_after_delay():
            try:
                await asyncio.sleep(td.total_seconds())
                await view.end_and_award()
            finally:
                self.active.pop(guild_id, None)

        task = asyncio.create_task(_end_after_delay())
        self.active[guild_id] = {"view": view, "task": task}


async def setup(bot: commands.Bot):
    await bot.add_cog(Lottery(bot))
