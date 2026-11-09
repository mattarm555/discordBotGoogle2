import asyncio
import os
import shutil

import discord
from discord import Embed, Interaction, app_commands
from discord.ext import commands

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _run(*args: str, timeout: float = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=ROOT_DIR,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "timed out"
    return proc.returncode, (out or b"").decode(errors="replace").strip()


class Deploy(commands.Cog):
    """Owner-only remote redeploy: pull the latest code from GitHub and restart."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _is_owner(self, interaction: Interaction) -> bool:
        app_info = await self.bot.application_info()
        return interaction.user.id == app_info.owner.id

    @app_commands.command(name="redeploy", description="Owner-only: pull the latest code from GitHub and restart the bot.")
    async def redeploy(self, interaction: Interaction):
        if not await self._is_owner(interaction):
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)

        git = shutil.which("git")
        if not git:
            await interaction.edit_original_response(content="❌ git is not on PATH on the host.")
            return

        rc, before = await _run(git, "rev-parse", "--short", "HEAD")
        rc, pull = await _run(git, "pull", "--ff-only")
        if rc != 0:
            await interaction.edit_original_response(embed=Embed(
                title="❌ git pull failed — still running the old code",
                description=f"```{pull[-1500:]}```",
                color=discord.Color.red()))
            return
        _, after = await _run(git, "rev-parse", "--short", "HEAD")
        _, log = await _run(git, "log", "--oneline", f"{before}..{after}") if before != after else (0, "")

        if before == after:
            await interaction.edit_original_response(embed=Embed(
                title="✅ Already up to date",
                description=f"Running `{after}`. Nothing to deploy.",
                color=discord.Color.green()))
            return

        await interaction.edit_original_response(embed=Embed(
            title="🚀 Redeploying",
            description=(f"`{before}` → `{after}`\n```{log[-1200:] or '(no log)'}```\n"
                         "Restarting now; the runner installs any new packages and starts the bot "
                         "again in ~15 seconds."),
            color=discord.Color.blurple()))
        print(f"[deploy] /redeploy by {interaction.user} {before} -> {after}; exiting for restart", flush=True)
        await asyncio.sleep(1)
        # Exiting lets deploy/windows/run.ps1 (or systemd on Linux) start the new code.
        await self.bot.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(Deploy(bot))
