import discord
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TOKEN")
YOUR_USER_ID = 461008427326504970  # Replace with your actual ID

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

# Bot Setup
bot = discord.Bot(intents=intents)

# Store deleted messages for /snipe
bot.sniped_messages = {}

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))
    print(f"{YELLOW}Logged in as {bot.user}{RESET}")
    print(f"{CYAN}Bot ready at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{RED}Connected to:{RESET}")
    for guild in bot.guilds:
        print(f"{BLUE} - {guild.name} ({guild.id}){RESET}")
    print(f"{RED}Cogs Loaded: {list(bot.cogs.keys())}{RESET}")

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    bot.sniped_messages[message.channel.id] = {
        "content": message.content,
        "author": message.author,
        "time": message.created_at
    }

@bot.slash_command(name="sync", description="Manually sync commands to this guild.")
async def sync_commands(ctx: discord.ApplicationContext):
    if ctx.author.id != YOUR_USER_ID:
        await ctx.respond("❌ You are not authorized to use this command.", ephemeral=True)
        return
    await bot.sync_commands()
    await ctx.respond("✅ Commands synced to this server!", ephemeral=True)

# Load all cogs on startup
@bot.event
async def setup_hook():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"{GREEN}Loaded cog: {filename}{RESET}")
            except Exception as e:
                print(f"{RED}❌ Failed to load {filename}:{RESET} {e}")

# Start the bot
if TOKEN:
    print(f"{GREEN}🔒 Token loaded successfully. Starting bot...{RESET}")
    bot.run(TOKEN)
else:
    print(f"{RED}❌ TOKEN not found. Please check your .env file.{RESET}")
