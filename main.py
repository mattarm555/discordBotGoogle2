import discord
import logging
discord.utils.setup_logging(level=logging.DEBUG)
import os
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime
 
# Load environment variables
load_dotenv()
TOKEN = os.getenv("TOKEN")
YOUR_USER_ID = 461008427326504970  # 👈 Your actual user ID

# --- Color Codes ---
RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# --- Bot Setup ---
class JengBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.sniped_messages = {}
        self._did_global_sync = False

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Provide user-friendly permission errors for app_commands.check decorators.
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) if str(error) else "❌ You do not have permission to use this command."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return

        # Fallback: surface a minimal error message without leaking internals.
        try:
            if interaction.response.is_done():
                await interaction.followup.send("⚠️ Something went wrong while running that command.", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Something went wrong while running that command.", ephemeral=True)
        except Exception:
            pass

    async def setup_hook(self):
        # Load cogs
        loaded: list[str] = []
        failed: list[tuple[str, str]] = []
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and filename != "__init__.py":
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"{GREEN}✅ Loaded cog: {filename}{RESET}")
                    loaded.append(filename)
                except Exception as e:
                    print(f"{RED}❌ Failed to load {filename}:{RESET} {e}")
                    failed.append((filename, str(e)))

        if loaded:
            print(f"{GREEN}🧩 Cogs loaded ({len(loaded)}):{RESET} {', '.join(sorted(loaded))}")
        if failed:
            print(f"{RED}🧩 Cogs failed ({len(failed)}):{RESET}")
            for name, err in failed:
                print(f"{RED} - {name}:{RESET} {err}")

        # Register /synccommands command
        self.tree.add_command(self.sync_commands)

    async def on_ready(self):
        # Avoid re-syncing on reconnects
        if not self._did_global_sync:
            try:
                synced = await self.tree.sync()
                print(f"{GREEN}🔁 Global slash commands synced: {len(synced)}{RESET}")
            except Exception as e:
                print(f"{RED}⚠️ Slash sync failed: {e}{RESET}")
            self._did_global_sync = True

        # Presence / status
        # {len(self.guilds)} servers
        try:
            activity_name = f"/help"
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.listening, name=activity_name)
            )
        except Exception as e:
            print(f"{YELLOW}⚠️ Failed to set presence: {e}{RESET}")

        print(f"{YELLOW}🔓 Logged in as {self.user}{RESET}")
        print(f"{CYAN}📅 Ready at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
        print(f"{RED}🌍 Connected to:{RESET}")
        for guild in self.guilds:
            print(f"{BLUE} - {guild.name} ({guild.id}){RESET}")
        print(f"{RED}🔧 Cogs Loaded: {list(self.cogs.keys())}{RESET}")

    @app_commands.command(name="synccommands", description="Manually sync slash commands to this server.")
    async def sync_commands(self, interaction: discord.Interaction):
        if interaction.user.id != YOUR_USER_ID:
            await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
            return
        try:
            synced = await self.tree.sync(guild=interaction.guild)
            await interaction.response.send_message(f"✅ Synced {len(synced)} commands to this server.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Sync failed: {e}", ephemeral=True)


# --- Prefix fallback sync (use if /synccommands mismatches) ---
@commands.command(name="syncguild")
async def syncguild(ctx: commands.Context):
    """Owner-only: sync slash commands to the current guild.

    This exists as a fallback in case the /synccommands slash command has a signature mismatch
    and can't be invoked.
    """
    if ctx.author.id != YOUR_USER_ID:
        return
    if not ctx.guild:
        await ctx.send("❌ Use this in a server.")
        return
    try:
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ Synced {len(synced)} commands to this server.")
    except Exception as e:
        await ctx.send(f"⚠️ Sync failed: {e}")

# Initialize bot
bot = JengBot()
bot.add_command(syncguild)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    bot.sniped_messages[message.channel.id] = {
        "content": message.content,
        "author": message.author,
        "time": message.created_at
    }

# --- Run the bot ---
if TOKEN:
    print(f"{GREEN}🔒 Token loaded. Starting bot...{RESET}")
    # Show Twitch credential status (do not print secret values)
    TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
    TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')
    if TWITCH_CLIENT_ID:
        print(f"{GREEN}🔒 TWITCH_CLIENT_ID loaded.{RESET}")
    else:
        print(f"{YELLOW}⚠️ TWITCH_CLIENT_ID not set.{RESET}")
    if TWITCH_CLIENT_SECRET:
        print(f"{GREEN}🔒 TWITCH_CLIENT_SECRET loaded.{RESET}")
    else:
        print(f"{YELLOW}⚠️ TWITCH_CLIENT_SECRET not set.{RESET}")
    # Show YouTube API key status (do not print the key itself)
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
    if YOUTUBE_API_KEY:
        print(f"{GREEN}🔒 YOUTUBE_API_KEY loaded.{RESET}")
    else:
        print(f"{YELLOW}⚠️ YOUTUBE_API_KEY not set.{RESET}")
    bot.run(TOKEN)
else:
    print(f"{RED}❌ TOKEN not found in .env{RESET}")
