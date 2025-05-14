import discord
import os
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TOKEN")

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

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.voice_states = True

# Bot Setup
class JengBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.sniped_messages = {}

    async def setup_hook(self):
        TEST_GUILD = discord.Object(id=799649221053382656)  # Your test server

        # Load all cogs from the cogs/ directory with error handling
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

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return

    bot.sniped_messages[message.channel.id] = {
        "content": message.content,
        "author": message.author,
        "time": message.created_at
    }

# Token check and launch
if TOKEN:
    print(f"{GREEN}🔒 Token loaded successfully. Starting bot...{RESET}")
    bot.run(TOKEN)
else:
    print(f"{RED}❌ TOKEN not found. Please check your .env file.{RESET}")
