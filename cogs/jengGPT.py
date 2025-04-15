import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import aiohttp
import requests
import time
from json.decoder import JSONDecodeError

RESET = "\033[0m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

OLLAMA_URL = "https://burlington-money-emotions-variance.trycloudflare.com"
DEFAULT_MODEL = "mistral"

# 🔍 Async check to verify Ollama is up before deferring
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

    @app_commands.command(name="askjeng", description="Ask your local AI anything.")
    @app_commands.describe(
        prompt="What do you want to ask JengGPT?",
        model="Which model to use (e.g., mistral, llama2, codellama, llama2-uncensored)"
    )
    async def askjeng(self, interaction: Interaction, prompt: str, model: str = DEFAULT_MODEL):
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            print(f"❌ {GREEN}Could not defer. Interaction may have expired or already responded.{RESET}")
            return

        if not await is_ollama_online():
            await interaction.followup.send(embed=Embed(
                title="🛑 JengGPT is not available",
                description="The AI backend (Ollama) is currently offline. Try again shortly.",
                color=discord.Color.red()
            ), ephemeral=True)
            print(f"❌ {GREEN}Ollama server not available — skipping interaction.{RESET}")
            return

        try:
            print(f"📝 {CYAN}Prompt: {prompt}{RESET}")
            print(f"🤖 {CYAN}Model selected: {model}{RESET}")
            print(f"🔁 {CYAN}Sending prompt to:{RESET}", OLLAMA_URL)

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
                await interaction.followup.send(embed=Embed(
                    title="😴 JengGPT is Not Available",
                    description="Sorry, JengGPT is not here right now! Please try again later.",
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

            await interaction.followup.send(embed=embed)

        except requests.exceptions.ConnectionError:
            print(f"❌ {GREEN}Could not connect to Ollama server.{RESET}")
            await interaction.followup.send(embed=Embed(
                title="😴 JengGPT is Offline",
                description="Sorry, JengGPT is not here right now! I recommend trying /warmup before you ask a question for better response times.",
                color=discord.Color.orange()
            ))

        except requests.exceptions.Timeout:
            print(f"⏳ {GREEN}Request to Ollama timed out.{RESET}")
            await interaction.followup.send(embed=Embed(
                title="⏳ Timeout",
                description="JengGPT took too long to respond. I recommend trying /warmup before you ask a question for better response times.",
                color=discord.Color.orange()
            ))

        except Exception as e:
            print(f"❌ {GREEN}Exception occurred:{RESET}", e)
            await interaction.followup.send(embed=Embed(
                title="❌ Error",
                description=f"```\n{str(e)}\n```",
                color=discord.Color.red()
            ))

    @app_commands.command(name="warmup", description="Ping Ollama and warm up a specific model.")
    @app_commands.describe(
        model="Which model to warm up (e.g., mistral, llama2, codellama. llam2-uncensored)"
    )
    async def warmup(self, interaction: Interaction, model: str = DEFAULT_MODEL):
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            print(f"❌ {GREEN}Could not defer. Interaction may have expired or already responded.{RESET}")
            return

        try:
            start_time = time.monotonic()

            # Step 1: Check if Ollama is online and get loaded models
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{OLLAMA_URL}/api/tags", timeout=3) as ping:
                        if ping.status != 200:
                            print(f"❌ {GREEN}Ollama ping failed with status {RESET}{ping.status}")
                            await interaction.followup.send(embed=Embed(
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
                            await interaction.followup.send(embed=Embed(
                                title="🟢 Model Already Active",
                                description=f"The model **`{model}`** is already running and ready to use.",
                                color=discord.Color.blurple()
                            ))
                            return
            except Exception:
                print(f"❌ {GREEN}Ollama server is offline or unreachable.{RESET}")
                await interaction.followup.send(embed=Embed(
                    title="😴 JengGPT is Offline",
                    description="Sorry, JengGPT is not here right now! I recommend trying /warmup before you ask a question for better response times.",
                    color=discord.Color.orange()
                ))
                return

            # Step 2: Try warming up the model with a dummy prompt
            try:
                response = requests.post(f"{OLLAMA_URL}/api/generate", json={
                    "model": model,
                    "prompt": "Hello",
                    "stream": False
                }, timeout=15)
            except Exception:
                print(f"❌ {GREEN}Warmup request failed due to timeout or unreachable host.{RESET}")
                await interaction.followup.send(embed=Embed(
                    title="😴 JengGPT is Offline",
                    description="Warmup failed. JengGPT is not responding or offline.",
                    color=discord.Color.orange()
                ))
                return

            elapsed = time.monotonic() - start_time

            if response.status_code != 200:
                print(f"⚠️ {GREEN}Ollama warmup failed (status {response.status_code}) in {elapsed:.2f}s{RESET}")
                await interaction.followup.send(embed=Embed(
                    title="⚠️ Warmup Failed",
                    description=f"Ollama responded with status code `{response.status_code}`.",
                    color=discord.Color.orange()
                ))
                return

            await interaction.followup.send(embed=Embed(
                title="✅ Warmup Complete",
                description=f"Model **`{model}`** is now active.\n"
                            f"Warmup time: **{elapsed:.2f} seconds**",
                color=discord.Color.green()
            ))

            print(f"🔥 {MAGENTA}Model '{model}' warmed up in {elapsed:.2f} seconds.{RESET}")

        except Exception as e:
            print(f"❌ {GREEN}Warmup error:{RESET}", e)
            await interaction.followup.send(embed=Embed(
                title="❌ Warmup Failed",
                description="Warmup failed. JengGPT is not responding or offline.",
                color=discord.Color.red()
            ))

async def setup(bot):
    await bot.add_cog(JengGPT(bot))
