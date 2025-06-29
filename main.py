import discord
import os
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TOKEN")
YOUR_USER_ID = 461008427326504970  # Replace with your actual Discord user ID

# --- Color Codes ---
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"]
CYAN = "\033[36m"

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
        # Load all cogs in ./cogs
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"{GREEN}✅ Loaded cog: {filename}{RESET}")
                except Exception as e:
                    print(f"{RED}❌ Failed to load {filename}:{RESET} {e}")

        # Optional: sync all commands to guilds for instant availability
        # Remove or comment this block if you want global sync instead
        for guild in self.guilds:
            try:
                await self.tree.sync(guild=guild)
                print(f"{CYAN}🔁 Synced commands to: {guild.name} ({guild.id}){RESET}")
            except Exception as e:
                print(f"{RED}❌ Sync failed for {guild.name}: {e}{RESET}")

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/help"))
        print(f"{YELLOW}Logged in as {self.user} (ID: {self.user.id}){RESET}")
        print(f"{CYAN}Bot ready at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
        print(f"{RED}Connected to guilds:{RESET}")
        for guild in self.guilds:
            print(f"{BLUE} - {guild.name} ({guild.id}){RESET}")
        print(f"{RED}Cogs Loaded: {list(self.cogs.keys())}{RESET}")

# Initialize bot
bot = JengBot()

# Slash command: /sync
@bot.tree.command(name="sync", description="Manually sync slash commands to this guild.")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != YOUR_USER_ID:
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    await bot.tree.sync(guild=interaction.guild)
    await interaction.response.send_message("✅ Commands synced to this server!", ephemeral=True)
    print(f"{GREEN}✅ Slash commands manually synced to {interaction.guild.name}{RESET}")

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

# Run the bot
if TOKEN:
    print(f"{GREEN}🔒 Token loaded successfully. Starting bot...{RESET}")
    bot.run(TOKEN)
else:
    print(f"{RED}❌ TOKEN not found. Please check your .env file.{RESET}")
