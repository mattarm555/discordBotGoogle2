import discord
from discord.ext import commands
from discord import Interaction, Embed
import aiohttp
import requests
import time
from json.decoder import JSONDecodeError

# --- Color Codes ---
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

OLLAMA_URL = "https://domestic-other-basis-valuation.trycloudflare.com"
DEFAULT_MODEL = "mistral"

def debug_command(name, user, guild, **kwargs):
    print(f"{GREEN}[COMMAND] /{name}{RESET} triggered by {YELLOW}{user.display_name}{RESET} in {BLUE}{guild.name}{RESET}")
    if kwargs:
        print(f"{CYAN}Input:{RESET}")
        for key, value in kwargs.items():
            print(f"  {key}: {value}")

async def is_ollama_online() -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
                return resp.status == 200
    except Exception:
        return False

class JengGPT(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="askjeng", description="Ask your local AI anything.")
    async def askjeng(self, ctx: discord.ApplicationContext,
                      prompt: discord.Option(str, description="What do you want to ask JengGPT?"),
                      model: discord.Option(str, description="Model (mistral, llama2, etc.)", default=DEFAULT_MODEL)):
        debug_command("askjeng", ctx.user, ctx.guild, prompt=prompt, model=model)

        await ctx.defer()

        if not await is_ollama_online():
            await ctx.respond(embed=Embed(
                title="🛑 JengGPT is not available",
                description="JengGPT is not currently running. Sorry about that!",
                color=discord.Color.red()
            ), ephemeral=True)
            return

        try:
            response = requests.post(f"{OLLAMA_URL}/api/generate", json={
                "model": model,
                "prompt": prompt,
                "stream": False
            }, timeout=15)

            print(f"📡 {MAGENTA}Status Code:{RESET}", response.status_code)
            print(f"🧾 {MAGENTA}Raw Response:{RESET}", response.text[:300])

            try:
                data = response.json()
            except JSONDecodeError:
                await ctx.respond(embed=Embed(
                    title="😴 JengGPT is Not Available",
                    description="Sorry, JengGPT returned a non-JSON response. Try again later.",
                    color=discord.Color.orange()
                ))
                return

            answer = data.get("response", "No response received.")

            embed = Embed(
                title="🧠 JengGPT",
                description=f"**Prompt:** {prompt}\n\n{answer.strip()}",
                color=discord.Color.dark_teal()
            )
            embed.add_field(name="🤖 Model Used", value=model, inline=False)
            embed.set_footer(text=f"Powered by {model} via Ollama")

            await ctx.respond(embed=embed)

        except requests.exceptions.ConnectionError:
            await ctx.respond(embed=Embed(
                title="😴 JengGPT is Offline",
                description="Could not connect to Ollama.",
                color=discord.Color.orange()
            ))
        except requests.exceptions.Timeout:
            await ctx.respond(embed=Embed(
                title="⏳ Timeout",
                description="JengGPT took too long to respond.",
                color=discord.Color.orange()
            ))
        except Exception as e:
            await ctx.respond(embed=Embed(
                title="❌ Error",
                description=f"```\n{str(e)}\n```",
                color=discord.Color.red()
            ))

    @commands.slash_command(name="warmup", description="Ping Ollama and warm up a model.")
    async def warmup(self, ctx: discord.ApplicationContext,
                     model: discord.Option(str, description="Model to warm up", default=DEFAULT_MODEL)):
        debug_command("warmup", ctx.user, ctx.guild, model=model)

        await ctx.defer()
        start_time = time.monotonic()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{OLLAMA_URL}/api/tags", timeout=3) as ping:
                    if ping.status != 200:
                        await ctx.respond(embed=Embed(
                            title="❌ Ollama is not responding",
                            description="Ping to the AI backend failed.",
                            color=discord.Color.red()
                        ))
                        return
                    tag_data = await ping.json()
                    models = [m["name"] if isinstance(m, dict) else m for m in tag_data.get("models", [])]

                    if model in models:
                        await ctx.respond(embed=Embed(
                            title="🟢 Model Already Active",
                            description=f"The model **`{model}`** is already running.",
                            color=discord.Color.blurple()
                        ))
                        return

            response = requests.post(f"{OLLAMA_URL}/api/generate", json={
                "model": model,
                "prompt": "Hello",
                "stream": False
            }, timeout=15)

            elapsed = time.monotonic() - start_time

            if response.status_code != 200:
                await ctx.respond(embed=Embed(
                    title="⚠️ Warmup Failed",
                    description=f"Ollama responded with status code `{response.status_code}`.",
                    color=discord.Color.orange()
                ))
                return

            await ctx.respond(embed=Embed(
                title="✅ Warmup Complete",
                description=f"Model **`{model}`** is now active.\nWarmup time: **{elapsed:.2f} seconds**",
                color=discord.Color.green()
            ))
        except Exception as e:
            print(f"❌ Warmup error: {e}")
            await ctx.respond(embed=Embed(
                title="❌ Warmup Failed",
                description="Warmup failed. JengGPT may be offline.",
                color=discord.Color.red()
            ))

# --- Cog Setup ---
async def setup(bot):
    await bot.add_cog(JengGPT(bot))
