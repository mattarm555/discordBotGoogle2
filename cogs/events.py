import discord
from discord.ext import commands
from discord import Interaction, Embed, ui
from datetime import datetime
import pytz

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

def debug_command(name, user, guild, **kwargs):
    print(f"{RED}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

class RSVPView(ui.View):
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
        self.created_at = datetime.now(pytz.timezone("US/Eastern"))

    def format_embed(self):
        embed = Embed(title=f"📅 {self.title}", description=self.description, color=discord.Color.gold())
        embed.add_field(name="🕒 Time", value=self.time, inline=False)
        embed.add_field(name="📍 Location", value=self.location, inline=False)
        embed.add_field(name="📝 Details", value=self.details or "None", inline=False)
        embed.add_field(name="✅ Going", value="\n".join(u.mention for u in self.going) or "No one yet", inline=True)
        embed.add_field(name="❌ Not Going", value="\n".join(u.mention for u in self.not_going) or "No one yet", inline=True)
        created_str = self.created_at.strftime("%B %d, %I:%M %p ET")
        embed.set_footer(text=f"🕰️ Created at {created_str} by {self.creator.display_name}")
        return embed

    @ui.button(label="✅ Going", style=discord.ButtonStyle.success)
    async def yes(self, interaction: Interaction, button: ui.Button):
        self.not_going.discard(interaction.user)
        self.going.add(interaction.user)
        await self.update(interaction)

    @ui.button(label="❌ Not Going", style=discord.ButtonStyle.danger)
    async def no(self, interaction: Interaction, button: ui.Button):
        self.going.discard(interaction.user)
        self.not_going.add(interaction.user)
        await self.update(interaction)

    async def update(self, interaction: Interaction):
        await interaction.response.edit_message(embed=self.format_embed(), view=self)

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="event", description="Create an interactive RSVP event.")
    async def event(self, ctx: discord.ApplicationContext,
                    title: discord.Option(str, description="Event title"),
                    time: discord.Option(str, description="When is the event?"),
                    location: discord.Option(str, description="Where is it?"),
                    details: discord.Option(str, description="More information", default=""),
                    description: discord.Option(str, description="Embed header", default="Click a button to RSVP!")):

        debug_command("event", ctx.user, ctx.guild,
                      title=title, time=time, location=location,
                      details=details, description=description)

        view = RSVPView(
            creator=ctx.user,
            title=title,
            time=time,
            location=location,
            details=details,
            description=description
        )

        embed = view.format_embed()
        msg = await ctx.respond(embed=embed, view=view)
        view.message = await msg.original_response()

# --- Cog Setup ---
async def setup(bot):
    await bot.add_cog(Events(bot))
