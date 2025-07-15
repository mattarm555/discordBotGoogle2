import discord
from discord.ext import commands
import json
import os
import random

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
            return json.load(f)
    return {}

def save_quotes(data):
    with open(QUOTES_FILE, "w") as f:
        json.dump(data, f, indent=4)

def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quotes = load_quotes()

    def get_guild_quotes(self, guild_id):
        if guild_id not in self.quotes:
            self.quotes[guild_id] = []
        return self.quotes[guild_id]

    @commands.slash_command(name="quote_add", description="Add a new quote.")
    async def quote_add(self, ctx: discord.ApplicationContext, text: str):
        debug_command("quote_add", ctx.author, ctx.guild, text=text)

        guild_id = str(ctx.guild.id)
        quote_list = self.get_guild_quotes(guild_id)
        quote_list.append(text)
        save_quotes(self.quotes)

        embed = discord.Embed(title="✅ Quote Added", description=f"Quote #{len(quote_list)}: {text}", color=discord.Color.green())
        await ctx.respond(embed=embed)

    @commands.slash_command(name="quote_get", description="Get a random quote.")
    async def quote_get(self, ctx: discord.ApplicationContext):
        debug_command("quote_get", ctx.author, ctx.guild)

        guild_id = str(ctx.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if not quote_list:
            embed = discord.Embed(title="❌ No Quotes", description="There are no quotes yet!", color=discord.Color.red())
            await ctx.respond(embed=embed)
            return

        quote = random.choice(quote_list)
        embed = discord.Embed(title="💬 Quote", description=quote, color=discord.Color.blurple())
        await ctx.respond(embed=embed)

    @commands.slash_command(name="quote_list", description="View all saved quotes.")
    async def quote_list(self, ctx: discord.ApplicationContext):
        debug_command("quote_list", ctx.author, ctx.guild)

        guild_id = str(ctx.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if not quote_list:
            embed = discord.Embed(title="❌ No Quotes", description="There are no quotes yet!", color=discord.Color.red())
            await ctx.respond(embed=embed)
            return

        embed = discord.Embed(title="📜 Quote List", color=discord.Color.gold())
        for i, quote in enumerate(quote_list, start=1):
            embed.add_field(name=f"#{i}", value=quote, inline=False)

        await ctx.respond(embed=embed)

    @commands.slash_command(name="quote_edit", description="Edit a quote by number.")
    async def quote_edit(self, ctx: discord.ApplicationContext, index: int, new_text: str):
        debug_command("quote_edit", ctx.author, ctx.guild, index=index, new_text=new_text)

        guild_id = str(ctx.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if index < 1 or index > len(quote_list):
            embed = discord.Embed(title="❌ Invalid Index", description="That quote doesn't exist.", color=discord.Color.red())
            await ctx.respond(embed=embed)
            return

        old = quote_list[index - 1]
        quote_list[index - 1] = new_text
        save_quotes(self.quotes)

        embed = discord.Embed(
            title="✏️ Quote Edited",
            description=f"**Before:** {old}\n**After:** {new_text}",
            color=discord.Color.orange()
        )
        await ctx.respond(embed=embed)

    @commands.slash_command(name="quote_delete", description="Delete a quote by number.")
    async def quote_delete(self, ctx: discord.ApplicationContext, index: int):
        debug_command("quote_delete", ctx.author, ctx.guild, index=index)

        guild_id = str(ctx.guild.id)
        quote_list = self.get_guild_quotes(guild_id)

        if index < 1 or index > len(quote_list):
            embed = discord.Embed(title="❌ Invalid Index", description="That quote doesn't exist.", color=discord.Color.red())
            await ctx.respond(embed=embed)
            return

        removed = quote_list.pop(index - 1)
        save_quotes(self.quotes)

        embed = discord.Embed(title="🗑️ Quote Deleted", description=f"Deleted quote: {removed}", color=discord.Color.red())
        await ctx.respond(embed=embed)

# --- Cog setup ---
async def setup(bot):
    await bot.add_cog(Quotes(bot))
