import discord
import json
import os
from discord.ext import commands
from discord import app_commands, Interaction, Embed

from utils.economy import get_balance, set_balance
from utils.rebirth import (
    get_rebirth_cost,
    get_required_rebirth_cost,
    set_rebirth_cost,
    increment_rebirth_count,
    get_rebirth_multiplier,
    get_rebirth_count,
)
from utils.debug import debug_command

SHOP_INV_FILE = "shop_inventory.json"  # { guild_id: { user_id: { item_name: count } } }


class Rebirth(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setrebirthcost", description="Admin: Set how many coins are required to /rebirth in this server.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(cost="Coins required to rebirth")
    async def set_rebirth_cost(self, interaction: Interaction, cost: int):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        try:
            cost_int = int(cost)
        except Exception:
            await interaction.response.send_message(
                embed=Embed(title="❌ Invalid Value", description="Cost must be an integer.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        if cost_int < 0:
            await interaction.response.send_message(
                embed=Embed(title="❌ Invalid Value", description="Cost must be ≥ 0.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        # sanity cap
        if cost_int > 10_000_000_000:
            await interaction.response.send_message(
                embed=Embed(title="❌ Too Large", description="Cost must be ≤ 10,000,000,000 coins.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        debug_command('setrebirthcost', interaction.user, interaction.guild, cost=cost_int)
        set_rebirth_cost(guild.id, cost_int)
        await interaction.response.send_message(
            embed=Embed(title="✅ Rebirth Cost Updated", description=f"Base rebirth cost set to **{cost_int:,}** coins for this server. (Cost doubles each rebirth.)", color=discord.Color.green()),
            ephemeral=True,
        )

    @app_commands.command(name="rebirth", description="Reset your coins to gain a multiplier on /work, /daily, and shop passive income.")
    @app_commands.describe(confirm="Set true to confirm rebirth (this resets your coins)")
    async def rebirth(self, interaction: Interaction, confirm: bool = False):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)
        gid = str(guild.id)

        base_cost = get_rebirth_cost(gid)
        cost = get_required_rebirth_cost(gid, uid)

        bal = get_balance(uid, guild_id=gid)
        current_count = get_rebirth_count(gid, uid)
        current_mult = get_rebirth_multiplier(gid, uid)

        if not confirm:
            remaining = max(0, int(cost) - int(bal))
            extra = f"You still need **{remaining:,}** more coins to rebirth.\n\n" if remaining > 0 else ""
            desc = (
                f"Rebirthing will **wipe your shop inventory** in this server and charge the rebirth cost.\n"
                f"You keep any extra coins above the cost.\n\n"
                f"Cost (this rebirth): **{cost:,}** coins\n"
                f"Base cost: **{int(base_cost):,}** coins (doubles each rebirth)\n"
                f"Your balance: **{bal:,}** coins\n\n"
                f"{extra}"
                f"Current rebirths: **{current_count}** (multiplier **x{current_mult}**)\n"
                f"After rebirth: multiplier becomes **x{current_mult * 2}**\n\n"
                "Run `/rebirth confirm:true` to confirm."
            )
            await interaction.response.send_message(
                embed=Embed(title="🔁 Confirm Rebirth", description=desc, color=discord.Color.blurple()),
                ephemeral=True,
            )
            return

        if bal < cost:
            await interaction.response.send_message(
                embed=Embed(
                    title="💸 Not Enough Coins",
                    description=f"You need **{cost:,}** coins to rebirth, but you only have **{bal:,}**.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        debug_command('rebirth', interaction.user, interaction.guild, cost=cost, balance=bal)

        # Deduct cost but keep any excess coins
        new_balance = max(0, int(bal) - int(cost))
        set_balance(uid, new_balance, guild_id=gid)

        # Wipe shop inventory for this user in this guild
        try:
            if os.path.exists(SHOP_INV_FILE):
                with open(SHOP_INV_FILE, "r", encoding="utf-8") as f:
                    inv = json.load(f)
            else:
                inv = {}
            if isinstance(inv, dict):
                g = inv.get(gid)
                if isinstance(g, dict):
                    g.pop(uid, None)
                    if not g:
                        inv.pop(gid, None)
                with open(SHOP_INV_FILE, "w", encoding="utf-8") as f:
                    json.dump(inv, f, indent=4)
        except Exception:
            pass

        new_count = increment_rebirth_count(gid, uid)
        new_mult = get_rebirth_multiplier(gid, uid)

        desc = (
            f"✅ **Rebirth complete!**\n\n"
            f"Rebirths: **{new_count}**\n"
            f"Multiplier: **x{new_mult}**\n\n"
            f"New balance: **{new_balance:,}** coins\n"
            "Your shop inventory was wiped for this server.\n\n"
            "This multiplier affects: **/daily**, **/work**, and **shop passive income**.\n"
            "It does **not** affect games like **blackjack** or **slots**."
        )
        await interaction.response.send_message(
            embed=Embed(title="🔁 Rebirth", description=desc, color=discord.Color.green())
        )

    @app_commands.command(name="rebirthinfo", description="View your rebirths, multiplier, and the server rebirth cost.")
    async def rebirthinfo(self, interaction: Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()),
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)
        gid = str(guild.id)
        cost = get_required_rebirth_cost(gid, uid)
        bal = get_balance(uid, guild_id=gid)
        count = get_rebirth_count(gid, uid)
        mult = get_rebirth_multiplier(gid, uid)
        remaining = max(0, int(cost) - int(bal))

        desc = (
            f"Rebirths: **{count}**\n"
            f"Multiplier: **x{mult}**\n\n"
            f"Rebirth cost (next): **{int(cost):,}** coins\n"
            f"Your balance: **{int(bal):,}** coins\n"
            + (f"You need **{remaining:,}** more coins to rebirth.\n\n" if remaining > 0 else "You can rebirth now.\n\n")
            + "To rebirth: `/rebirth confirm:true`"
        )
        await interaction.response.send_message(
            embed=Embed(title="🔁 Rebirth Info", description=desc, color=discord.Color.blurple()),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Rebirth(bot))
