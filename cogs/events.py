import discord
from discord.ext import commands
from datetime import datetime
import pytz

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
    print(f"{RED}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class RSVPView(discord.ui.View):
    def __init__(self, creator, title, time, location, details, description="Click a button to RSVP!"):
        super().__init__(timeout=None)
        self.creator = creator
        self.title = title
        self.time = time
        self.location = location
        self.details = details
        self.description = description
        self.going = set()
        self.not_going = set()
        self.message = None
        self.created_at = datetime.now(pytz.timezone("US/Eastern"))  # store creation time

    def format_embed(self):
        embed = discord.Embed(title=f"📅 {self.title}", description=self.description, color=discord.Color.gold())
        embed.add_field(name="🕒 Time", value=self.time, inline=False)
        embed.add_field(name="📍 Location", value=self.location, inline=False)
        embed.add_field(name="📝 Details", value=self.details or "None", inline=False)
        embed.add_field(name="✅ Going", value="\n".join(u.mention for u in self.going) or "No one yet", inline=True)
        embed.add_field(name="❌ Not Going", value="\n".join(u.mention for u in self.not_going) or "No one yet", inline=True)
        
        created_str = self.created_at.strftime("%B %d, %I:%M %p ET")
        embed.set_footer(text=f"🕰️ Created at {created_str} by {self.creator.display_name}")
        return embed

    @discord.ui.button(label="✅ Going", style=discord.ButtonStyle.success)
    async def yes(self, button, interaction: discord.Interaction):
        self.not_going.discard(interaction.user)
        self.going.add(interaction.user)
        await self.update(interaction)

    @discord.ui.button(label="❌ Not Going", style=discord.ButtonStyle.danger)
    async def no(self, button, interaction: discord.Interaction):
        self.going.discard(interaction.user)
        self.not_going.add(interaction.user)
        await self.update(interaction)

    async def update(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.format_embed(), view=self)

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(
        name="event",
        description="Create an interactive RSVP event."
    )
    async def event(
        self,
        ctx: discord.ApplicationContext,
        title: str,
        time: str,
        location: str,
        details: str = "",
        description: str = "Click a button to RSVP!"
    ):
        await ctx.defer()
        debug_command(
            "event", ctx.author, ctx.guild,
            title=title,
            time=time,
            location=location,
            details=details,
            description=description
        )

        view = RSVPView(
            creator=ctx.author,
            title=title,
            time=time,
            location=location,
            details=details,
            description=description
        )

        embed = view.format_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

# --- Cog Setup ---
async def setup(bot):
    await bot.add_cog(Events(bot))
