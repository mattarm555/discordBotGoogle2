import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed, ui
import os
import json

QUOTE_FILE = "quotes.json"

# Color codes for debug output
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
BLINK = "\033[5m"
REVERSE = "\033[7m"
HIDDEN = "\033[8m"
RED = "\033[31m"

def load_quote_data():
    if os.path.exists(QUOTE_FILE):
        try:
            with open(QUOTE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_quote_data(data):
    with open(QUOTE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def debug_command(name, user, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, val in kwargs.items():
            print(f"{RED}  {key.capitalize()}: {val}{RESET}")

class QuotePagination(ui.View):
    def __init__(self, quotes, per_page=5):
        super().__init__(timeout=60)
        self.quotes = quotes
        self.per_page = per_page
        self.page = 0
        self.max_pages = (len(quotes) - 1) // per_page + 1

    def get_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        embed = discord.Embed(
            title=f"📜 Saved Quotes (Page {self.page + 1}/{self.max_pages})",
            description="\n".join([f"**{i+1}.** {q}" for i, q in enumerate(self.quotes[start:end], start=start)]),
            color=discord.Color.blurple()
        )
        return embed

    @ui.button(label="⬅️ Prev", style=discord.ButtonStyle.blurple)
    async def prev(self, interaction: Interaction, button: ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @ui.button(label="➡️ Next", style=discord.ButtonStyle.blurple)
    async def next(self, interaction: Interaction, button: ui.Button):
        if self.page < self.max_pages - 1:
            self.page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quotes = load_quote_data()

    def ensure_guild_entry(self, guild_id):
        if str(guild_id) not in self.quotes:
            self.quotes[str(guild_id)] = []

    @app_commands.command(name="quote_add", description="Add a new quote.")
    @app_commands.describe(text="The quote and who said it.")
    async def quote_add(self, interaction: Interaction, text: str):
        debug_command("quote_add", interaction.user, text=text)
        guild_id = str(interaction.guild.id)
        self.ensure_guild_entry(guild_id)
        self.quotes[guild_id].append(text)
        save_quote_data(self.quotes)
        embed = Embed(title="✅ Quote Saved", description="Your quote was added!", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_get", description="Get a random quote.")
    async def quote_get(self, interaction: Interaction):
        debug_command("quote_get", interaction.user)
        guild_id = str(interaction.guild.id)
        if guild_id not in self.quotes or not self.quotes[guild_id]:
            embed = Embed(title="❌ No Quotes", description="There are no quotes saved for this server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return
        import random
        quote = random.choice(self.quotes[guild_id])
        embed = Embed(title="📜 Random Quote", description=f"\"{quote}\"", color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_list", description="Lists all saved quotes with pagination.")
    async def quote_list(self, interaction: Interaction):
        debug_command("quote_list", interaction.user)
        guild_id = str(interaction.guild.id)

        if guild_id not in self.quotes or not self.quotes[guild_id]:
            embed = Embed(title="❌ No Quotes", description="There are no quotes saved for this server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        view = QuotePagination(self.quotes[guild_id])
        await interaction.response.send_message(embed=view.get_embed(), view=view)

    @app_commands.command(name="quote_edit", description="Edit an existing quote.")
    @app_commands.describe(index="The quote number to edit", new_text="The new quote text")
    async def quote_edit(self, interaction: Interaction, index: int, new_text: str):
        debug_command("quote_edit", interaction.user, index=index, new_text=new_text)
        guild_id = str(interaction.guild.id)

        if guild_id not in self.quotes or index < 1 or index > len(self.quotes[guild_id]):
            embed = Embed(title="❌ Invalid Quote", description="Quote number is invalid.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        self.quotes[guild_id][index - 1] = new_text
        save_quote_data(self.quotes)
        embed = Embed(title="✏️ Quote Updated", description=f"Quote #{index} has been updated.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quote_delete", description="Delete a quote by its number.")
    @app_commands.describe(index="The quote number to delete")
    async def quote_delete(self, interaction: Interaction, index: int):
        debug_command("quote_delete", interaction.user, index=index)
        guild_id = str(interaction.guild.id)

        if guild_id not in self.quotes or index < 1 or index > len(self.quotes[guild_id]):
            embed = Embed(title="❌ Invalid Quote", description="Quote number is invalid.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            return

        removed = self.quotes[guild_id].pop(index - 1)
        save_quote_data(self.quotes)
        embed = Embed(
            title="🗑️ Quote Deleted",
            description=f"Removed quote #{index}:\n\n\"{removed}\"",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)

# Cog setup
async def setup(bot):
    await bot.add_cog(Quotes(bot))

