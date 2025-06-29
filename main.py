import discord
import os
from dotenv import load_dotenv
from datetime import datetime
from discord.ext import commands

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TOKEN")
YOUR_USER_ID = 461008427326504970  # Replace with your actual user ID

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.voice_states = True

# Custom bot class
class JengBot(discord.Bot):
    def __init__(self):
        super().__init__(intents=intents)
        self.sniped_messages = {}

    async def setup_hook(self):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"{GREEN}Loaded cog: {filename}{RESET}")
                except Exception as e:
                    print(f"{RED}❌ Failed to load {filename}:{RESET} {e}")

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))
        print(f"{YELLOW}Logged in as {self.user}{RESET}")
        print(f"{CYAN}Bot ready at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
        print(f"{RED}Connected to:{RESET}")
        for guild in self.guilds:
            print(f"{BLUE} - {guild.name} ({guild.id}){RESET}")
        print(f"{RED}Cogs Loaded: {list(self.cogs.keys())}{RESET}")

bot = JengBot()

# Slash command to sync commands
@bot.slash_command(name="sync", description="Manually sync commands to this guild.")
async def sync(ctx: discord.ApplicationContext):
    if ctx.author.id != YOUR_USER_ID:
        await ctx.respond("❌ You are not authorized to use this command.", ephemeral=True)
        return
    await bot.sync_commands()
    await ctx.respond("✅ Commands synced to this server!", ephemeral=True)

# Snipe deleted messages
@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    bot.sniped_messages[message.channel.id] = {
        "content": message.content,
        "author": message.author,
        "time": message.created_at
    }

# Start the bot
if TOKEN:
    print(f"{GREEN}🔒 Token loaded successfully. Starting bot...{RESET}")
    bot.run(TOKEN)
else:
    print(f"{RED}❌ TOKEN not found. Please check your .env file.{RESET}")
