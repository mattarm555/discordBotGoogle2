import discord
from discord.ext import commands
import aiohttp
import requests
import time
from json.decoder import JSONDecodeError

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
    async def askjeng(self, ctx: discord.ApplicationContext, prompt: str, model: str = DEFAULT_MODEL):
        debug_command("askjeng", ctx.author, ctx.guild, prompt=prompt, model=model)

        await ctx.defer()

        if not await is_ollama_online():
            await ctx.respond(embed=discord.Embed(
                title="🛑 JengGPT is not available",
                description="JengGPT is not currently running. Sorry about that!",
                color=discord.Color.red()
            ), ephemeral=True)
            print(f"❌ {GREEN}Ollama server not available — skipping interaction.{RESET}")
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
                print(f"❌ {GREEN}Received non-JSON response from Ollama.{RESET}")
                await ctx.respond(embed=discord.Embed(
                    title="😴 JengGPT is Not Available",
                    description="Sorry, JengGPT is not here right now! Please try again later.",
                    color=discord.Color.orange()
                ))
                return

            answer = data.get("response", "No response received.")

            embed = discord.Embed(
                title="🧠 JengGPT",
                description=f"**Prompt:** {prompt}\n\n{answer.strip()}",
                color=discord.Color.dark_teal()
            )
            embed.add_field(name="🤖 Model Used", value=model, inline=False)
            embed.set_footer(text=f"Powered by {model} via Ollama")

            await ctx.respond(embed=embed)

        except requests.exceptions.ConnectionError:
            print(f"❌ {GREEN}Could not connect to Ollama server.{RESET}")
            await ctx.respond(embed=discord.Embed(
                title="😴 JengGPT is Offline",
                description="Sorry, JengGPT is either not here right now or experiencing technical difficulties.",
                color=discord.Color.orange()
            ))

        except requests.exceptions.Timeout:
            print(f"⏳ {GREEN}Request to Ollama timed out.{RESET}")
            await ctx.respond(embed=discord.Embed(
                title="⏳ Timeout",
                description="JengGPT took too long to respond. I recommend trying /warmup before you ask a question for better response times.",
                color=discord.Color.orange()
            ))

        except Exception as e:
            print(f"❌ {GREEN}Exception occurred:{RESET}", e)
            await ctx.respond(embed=discord.Embed(
                title="❌ Error",
                description=f"```\n{str(e)}\n```",
                color=discord.Color.red()
            ))

    @commands.slash_command(name="warmup", description="Ping Ollama and warm up a specific model.")
    async def warmup(self, ctx: discord.ApplicationContext, model: str = DEFAULT_MODEL):
        debug_command("warmup", ctx.author, ctx.guild, model=model)

        await ctx.defer()

        try:
            start_time = time.monotonic()

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{OLLAMA_URL}/api/tags", timeout=3) as ping:
                        if ping.status != 200:
                            print(f"❌ {GREEN}Ollama ping failed with status {RESET}{ping.status}")
                            await ctx.respond(embed=discord.Embed(
                                title="❌ Ollama is not responding",
                                description="Ping to the AI backend failed.",
                                color=discord.Color.red()
                            ))
                            return
                        tag_data = await ping.json()
                        model_list = tag_data.get("models") or tag_data.get("tags") or []
                        available_models = [m["name"] if isinstance(m, dict) else m for m in model_list]

                        if model in available_models:
                            print(f"🟢 Model '{model}' is already loaded.")
                            await ctx.respond(embed=discord.Embed(
                                title="🟢 Model Already Active",
                                description=f"The model **`{model}`** is already running and ready to use.",
                                color=discord.Color.blurple()
                            ))
                            return
            except Exception:
                print(f"❌ {GREEN}Ollama server is offline or unreachable.{RESET}")
                await ctx.respond(embed=discord.Embed(
                    title="😴 JengGPT is Offline",
                    description="Sorry, JengGPT is not here right now! Please try again later.",
                    color=discord.Color.orange()
                ))
                return

            try:
                response = requests.post(f"{OLLAMA_URL}/api/generate", json={
                    "model": model,
                    "prompt": "Hello",
                    "stream": False
                }, timeout=15)
            except Exception:
                print(f"❌ {GREEN}Warmup request failed due to timeout or unreachable host.{RESET}")
                await ctx.respond(embed=discord.Embed(
                    title="😴 JengGPT is Offline",
                    description="Warmup failed. JengGPT is not responding or offline.",
                    color=discord.Color.orange()
                ))
                return

            elapsed = time.monotonic() - start_time

            if response.status_code != 200:
                print(f"⚠️ {GREEN}Ollama warmup failed (status {response.status_code}) in {elapsed:.2f}s{RESET}")
                await ctx.respond(embed=discord.Embed(
                    title="⚠️ Warmup Failed",
                    description=f"Ollama responded with status code `{response.status_code}`.",
                    color=discord.Color.orange()
                ))
                return

            await ctx.respond(embed=discord.Embed(
                title="✅ Warmup Complete",
                description=f"Model **`{model}`** is now active.\nWarmup time: **{elapsed:.2f} seconds**",
                color=discord.Color.green()
            ))

            print(f"🔥 {MAGENTA}Model '{model}' warmed up in {elapsed:.2f} seconds.{RESET}")

        except Exception as e:
            print(f"❌ {GREEN}Warmup error:{RESET}", e)
            await ctx.respond(embed=discord.Embed(
                title="❌ Warmup Failed",
                description="Warmup failed. JengGPT is not responding or offline.",
                color=discord.Color.red()
            ))

async def setup(bot):
    await bot.add_cog(JengGPT(bot))
