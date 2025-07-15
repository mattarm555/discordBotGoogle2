import discord
import os
from discord.ext import commands
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

    async def setup_hook(self):
        # Load cogs
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and filename != "__init__.py":
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"{GREEN}✅ Loaded cog: {filename}{RESET}")
                except Exception as e:
                    print(f"{RED}❌ Failed to load {filename}:{RESET} {e}")

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))
        print(f"{YELLOW}🔓 Logged in as {self.user}{RESET}")
        print(f"{CYAN}📅 Ready at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
        print(f"{RED}🌍 Connected to:{RESET}")
        for guild in self.guilds:
            print(f"{BLUE} - {guild.name} ({guild.id}){RESET}")
        print(f"{RED}🔧 Cogs Loaded: {list(self.cogs.keys())}{RESET}")

# Initialize bot
bot = JengBot()

@bot.slash_command(name="sync", description="Manually sync slash commands to this server.")
async def sync_commands(ctx):
    if ctx.author.id != YOUR_USER_ID:
        await ctx.respond("❌ You are not authorized.", ephemeral=True)
        return
    try:
        synced = await bot.sync_commands()
        await ctx.respond(f"✅ Synced {len(synced)} commands to this server.", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"⚠️ Sync failed: {e}", ephemeral=True)

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
    bot.run(TOKEN)
else:
    print(f"{RED}❌ TOKEN not found in .env{RESET}")
