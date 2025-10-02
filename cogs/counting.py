import discord
from discord.ext import commands
from discord import app_commands, Interaction
import json
import os
from typing import Optional
from utils.debug import debug_command
import asyncio

DATA_FILE = "counting_data.json"
ROLE_NAME = "cannot count"


def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}


def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


class Counting(commands.Cog):
    """Counting game cog. Creates counting channels and enforces rules per-channel.

    State is persisted in `counting_data.json` with the structure described in the workspace.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_json(DATA_FILE)
        # per-channel locks to serialize processing and avoid race conditions
        self._locks: dict[str, asyncio.Lock] = {}

    def has_bot_admin(self, member: discord.Member) -> bool:
        """Return True if the member is guild admin or has a role listed in xp_config.json under permissions_roles."""
        try:
            cfg_path = "xp_config.json"
            cfg = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            guild_id = str(member.guild.id)
            perms = cfg.get(guild_id, {}).get("permissions_roles", [])
            if member.guild_permissions.administrator:
                return True
            for role in member.roles:
                if str(role.id) in perms:
                    return True
        except Exception:
            pass
        return False

    def _save(self):
        save_json(DATA_FILE, self.data)

    async def _ensure_cannot_count_role(self, guild: discord.Guild) -> discord.Role:
        role = discord.utils.get(guild.roles, name=ROLE_NAME)
        if role:
            return role
        try:
            role = await guild.create_role(name=ROLE_NAME, reason="Counting punishment role")
            return role
        except discord.Forbidden:
            return None

    @app_commands.command(name="counting", description="Create a counting channel and initialize counting state.")
    @app_commands.describe(name="name of the counting channel (e.g. counting-game)", chances="how many mistakes before a user is banned from counting (leave empty for unlimited)")
    async def counting(self, interaction: Interaction, name: str, chances: Optional[int] = None):
        debug_command('counting', interaction.user, interaction.guild, name=name, chances=chances)

        if not interaction.guild:
            embed = discord.Embed(title="Error", description="This command must be used in a server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Permission check: only guild admins or configured bot-admin roles may create counting channels
        if not self.has_bot_admin(interaction.user):
            embed = discord.Embed(title="Permission Denied", description="You do not have permission to create counting channels.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Try to create the channel
        try:
            channel = await interaction.guild.create_text_channel(name)
        except discord.Forbidden:
            embed = discord.Embed(title="Permission Error", description="I don't have permission to create channels in this server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        except Exception as e:
            embed = discord.Embed(title="Error", description=f"Failed to create channel: {e}", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        ch_id = str(channel.id)
        # Store initial state; chances default is None (unlimited)
        self.data[ch_id] = {
            "last_count": 0,
            "last_user": None,
            "chances": chances if chances is not None else None,
            "mistakes": {}
        }
        self._save()

        desc = f"Counting channel created: {channel.mention}."
        if chances is None:
            desc += " Mistake limit: unlimited."
        else:
            desc += f" Mistake limit: {chances}"

        await interaction.response.send_message(embed=discord.Embed(title="✅ Counting channel created", description=desc, color=discord.Color.green()))

    @app_commands.command(name="delete_counting", description="Delete a counting channel and remove its counting configuration.")
    @app_commands.describe(channel="The counting channel to delete")
    async def delete_counting(self, interaction: Interaction, channel: discord.TextChannel):
        # debug log
        try:
            debug_command('delete_counting', interaction.user, interaction.guild, channel=channel.name)
        except Exception:
            pass

        if not interaction.guild:
            embed = discord.Embed(title="Error", description="This command must be used in a server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Permission check
        if not self.has_bot_admin(interaction.user):
            embed = discord.Embed(title="Permission Denied", description="You do not have permission to delete counting channels.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if channel.guild.id != interaction.guild.id:
            embed = discord.Embed(title="Error", description="That channel is not in this server.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        ch_id = str(channel.id)
        channel_name = channel.name

        # Only allow deletion for channels that are known counting channels
        if ch_id not in self.data:
            embed = discord.Embed(title="Error", description=f"{channel_name} is not a counting channel managed by me.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # If the command was invoked in the channel being deleted, do not send any messages
        # (avoid followups after deletion which can raise Unknown Channel). Just attempt deletion
        # and remove the stored data.
        invoked_channel = interaction.channel
        if invoked_channel and invoked_channel.id == channel.id:
            try:
                await channel.delete()
            except Exception:
                # Deliberately do not send messages in this case per user request.
                return

            # Remove stored data if present
            if ch_id in self.data:
                self.data.pop(ch_id, None)
                self._save()
            return

        # Send an initial public response so the server sees the deletion is in progress
        processing = discord.Embed(title="Deleting channel...", description=f"Attempting to delete {channel_name}.", color=discord.Color.orange())
        await interaction.response.send_message(embed=processing, ephemeral=False)

        try:
            await channel.delete()
        except discord.Forbidden:
            embed = discord.Embed(title="Permission Error", description="I don't have permission to delete that channel.", color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        except Exception as e:
            embed = discord.Embed(title="Error", description=f"Failed to delete channel: {e}", color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        removed = False
        if ch_id in self.data:
            self.data.pop(ch_id, None)
            self._save()
            removed = True

        if removed:
            embed = discord.Embed(title="✅ Counting channel removed", description=f"{channel_name} deleted and its counting data removed.", color=discord.Color.green())
        else:
            embed = discord.Embed(title="✅ Channel removed", description=f"{channel_name} deleted. No counting data found.", color=discord.Color.green())

        await interaction.followup.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        ch_id = str(message.channel.id)
        entry = self.data.get(ch_id)
        if not entry:
            return

        # acquire a per-channel lock to avoid races when multiple messages arrive simultaneously
        lock = self._locks.get(ch_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[ch_id] = lock

        async with lock:
            # If user has the cannot count role, delete their messages (if they post numbers)
            cannot_role = discord.utils.get(message.guild.roles, name=ROLE_NAME)
            if cannot_role and cannot_role in message.author.roles:
                # If they posted a number, delete it
                try:
                    # quick check if message is integer
                    _ = int(message.content.strip())
                except Exception:
                    return
                try:
                    await message.delete()
                except Exception:
                    pass
                return

            # Only process pure integer messages
            content = message.content.strip()
            try:
                num = int(content)
            except Exception:
                return

            last_count = entry.get("last_count", 0)
            last_user = entry.get("last_user")
            chances = entry.get("chances")
            mistakes = entry.setdefault("mistakes", {})

            author_id = str(message.author.id)

            # Violation: same user twice in a row
            if last_user is not None and author_id == last_user:
                try:
                    await message.add_reaction("❌")
                except Exception:
                    pass

                # increment mistake count
                mistakes[author_id] = mistakes.get(author_id, 0) + 1

                # compute remaining mistakes if a limit is set
                remaining = None
                if chances is not None:
                    remaining = max(chances - mistakes[author_id], 0)

                # reset
                entry["last_count"] = 0
                entry["last_user"] = None
                self._save()

                # announce (include mistakes left when applicable)
                try:
                    desc = f"{message.author.mention} messed up by counting twice in a row."
                    if remaining is not None:
                        desc += f"\n\nMistakes left: {remaining}"
                    em = discord.Embed(title="Count reset!", description=desc, color=discord.Color.red())
                    await message.channel.send(embed=em)
                except Exception:
                    pass

                # enforce role if needed
                if chances is not None and mistakes[author_id] >= chances:
                    role = await self._ensure_cannot_count_role(message.guild)
                    if role:
                        try:
                            await message.author.add_roles(role, reason="Reached counting mistake limit")
                            em2 = discord.Embed(title="Cannot Count Assigned", description=f"Vro {message.author.mention} you had {chances} chances :wilted_rose: Nah you can't count anymore gang", color=discord.Color.orange())
                            await message.channel.send(embed=em2)
                            # Debug: user reached mistake limit
                            try:
                                debug_command('count_limit_reached', message.author, message.guild, channel=message.channel, mistakes=mistakes[author_id])
                            except Exception:
                                pass
                        except Exception:
                            pass

                return

            # Correct count
            if num == last_count + 1:
                try:
                    await message.add_reaction("✅")
                except Exception:
                    pass
                entry["last_count"] = num
                entry["last_user"] = author_id
                self._save()
                return

            # Wrong number
            try:
                await message.add_reaction("❌")
            except Exception:
                pass

            mistakes[author_id] = mistakes.get(author_id, 0) + 1

            # compute remaining mistakes if a limit is set
            remaining = None
            if chances is not None:
                remaining = max(chances - mistakes[author_id], 0)

            entry["last_count"] = 0
            entry["last_user"] = None
            self._save()

            try:
                expected = last_count + 1
                desc = f"{message.author.mention} you can't count dawg??? Lock in. Should have been {expected}."
                if remaining is not None:
                    desc += f"\n\nMistakes left: {remaining}"
                em = discord.Embed(title="Count reset!", description=desc, color=discord.Color.red())
                await message.channel.send(embed=em)
            except Exception:
                pass

            if chances is not None and mistakes[author_id] >= chances:
                role = await self._ensure_cannot_count_role(message.guild)
                if role:
                    try:
                        await message.author.add_roles(role, reason="Reached counting mistake limit")
                        em2 = discord.Embed(title="Cannot Count Assigned", description=f"Vro {message.author.mention} you had {chances} chances :wilted_rose: Nah you can't count anymore gang", color=discord.Color.orange())
                        await message.channel.send(embed=em2)
                        # Debug: user reached mistake limit
                        try:
                            debug_command('count_limit_reached', message.author, message.guild, channel=message.channel, mistakes=mistakes[author_id])
                        except Exception:
                            pass
                    except Exception:
                        pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Counting(bot))
