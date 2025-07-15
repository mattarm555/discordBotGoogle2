import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction, Embed
import random
from datetime import datetime
import pytz
from utils.debug import debug_command
import asyncio

# --- Color Codes ---
RESET = "\033[0m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class HelpPaginator(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=60)
        self.pages = pages
        self.index = 0

    def get_embed(self):
        return self.pages[self.index]

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.blurple)
    async def prev_page(self, button, interaction: discord.Interaction):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.blurple)
    async def next_page(self, button, interaction: discord.Interaction):
        if self.index < len(self.pages) - 1:
            self.index += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.league_champions = [
            "Ahri", "Akali", "Aatrox", "Alistar", "Amumu", "Anivia", "Annie", "Aphelios", "Ashe",
            "Aurelion Sol", "Azir", "Bard", "Bel'Veth", "Blitzcrank", "Brand", "Braum", "Caitlyn", "Camille",
            "Cassiopeia", "Cho'Gath", "Corki", "Darius", "Diana", "Dr. Mundo", "Draven", "Ekko",
            "Elise", "Evelynn", "Ezreal", "Fiddlesticks", "Fiora", "Fizz", "Galio", "Gangplank",
            "Garen", "Gnar", "Gragas", "Graves", "Gwen", "Hecarim", "Heimerdinger", "Hwei", "Illaoi",
            "Irelia", "Ivern", "Janna", "Jarvan IV", "Jax", "Jayce", "Jhin", "Jinx", "Kai'Sa",
            "Kalista", "Karma", "Karthus", "Kassadin", "Katarina", "Kayle", "Kayn", "Kennen",
            "Kha'Zix", "Kindred", "Kled", "Kog'Maw", "LeBlanc", "Lee Sin", "Leona", "Lillia",
            "Lissandra", "Lucian", "Lulu", "Lux", "Malphite", "Malzahar", "Maokai", "Mel", "Milio", "Master Yi",
            "Miss Fortune", "Mordekaiser", "Morgana", "Naafiri", "Nami", "Nasus", "Nautilus", "Neeko",
            "Nidalee", "Nilah", "Nocturne", "Nunu & Willump", "Olaf", "Orianna", "Ornn", "Pantheon",
            "Poppy", "Pyke", "Qiyana", "Quinn", "Rakan", "Rammus", "Rek'Sai", "Rell", "Renata Glasc",
            "Renekton", "Rengar", "Riven", "Rumble", "Ryze", "Samira", "Sejuani", "Senna", "Seraphine",
            "Sett", "Shaco", "Shen", "Shyvana", "Singed", "Sion", "Sivir", "Skarner", "Smolder", "Sona",
            "Soraka", "Swain", "Sylas", "Syndra", "Tahm Kench", "Taliyah", "Talon", "Taric",
            "Teemo", "Thresh", "Tristana", "Trundle", "Tryndamere", "Twisted Fate", "Twitch",
            "Udyr", "Urgot", "Varus", "Vayne", "Veigar", "Kel'Koz", "Vex", "Vi", "Viego",
            "Viktor", "Vladimir", "Volibear", "Warwick", "Wukong", "Xayah", "Xerath", "Xin Zhao",
            "Yasuo", "Yone", "Yorick", "Yuumi", "Zac", "Zed", "Zeri", "Ziggs", "Zilean", "Zoe",
            "Zyra"
        ]

    @commands.slash_command(name="champ", description="Randomly selects a League of Legends champion.")
    async def champ(self, ctx: discord.ApplicationContext):
        debug_command("champ", ctx.author, ctx.guild)

        if not self.league_champions:
            embed = discord.Embed(title="⚠ No Champions", description="The champion list is currently empty.", color=discord.Color.orange())
            await ctx.respond(embed=embed)
            return

        champion = random.choice(self.league_champions)
        embed = discord.Embed(
            title="🎮 Random League Champion",
            description=f"Your champion is: **{champion}**!",
            color=discord.Color.purple()
        )
        await ctx.respond(embed=embed)

    @commands.slash_command(name="spam", description="Mentions a user multiple times.")
    async def spam(self, ctx: discord.ApplicationContext, user: discord.Member, count: int = 1):
        debug_command("spam", ctx.author, ctx.guild, target=user.display_name, count=count)

        if count > 20:
            embed = discord.Embed(title="⚠ Limit Exceeded", description="Please enter a number **20 or lower**.", color=discord.Color.red())
            await ctx.respond(embed=embed, ephemeral=True)
            return

        await ctx.respond(f"{user.mention} wya")
        for _ in range(count - 1):
            await asyncio.sleep(0.75)
            await ctx.channel.send(f"{user.mention} wya")

    @commands.slash_command(name="snipe", description="Retrieves the last deleted message in the current channel.")
    async def snipe(self, ctx: discord.ApplicationContext):
        debug_command("snipe", ctx.author, ctx.guild)

        sniped_messages = self.bot.sniped_messages
        snipe_data = sniped_messages.get(ctx.channel.id)

        if not snipe_data:
            await ctx.respond(embed=discord.Embed(title="❌ Nothing to Snipe", description="No message to snipe here.", color=discord.Color.red()), ephemeral=True)
            return

        embed = discord.Embed(
            title="Get sniped gang",
            description=snipe_data["content"],
            color=discord.Color.dark_red(),
            timestamp=snipe_data["time"]
        )
        embed.set_author(name=snipe_data["author"].display_name, icon_url=snipe_data["author"].avatar.url if snipe_data["author"].avatar else None)
        await ctx.respond(embed=embed)

    @commands.slash_command(name="help", description="Displays a list of available commands.")
    async def help(self, ctx: discord.ApplicationContext):
        debug_command("help", ctx.author, ctx.guild)

        pages = []

        # Music
        music_embed = discord.Embed(title="🎵 Music Commands", color=discord.Color.blue())
        music_embed.add_field(name="/play <url>", value="Plays a song or playlist from the given URL.", inline=False)
        music_embed.add_field(name="/queue", value="Shows the current music queue.", inline=False)
        music_embed.add_field(name="/skip", value="Skips the current song.", inline=False)
        music_embed.add_field(name="/stop", value="Pauses the music.", inline=False)
        music_embed.add_field(name="/start", value="Resumes paused music.", inline=False)
        music_embed.add_field(name="/leave", value="Clears the queue and makes the bot leave the voice channel.", inline=False)
        music_embed.add_field(name="/playplaylist", value="Play a saved playlist.", inline=False)
        music_embed.add_field(name="/saveplaylist", value="Save a custom playlist under a chosen name.", inline=False)
        music_embed.add_field(name="/removeplaylist", value="Remove a saved playlist.", inline=False)
        music_embed.add_field(name="/listplaylists", value="Lists saved playlists.", inline=False)
        music_embed.add_field(name="/queueshuffle", value="Shuffles the current queue.", inline=False)
        music_embed.set_footer(text="Page 1/5")
        pages.append(music_embed)

        # XP
        xp_embed = discord.Embed(title="📈 XP System Commands", color=discord.Color.green())
        xp_embed.add_field(name="/level", value="Shows your XP level and server rank.", inline=False)
        xp_embed.add_field(name="/leaderboard", value="Shows the leaders in XP in this server.", inline=False)
        xp_embed.add_field(name="/xpset <amount>", value="Sets the amount of XP gained per message.", inline=False)
        xp_embed.add_field(name="/xpblock <channel>", value="Blocks XP in the given channel.", inline=False)
        xp_embed.add_field(name="/xpunblock <channel>", value="Unblocks XP in the given channel.", inline=False)
        xp_embed.add_field(name="/xpconfig", value="Shows the current XP settings.", inline=False)
        xp_embed.set_footer(text="Page 2/5")
        pages.append(xp_embed)

        # Misc
        misc_embed = discord.Embed(title="😂 Miscellaneous Commands", color=discord.Color.purple())
        misc_embed.add_field(name="/champ", value="Selects a random champion.", inline=False)
        misc_embed.add_field(name="/spam <user> <num>", value="Spams a user a specified number of times.", inline=False)
        misc_embed.add_field(name="/askjeng <prompt> <model>", value="Ask an AI that runs locally on Jeng's computer!", inline=False)
        misc_embed.add_field(name="/warmup <model>", value="Warms up a specific ollama model.", inline=False)
        misc_embed.set_footer(text="Page 3/5")
        pages.append(misc_embed)

        # Community
        community_embed = discord.Embed(title="📊 Community Tools", color=discord.Color.orange())
        community_embed.add_field(name="/poll", value="Create a poll with emoji-based voting.", inline=False)
        community_embed.add_field(name="/event", value="Create an RSVP event for members.", inline=False)
        community_embed.add_field(name="/welcomeconfig", value="Shows server's welcoming configuration.", inline=False)
        community_embed.add_field(name="/setwelcome", value="Allows user to configure a welcoming system.", inline=False)
        community_embed.set_footer(text="Page 4/5")
        pages.append(community_embed)

        # Quotes
        quotes_embed = discord.Embed(title="💬 Quote System", color=discord.Color.teal())
        quotes_embed.add_field(name="/quote_add", value="Add a new quote.", inline=False)
        quotes_embed.add_field(name="/quote_get", value="Get a random quote.", inline=False)
        quotes_embed.add_field(name="/quote_list", value="View paginated list of quotes.", inline=False)
        quotes_embed.add_field(name="/quote_edit <index> <new_text>", value="Edit a quote by number.", inline=False)
        quotes_embed.add_field(name="/quote_delete <index>", value="Delete a quote by number.", inline=False)
        quotes_embed.set_footer(text="Page 5/5")
        pages.append(quotes_embed)

        try:
            view = HelpPaginator(pages)
            await ctx.author.send(embed=pages[0], view=view)

            confirmation = discord.Embed(
                title="📬 Help Sent!",
                description="Check your DMs for a list of commands.",
                color=discord.Color.green()
            )
            await ctx.respond(embed=confirmation, ephemeral=True)

        except discord.Forbidden:
            error = discord.Embed(
                title="❌ Couldn't Send Help",
                description="Your DMs are closed! Please enable them and try again.",
                color=discord.Color.red()
            )
            await ctx.respond(embed=error, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Misc(bot))
