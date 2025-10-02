import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import json
import os

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

QUOTES_FILE = "quotes.json"

def load_quotes():
    if os.path.exists(QUOTES_FILE):
        with open(QUOTES_FILE, "r") as f:
            try:
                data = json.load(f)
            except Exception:
                # corrupted or invalid JSON -> reset to empty dict
                return {}
            # Ensure we return a dict keyed by guild id. If the file contains a list
            # (legacy format) or other type, normalize to an empty dict.
            if isinstance(data, dict):
                return data
            return {}
    return {}

def save_quotes(data):
    with open(QUOTES_FILE, "w") as f:
        # Ensure we're saving a dict
        if not isinstance(data, dict):
            data = {}
        json.dump(data, f, indent=4)

def debug_command(name, user, guild, **kwargs):
    gname = guild.name if guild else 'DM'
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{gname}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quotes = load_quotes()
        # Normalize loaded quotes to a dict keyed by guild id strings
        if not isinstance(self.quotes, dict):
            self.quotes = {}

    def get_guild_quotes(self, guild_id):
        # ensure guild_id is a string key
        gid = str(guild_id)
        if gid not in self.quotes or not isinstance(self.quotes.get(gid), list):
            self.quotes[gid] = []
        return self.quotes[gid]

    @app_commands.command(name="quote_add", description="Add a new quote.")
    @app_commands.describe(text="The quote text")
    async def quote_add(self, interaction: Interaction, text: str):
        debug_command("quote_add", interaction.user, interaction.guild, text=text)

        guild_id = str(interaction.guild.id)
        quote_list = self.get_guild_quotes(guild_id)
        quote_list.append(text)
        save_quotes(self.quotes)

        embed = Embed(title="✅ Quote Added", description=f"Quote #{len(quote_list)}: {text}", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_get", description="Get a random quote.")
    async def quote_get(self, interaction: Interaction):
        debug_command("quote_get", interaction.user, interaction.guild)

        guild_id = str(interaction.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if not quote_list:
            embed = Embed(title="❌ No Quotes", description="There are no quotes yet!", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        import random
        quote = random.choice(quote_list)
        embed = Embed(title="💬 Quote", description=quote, color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_list", description="View all saved quotes.")
    async def quote_list(self, interaction: Interaction):
        debug_command("quote_list", interaction.user, interaction.guild)

        guild_id = str(interaction.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if not quote_list:
            embed = Embed(title="❌ No Quotes", description="There are no quotes yet!", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        embed = Embed(title="📜 Quote List", color=discord.Color.gold())
        for i, quote in enumerate(quote_list, start=1):
            embed.add_field(name=f"#{i}", value=quote, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_edit", description="Edit a quote by number.")
    @app_commands.describe(index="Quote number to edit", new_text="New quote text")
    async def quote_edit(self, interaction: Interaction, index: int, new_text: str):
        debug_command("quote_edit", interaction.user, interaction.guild, index=index, new_text=new_text)

        guild_id = str(interaction.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if index < 1 or index > len(quote_list):
            embed = Embed(title="❌ Invalid Index", description="That quote doesn't exist.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        old = quote_list[index - 1]
        quote_list[index - 1] = new_text
        save_quotes(self.quotes)

        embed = Embed(
            title="✏️ Quote Edited",
            description=f"**Before:** {old}\n**After:** {new_text}",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_delete", description="Delete a quote by number.")
    @app_commands.describe(index="Quote number to delete")
    async def quote_delete(self, interaction: Interaction, index: int):
        debug_command("quote_delete", interaction.user, interaction.guild, index=index)

        guild_id = str(interaction.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if index < 1 or index > len(quote_list):
            embed = Embed(title="❌ Invalid Index", description="That quote doesn't exist.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        removed = quote_list.pop(index - 1)
        save_quotes(self.quotes)

        embed = Embed(title="🗑️ Quote Deleted", description=f"Deleted quote: {removed}", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(Quotes(bot))
