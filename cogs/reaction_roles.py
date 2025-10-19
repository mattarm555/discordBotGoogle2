import discord
from discord.ext import commands
from discord import app_commands, Interaction
import os
import json
import logging
import hashlib
from typing import Optional
import random
import asyncio
import time
from utils.debug import debug_command

logger = logging.getLogger('jeng.reactionroles')
logger.setLevel(logging.INFO)

REACTION_FILE = 'reaction_roles.json'
COOLDOWNS_FILE = 'reaction_roles_cooldowns.json'
# NOTE: The file previously contained a very large, variant-filled palette.
# To simplify and make names human-readable and unique, we override that
# earlier palette here with a curated set of 100 distinct color names
# (no variant qualifiers) and 100 emoji placeholders. This preserves the
# rest of the module while ensuring COLOR_EMOJIS/COLOR_PALETTE are clean.

# Simple emoji set (100 entries) — cycled from a small base set to provide
# readable reaction icons; these are intentionally generic and can be
# customized later if you prefer different emoji choices.
COLOR_EMOJIS = [
    # 100 unique, display-friendly emojis mapped 1:1 to COLOR_PALETTE
    '⬜','⬛','🟥','🟧','🟨','🟩','🟦','🟪','🟫','🔴',
    '🟠','🟡','🟢','🔵','🟣','⚪','⚫','🔶','🔷','🔸',
    '🔹','🔺','🔻','⭐','🌟','✨','⚡','🔥','💥','💫',
    '💢','❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎',
    '🌈','🌊','🍊','🍎','🍐','🍋','🍇','🍓','🍒','🍑',
    '🍍','🥭','🥥','🥝','🍌','🍉','🍅','🥕','🌽','🥦',
    '🍆','🍄','🌶️','🌸','🌹','🌺','🌻','🌼','🌷','🌱',
    '🌲','🌳','🌵','🌴','🍀','🍁','🍂','🍃','🪴','🌐',
    '🧊','🧿','🪙','⚙️','🧸','🧶','🪄','🪅','🪆','🪮',
    '🎨','🎭','🎵','🎯','🏵️','🎗️','🎖️','🎉','🎊','🎈',
]

# Curated 100 human-readable color names (no variants) and hex codes.
COLOR_PALETTE = [
    ("White", "#FFFFFF"),
    ("Black", "#010000"),
    ("Red", "#FF0000"),
    ("Green", "#008000"),
    ("Blue", "#0000FF"),
    ("Yellow", "#FFFF00"),
    ("Orange", "#FFA500"),
    ("Purple", "#800080"),
    ("Hot Pink", "#FF1493"),
    ("Saddle Brown", "#8B4513"),
    ("Gray", "#808080"),
    ("Teal", "#008080"),
    ("Navy", "#000080"),
    ("Maroon", "#800000"),
    ("Olive", "#808000"),
    ("Lime", "#00FF00"),
    ("Aqua", "#00FFFF"),
    ("Turquoise", "#40E0D0"),
    ("Indigo", "#4B0082"),
    ("Violet", "#EE82EE"),
    ("Magenta", "#FF00FF"),
    ("Dark Turquoise", "#00CED1"),
    ("Beige", "#F5F5DC"),
    ("Tan", "#D2B48C"),
    ("Gold", "#FFD700"),
    ("Silver", "#C0C0C0"),
    ("Bronze", "#CD7F32"),
    ("Lavender", "#E6E6FA"),
    ("Plum", "#8E4585"),
    ("Mint", "#98FF98"),
    ("Peach", "#FFE5B4"),
    ("Apricot", "#FBCEB1"),
    ("Salmon", "#FA8072"),
    ("Coral", "#FF7F50"),
    ("Crimson", "#DC143C"),
    ("Burgundy", "#800020"),
    ("Chocolate", "#D2691E"),
    ("Coffee", "#6F4E37"),
    ("Mustard", "#FFDB58"),
    ("Khaki", "#F0E68C"),
    ("Charcoal", "#36454F"),
    ("Slate Gray", "#708090"),
    ("Steel Blue", "#4682B4"),
    ("Sky Blue", "#87CEEB"),
    ("Ocean Blue", "#0077BE"),
    ("Midnight Blue", "#191970"),
    ("Forest Green", "#228B22"),
    ("Pine Green", "#01796F"),
    ("Moss", "#8A9A5B"),
    ("Emerald", "#50C878"),
    ("Jade", "#00A86B"),
    ("Seafoam", "#9FE2BF"),
    ("Teal Green", "#3EB489"),
    ("Lilac", "#C8A2C8"),
    ("Rose", "#FF007F"),
    ("Raspberry", "#E30B5C"),
    ("Copper", "#B87333"),
    ("Rust", "#B7410E"),
    ("Sand", "#C2B280"),
    ("Dune", "#967117"),
    ("Ivory", "#FFFFF0"),
    ("Almond", "#FFEBCD"),
    ("Deep Ocean", "#006994"),
    ("Ice", "#F0FFFF"),
    ("Frost", "#E0FFFF"),
    ("Lemon", "#FFF44F"),
    ("Canary", "#FFEF00"),
    ("Amber", "#FFBF00"),
    ("Flame", "#E25822"),
    ("Firebrick", "#B22222"),
    ("Berry", "#8A2BE2"),
    ("Orchid", "#DA70D6"),
    ("Periwinkle", "#CCCCFF"),
    ("Mint Cream", "#F5FFFA"),
    ("Celeste", "#B2FFFF"),
    ("Cerulean", "#007BA7"),
    ("Sapphire", "#0F52BA"),
    ("Cobalt", "#0047AB"),
    ("Azure", "#007FFF"),
    ("Cornflower", "#6495ED"),
    ("Sandstone", "#786D5F"),
    ("Taupe", "#483C32"),
    ("Wheat", "#F5DEB3"),
    ("Oat", "#E6D8AD"),
    ("Lemon Chiffon", "#FFFACD"),
    ("Powder Blue", "#B0E0E6"),
    ("Slate Blue", "#6A5ACD"),
    ("Denim", "#1560BD"),
    ("Spring Green", "#00FF7F"),
    ("Olive Drab", "#6B8E23"),
    ("Chartreuse", "#7FFF00"),
    ("Pistachio", "#93C572"),
    ("Peacock", "#33A1C9"),
    ("Arctic Blue", "#CDEBFF"),
    ("Sunset", "#FD5E53"),
    ("Tangerine", "#FF9408"),
    ("Mahogany", "#C04000"),
    ("Sangria", "#92000A"),
    ("Pewter", "#99AABB"),
    ("Smoke", "#848482"),
]

# Maximum number of available colors (dynamic)
# Allow up to the full curated palette (previously capped at 75)
MAX_COLOR_COUNT = min(50, len(COLOR_PALETTE))


class ColorPickerView(discord.ui.View):
    """Interactive color picker: paginate through the hardcoded palette and allow the
    command user to pick exactly `required` colors. Includes Prev/Next navigation,
    per-item select buttons, Random quick-pick, Confirm, and Cancel.
    """
    def __init__(self, palette, emojis, required: int, user_id: int, *, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.palette = palette
        self.emojis = emojis
        self.required = required
        self.user_id = user_id
        self.page_size = 10
        self.page = 0
        self.selected = set()
        self.value = None  # final list of indices when confirmed

        # persistent controls
        self.prev_btn = discord.ui.Button(label='◀', style=discord.ButtonStyle.secondary)
        self.next_btn = discord.ui.Button(label='▶', style=discord.ButtonStyle.secondary)
        self.random_btn = discord.ui.Button(label='Random', style=discord.ButtonStyle.primary)
        self.confirm_btn = discord.ui.Button(label='Confirm', style=discord.ButtonStyle.success, disabled=True)
        self.cancel_btn = discord.ui.Button(label='Cancel', style=discord.ButtonStyle.danger)

        # assign callbacks
        self.prev_btn.callback = self.on_prev
        self.next_btn.callback = self.on_next
        self.random_btn.callback = self.on_random
        self.confirm_btn.callback = self.on_confirm
        self.cancel_btn.callback = self.on_cancel

        # initial children: item buttons will be added by update_page_items
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)
        self.add_item(self.random_btn)
        self.add_item(self.confirm_btn)
        self.add_item(self.cancel_btn)
        self.update_page_items()

    def update_page_items(self):
        # remove any existing item buttons (custom_id starts with 'item-')
        for child in list(self.children):
            cid = getattr(child, 'custom_id', None)
            if isinstance(cid, str) and cid.startswith('item-'):
                self.remove_item(child)

        start = self.page * self.page_size
        end = min(start + self.page_size, len(self.palette))
        for i in range(start, end):
            emoji = self.emojis[i] if i < len(self.emojis) else '❔'
            name = self.palette[i][0]
            label = f"{emoji} {name}"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f'item-{i}')

            async def item_callback(interaction: discord.Interaction, i=i):
                if interaction.user.id != self.user_id:
                    await interaction.response.send_message('Only the command invoker can use this picker.', ephemeral=True)
                    return
                if i in self.selected:
                    self.selected.remove(i)
                else:
                    if len(self.selected) >= self.required:
                        # inform user they can't select more
                        await interaction.response.send_message(f'You can only select {self.required} colors.', ephemeral=True)
                        return
                    self.selected.add(i)
                # update confirm enabled state
                self.confirm_btn.disabled = (len(self.selected) != self.required)
                await interaction.response.edit_message(embed=self.build_embed(), view=self)

            btn.callback = item_callback
            # insert item buttons before navigation controls (so they appear first)
            # add at front: use insert at position 0 repeatedly to keep order
            self.add_item(btn)

    def build_embed(self):
        start = self.page * self.page_size
        end = min(start + self.page_size, len(self.palette))
        e = discord.Embed(title=f'Select colors ({len(self.selected)}/{self.required}) — page {self.page+1}/{(len(self.palette)-1)//self.page_size+1}', color=discord.Color.blurple())
        for i in range(start, end):
            emoji = self.emojis[i] if i < len(self.emojis) else '❔'
            name, hexv = self.palette[i]
            selected_mark = ' ✅' if i in self.selected else ''
            e.add_field(name=f"{emoji} {name}{selected_mark}", value=f'`{hexv}`', inline=True)
        # footer hint
        e.set_footer(text='Click an item to toggle selection. Use Random to auto-pick. Confirm becomes enabled when selections match the requested count.')
        return e

    async def on_prev(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Only the command invoker can use this picker.', ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
            self.update_page_items()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_next(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Only the command invoker can use this picker.', ephemeral=True)
            return
        max_page = (len(self.palette)-1) // self.page_size
        if self.page < max_page:
            self.page += 1
            self.update_page_items()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_random(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Only the command invoker can use this picker.', ephemeral=True)
            return
        # choose random indices
        self.selected = set(random.sample(range(len(self.palette)), k=self.required))
        self.confirm_btn.disabled = False
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_confirm(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Only the command invoker can use this picker.', ephemeral=True)
            return
        if len(self.selected) != self.required:
            await interaction.response.send_message(f'Please select exactly {self.required} colors before confirming.', ephemeral=True)
            return
        self.value = list(self.selected)
        await interaction.response.edit_message(content='Selection confirmed — creating roles...', embed=None, view=None)
        self.stop()

    async def on_cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('Only the command invoker can use this picker.', ephemeral=True)
            return
        await interaction.response.edit_message(content='Selection cancelled.', embed=None, view=None)
        self.value = None
        self.stop()

    async def on_timeout(self):
        # when timing out, just stop and leave the message as-is
        try:
            self.stop()
        except Exception:
            pass



def load_reaction_configs():
    if os.path.exists(REACTION_FILE):
        try:
            with open(REACTION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            # file is empty or corrupted; log and return empty config map
            logger.exception('[ReactionRoles] Failed to parse reaction_roles.json; starting with empty configs')
            try:
                # attempt to move the bad file aside
                os.replace(REACTION_FILE, REACTION_FILE + '.bak')
            except Exception:
                pass
            return {}
    return {}


def save_reaction_configs(data):
    with open(REACTION_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def _load_cooldowns():
    if os.path.exists(COOLDOWNS_FILE):
        try:
            with open(COOLDOWNS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cooldowns(data: dict):
    try:
        with open(COOLDOWNS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def _fmt_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s and not h:  # only show seconds when under an hour to keep it compact
        parts.append(f"{s}s")
    return ' '.join(parts) if parts else '0s'


class ReactionRoles(commands.Cog):
    """Create color roles and post reaction-role messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.configs = load_reaction_configs()  # guild_id -> list of configs
        # in-memory per-guild cooldowns when we detect long Retry-After values
        # maps guild_id -> unix timestamp (time.time()) until which bulk creations should be avoided
        self._guild_cooldowns = {}

    async def cog_unload(self):
        pass

    def _make_config_id(self, guild_id: int, base_name: str) -> str:
        h = hashlib.sha1(f"{guild_id}:{base_name}:{os.urandom(8)}".encode('utf-8')).hexdigest()
        return h[:8]

    @app_commands.command(name='reactionroles_create', description='Create 1..50 color roles.')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(count=f'Number of color roles to create (1-{MAX_COLOR_COUNT})', base_name='Base name for the roles', interactive='Use interactive picker to choose colors', batch_size='Create roles in batches of this size to avoid rate limits')
    async def create_roles(self, interaction: Interaction, count: int, base_name: Optional[str] = 'Color', interactive: Optional[bool] = False, batch_size: Optional[int] = 10):
        # Defer immediately (public response) so we can edit it later.
        await interaction.response.defer(thinking=True, ephemeral=False)
        debug_command('reactionroles_create', interaction.user, guild=interaction.guild, count=count, base_name=base_name)
        # permission check
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            # edit the original (deferred) ephemeral response with an error
            await interaction.edit_original_response(content='❌ You do not have permission to use this command.')
            return

        # dynamic validation against available colors
        # dynamic validation against available colors (cap at MAX_COLOR_COUNT)
        max_count = min(len(COLOR_PALETTE), MAX_COLOR_COUNT)
        if count < 1 or count > max_count:
            await interaction.edit_original_response(content=f'❌ Count must be between 1 and {max_count}.')
            return

        # size-based per-user cooldown: 30m if <25 roles, else 1h
        try:
            cooldown_seconds = 1800 if count < 25 else 3600
            now_ts = int(time.time())
            gid = str(interaction.guild.id)
            uid = str(interaction.user.id)
            cds = _load_cooldowns()
            last = int(cds.get('guilds', {}).get(gid, {}).get(uid, {}).get('last_create', 0))
            elapsed = now_ts - last
            if last > 0 and elapsed < cooldown_seconds:
                remaining = cooldown_seconds - elapsed
                await interaction.edit_original_response(content=f'⏳ Cooldown in effect. You can create roles again in { _fmt_remaining(remaining) } (based on requested count).')
                return
            # record now to prevent spam starts; will overwrite on success as well
            cds.setdefault('guilds', {}).setdefault(gid, {}).setdefault(uid, {})['last_create'] = now_ts
            _save_cooldowns(cds)
        except Exception:
            # do not block on cooldown system failure
            pass

        # validate batch_size
        try:
            batch_size = int(batch_size) if batch_size is not None else 10
        except Exception:
            batch_size = 10
        if batch_size < 1:
            batch_size = 1

        guild = interaction.guild
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            await interaction.edit_original_response(content='❌ Could not determine bot member in this guild.')
            return

        # check for a recent large rate-limit cooldown for this guild
        now_ts = time.time()
        cooldown_until = self._guild_cooldowns.get(guild.id)
        if cooldown_until and cooldown_until > now_ts:
            remaining = int(cooldown_until - now_ts)
            await interaction.edit_original_response(content=f'❌ This server is currently rate-limited for bulk role creation. Try again in {remaining}s.')
            return

        # check manage_roles permission
        if not guild.me.guild_permissions.manage_roles:
            await interaction.edit_original_response(content='❌ I need the Manage Roles permission to create roles.')
            return

    # NOTE: determine the bot's top role position AFTER creating roles to avoid stale data
    # (we'll refetch the bot member after role creation and use that position)
        # pick a random subset of colors while preserving the universal emoji->color mapping
        created = []
        try:
            # allow interactive selection of colors (picker) or random sampling
            if interactive:
                # If user asked for the full palette, just use all colors — no need for interactive selection
                if count >= len(COLOR_PALETTE):
                    indices = list(range(len(COLOR_PALETTE)))
                else:
                    view = ColorPickerView(COLOR_PALETTE, COLOR_EMOJIS, required=count, user_id=interaction.user.id)
                    message = await interaction.edit_original_response(embed=view.build_embed(), view=view)
                    # wait for the view to finish (confirm/cancel or timeout)
                    await view.wait()
                    if not view.value:
                        # cancelled or timed out
                        await interaction.followup.send('Color selection cancelled or timed out.', ephemeral=True)
                        return
                    indices = view.value
            else:
                # sample indices so emojis remain tied to their matching colors
                indices = random.sample(range(len(COLOR_PALETTE)), k=count)
            # Build lists and create roles one-by-one with per-role timeout and robust error handling.
            color_choices = [COLOR_PALETTE[i] for i in indices]
            emoji_choices = [COLOR_EMOJIS[i] for i in indices]
            success_indices = []
            failed = []
            total = len(indices)
            last_progress_update = 0
            # Create a partial config entry up-front and persist it so progress isn't lost
            cfg_id = self._make_config_id(guild.id, base_name)
            cfg = {
                'id': cfg_id,
                'base_name': base_name,
                'choices': []
            }
            self.configs.setdefault(str(guild.id), []).append(cfg)
            try:
                save_reaction_configs(self.configs)
            except Exception:
                logger.exception('[ReactionRoles] Failed to save initial partial config')
            # Preflight: ensure we won't exceed Discord's hard role limit (250 roles)
            existing_role_count = len(guild.roles)
            if existing_role_count + len(indices) > 250:
                await interaction.edit_original_response(content=f'❌ Creating {len(indices)} roles would exceed Discord\'s maximum of 250 roles per guild (current: {existing_role_count}). Reduce the count and try again.')
                return

            # process indices in batches to avoid hammering the API
            total = len(indices)
            processed = 0
            for batch_start in range(0, total, batch_size):
                batch = indices[batch_start:batch_start+batch_size]
                for palette_idx in batch:
                    processed += 1
                    color_name, hexcode = COLOR_PALETTE[palette_idx]
                    name = f"{color_name}"
                    # parse hex to int for discord.Color
                    try:
                        v = int(hexcode.lstrip('#'), 16)
                        colour = discord.Color(v)
                    except Exception:
                        colour = discord.Color.default()

                    # If a role with the intended name already exists, reuse it and record success
                    existing = {r.name: r for r in guild.roles}
                    if name in existing:
                        role = existing[name]
                        created.append(role)
                        success_indices.append(palette_idx)
                        # Sleep to avoid contributing to rate limits
                        try:
                            await asyncio.sleep(3.0)
                        except Exception:
                            pass
                        # update progress using actual created/failed counts
                        if (len(created) + len(failed)) - last_progress_update >= 5 or (len(created) + len(failed)) == total:
                            try:
                                await interaction.edit_original_response(content=f'Creating roles... {len(created)}/{total} succeeded, {len(failed)} failed', embed=None)
                            except Exception:
                                pass
                            last_progress_update = len(created) + len(failed)
                        continue

                    # Attempt to create the role with retry on explicit rate limits
                    per_role_start = time.monotonic()
                    per_role_timeout = 30.0  # allow up to 30 seconds trying this role (including wait-on-rate-limit)
                    attempt = 0
                    while True:
                        attempt += 1
                        try:
                            role = await guild.create_role(name=name, colour=colour, reason=f'Reaction roles created by {interaction.user}')
                            created.append(role)
                            success_indices.append(palette_idx)
                            # brief throttle after success
                            try:
                                await asyncio.sleep(2.0)
                            except Exception:
                                pass
                            break
                        except discord.HTTPException as http_exc:
                            # Extract retry information if present
                            try:
                                status = getattr(http_exc, 'status', None)
                                retry_after = getattr(http_exc, 'retry_after', None) or getattr(http_exc, 'retry_after_seconds', None)
                            except Exception:
                                status = None
                                retry_after = None

                            # If Discord indicates a Retry-After, honor it and retry the same role
                            ra = None
                            try:
                                ra = float(retry_after) if retry_after is not None else None
                            except Exception:
                                ra = None

                            if status == 429 or (ra is not None):
                                if ra and ra > 0:
                                    logger.warning(f'[ReactionRoles] Rate limited when creating role {name}; retry-after {ra:.1f}s')
                                    print(f"[DEBUG][ReactionRoles] Rate limited creating '{name}' (retry-after {ra:.1f}s)")
                                    # set guild cooldown for long retry-after durations
                                    if ra > 5:
                                        try:
                                            self._guild_cooldowns[guild.id] = time.time() + ra
                                        except Exception:
                                            pass
                                    # notify the user and sleep the indicated retry_after, then retry the same role
                                    try:
                                        await interaction.edit_original_response(content=f'Rate-limited by Discord; waiting {int(ra)}s before retrying...', embed=None)
                                    except Exception:
                                        logger.exception('[ReactionRoles] Failed to notify user about rate limit')
                                    print(f"[DEBUG][ReactionRoles] Sleeping {min(ra, per_role_timeout)}s before retrying role '{name}'")
                                    sleep_for = min(ra, per_role_timeout)
                                    await asyncio.sleep(sleep_for)
                                    # If we've exceeded the per-role patience window, record failure and stop retrying this role
                                    if time.monotonic() - per_role_start > per_role_timeout:
                                        logger.warning(f'[ReactionRoles] Giving up on role {name} after timeout waiting through rate-limits')
                                        print(f"[DEBUG][ReactionRoles] Giving up on role '{name}' after waiting through rate-limits")
                                        failed.append({'index': palette_idx, 'name': name, 'reason': 'rate_limit_timeout'})
                                        break
                                    # otherwise retry this role
                                    continue
                                else:
                                    # No useful retry_after; treat as a failed HTTP error
                                    logger.exception(f'[ReactionRoles] HTTP error creating role for {name} (palette index {palette_idx})')
                                    print(f"[DEBUG][ReactionRoles] HTTP error creating role '{name}' (index {palette_idx})")
                                    failed.append({'index': palette_idx, 'name': name, 'reason': 'http_exception'})
                                    break
                            else:
                                logger.exception(f'[ReactionRoles] HTTP error creating role for {name} (palette index {palette_idx})')
                                print(f"[DEBUG][ReactionRoles] HTTP error creating role '{name}' (index {palette_idx})")
                                failed.append({'index': palette_idx, 'name': name, 'reason': 'http_exception'})
                                break
                        except Exception as e:
                            logger.exception(f'[ReactionRoles] Error creating role for {name} (palette index {palette_idx}): {e}')
                            print(f"[DEBUG][ReactionRoles] Exception creating role '{name}' (index {palette_idx}): {e}")
                            failed.append({'index': palette_idx, 'name': name, 'reason': 'error'})
                            break

                    # If succeeded, record mapping into the partial cfg and persist immediately
                    if 'role' in locals() and role and (palette_idx in success_indices):
                        try:
                            # find mapping info
                            try:
                                pos = indices.index(palette_idx)
                                emoji_val = emoji_choices[pos]
                                hex_val = color_choices[pos][1]
                                name_val = color_choices[pos][0]
                            except Exception:
                                # fallback safe values
                                emoji_val = COLOR_EMOJIS[palette_idx] if palette_idx < len(COLOR_EMOJIS) else None
                                hex_val = COLOR_PALETTE[palette_idx][1] if palette_idx < len(COLOR_PALETTE) else None
                                name_val = COLOR_PALETTE[palette_idx][0] if palette_idx < len(COLOR_PALETTE) else name
                            # append to cfg choices
                            cfg.setdefault('choices', []).append({'emoji': emoji_val, 'id': role.id, 'hex': hex_val, 'name': name_val})
                            try:
                                save_reaction_configs(self.configs)
                            except Exception:
                                logger.exception('[ReactionRoles] Failed to save partial config after creating a role')
                        except Exception:
                            logger.exception('[ReactionRoles] Failed to append created role to partial config')

                    # update progress using actual created/failed counts
                    if (len(created) + len(failed)) - last_progress_update >= 5 or (len(created) + len(failed)) == total:
                        try:
                            await interaction.edit_original_response(content=f'Creating roles... {len(created)}/{total} succeeded, {len(failed)} failed', embed=None)
                        except Exception:
                            pass
                        last_progress_update = len(created) + len(failed)

                # after finishing a batch, pause a bit to allow Discord some breathing room between batches
                if (batch_start + batch_size) < total:
                    try:
                        await asyncio.sleep(5.0)
                    except Exception:
                        pass

            # attempt to move roles to just under the bot's top role
            # Re-fetch bot member to get an up-to-date top role position, then compute desired placements.
                try:
                    bot_member = await guild.fetch_member(self.bot.user.id)
                except Exception:
                    bot_member = guild.get_member(self.bot.user.id)
                bot_top_pos = bot_member.top_role.position if bot_member else 0
            def _build_positions_map(top_pos):
                """Return a mapping of Role->position for the created roles given a top position."""
                pos_map = {}
                for idx, role in enumerate(created):
                    pos = top_pos - 1 - idx
                    if pos < 0:
                        pos = 0
                    pos_map[role] = pos
                return pos_map

            try:
                positions_map = _build_positions_map(bot_top_pos)
                # Submit the position edits in one call using Role->position mapping
                await guild.edit_role_positions(positions=positions_map)
            except Exception:
                logger.exception('[ReactionRoles] Failed to reorder roles; attempting a single retry after refetch')
                # single retry: refetch bot member to refresh top role position and retry once
                try:
                    try:
                        bot_member = await guild.fetch_member(self.bot.user.id)
                    except Exception:
                        bot_member = guild.get_member(self.bot.user.id)
                    bot_top_pos = bot_member.top_role.position if bot_member else bot_top_pos
                    positions_map = _build_positions_map(bot_top_pos)
                    await guild.edit_role_positions(positions=positions_map)
                except Exception:
                    logger.exception('[ReactionRoles] Retry to reorder roles failed')

            # Update the initial partial cfg in-place with the final created choices.
            # We rely on the partial cfg that was appended earlier; find it and replace its choices
            try:
                # build choices list from created roles in the same order
                final_choices = []
                for r in created:
                    # try to find matching palette entry by role name or id
                    # fall back to None for emoji/hex/name if not resolvable
                    entry = next((ch for ch in cfg.get('choices', []) if int(ch.get('id')) == r.id), None)
                    if entry:
                        final_choices.append(entry)
                    else:
                        # best-effort: try to match by name to color_choices
                        matched = None
                        for idx, cr in enumerate(created):
                            if cr.id == r.id:
                                try:
                                    final_choices.append({'emoji': emoji_choices[idx], 'id': r.id, 'hex': color_choices[idx][1], 'name': color_choices[idx][0]})
                                except Exception:
                                    final_choices.append({'emoji': None, 'id': r.id, 'hex': None, 'name': r.name})
                                matched = True
                                break
                        if not matched:
                            final_choices.append({'emoji': None, 'id': r.id, 'hex': None, 'name': r.name})

                cfg['choices'] = final_choices
                # ensure this cfg remains the sole authoritative entry for this config; remove any other empty duplicates
                guild_list = self.configs.setdefault(str(guild.id), [])
                # remove any other entries that have the same base_name but different id and empty choices
                for other in list(guild_list):
                    if other is not cfg and other.get('base_name') == base_name and not other.get('choices'):
                        try:
                            guild_list.remove(other)
                        except Exception:
                            pass
                # persist
                save_reaction_configs(self.configs)
            except Exception:
                logger.exception('[ReactionRoles] Failed to finalize and save config')

            # reply with mapping split into pages of up to 25 fields (Discord limit)
            def build_embed_page(title_suffix, items):
                e = discord.Embed(title=f'✅ Reaction Roles Created {title_suffix}', color=discord.Color.blurple())
                e.add_field(name='Config ID', value=f'`{cfg_id}`', inline=False)
                # add items as fields, grouping 3 per visual row but counting fields directly
                for name, val in items:
                    e.add_field(name=name, value=val, inline=True)
                return e

            # prepare list of display items
            display_items = []
            for choice in cfg['choices']:
                role = guild.get_role(choice['id'])
                if not role:
                    continue
                display_items.append((f"{choice['emoji']} — {role.name}", '\u200b'))

            # paginate into chunks where each embed has at most 25 fields (we already reserve 1 for cfg id)
            max_fields_per_embed = 25
            # available slots for choice fields per embed
            slots = max_fields_per_embed - 1
            pages = [display_items[i:i+slots] for i in range(0, len(display_items), slots)]

            # send first page with edit_original_response
            if pages:
                first_embed = build_embed_page(f'(1/{len(pages)})', pages[0])
                await interaction.edit_original_response(embed=first_embed)
                # send subsequent pages as followups
                for idx, page_items in enumerate(pages[1:], start=2):
                    e = build_embed_page(f'({idx}/{len(pages)})', page_items)
                    try:
                        await interaction.followup.send(embed=e)
                    except Exception:
                        logger.exception('[ReactionRoles] Failed to send followup embed for additional page')
            else:
                # no display items; still confirm
                embed = discord.Embed(title='✅ Reaction Roles Created', color=discord.Color.blurple())
                embed.add_field(name='Config ID', value=f'`{cfg_id}`', inline=False)
                await interaction.edit_original_response(embed=embed)

            # On successful completion, update cooldown timestamp definitively
            try:
                cds = _load_cooldowns()
                gid = str(guild.id)
                uid = str(interaction.user.id)
                cds.setdefault('guilds', {}).setdefault(gid, {}).setdefault(uid, {})['last_create'] = int(time.time())
                _save_cooldowns(cds)
            except Exception:
                pass
        except discord.Forbidden as e:
            # Explicitly handle missing permissions / hierarchy issues so operator sees the reason
            logger.exception('[ReactionRoles] Permission error while creating roles')
            print(f"[ERROR][ReactionRoles] Forbidden: {e}")
            embed = discord.Embed(title='❌ Failed to create roles - Permission Error', description='I do not have sufficient permissions or my role is too low in the hierarchy to create/manage roles.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
        except Exception as e:
            # Log and surfacing exception details so failure is not silently swallowed
            logger.exception('[ReactionRoles] Failed to create roles')
            print(f"[ERROR][ReactionRoles] Exception during create_roles: {e}")
            embed = discord.Embed(title='❌ Failed to create roles', description=f'An unexpected error occurred: {type(e).__name__}: {e}', color=discord.Color.red())
            try:
                await interaction.edit_original_response(embed=embed)
            except Exception:
                # if we cannot edit the original response, attempt a followup
                try:
                    await interaction.followup.send(embed=embed)
                except Exception:
                    logger.exception('[ReactionRoles] Additionally failed to notify user about the create_roles failure')

    @app_commands.command(name='reactionroles_post', description='Post a reaction-roles message for a previously created role set')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(config_id='Config ID from reactionroles_create', channel='Channel to post in', message='Optional message to post (leave blank to omit description)', title='Optional title for the posted embed')
    async def post_message(self, interaction: Interaction, config_id: str, channel: discord.TextChannel, message: Optional[str] = None, title: Optional[str] = None):
        # Defer immediately (public response) so we can edit it later.
        await interaction.response.defer(thinking=True, ephemeral=False)
        debug_command('reactionroles_post', interaction.user, guild=interaction.guild, channel=channel, config_id=config_id)
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            await interaction.edit_original_response(content='❌ You do not have permission to use this command.')
            return

        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        cfg = next((c for c in guild_cfgs if c.get('id') == config_id), None)
        if not cfg:
            embed = discord.Embed(title='❌ Config Not Found', description='Config ID not found for this server.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

        # support new 'choices' format, fall back to legacy 'roles'/'emojis'
        choices = cfg.get('choices')
        if not choices:
            # legacy: rebuild choices from roles + emojis
            roles_list = cfg.get('roles', [])
            emojis = cfg.get('emojis', [])
            choices = []
            for idx, rid_entry in enumerate(roles_list):
                if isinstance(rid_entry, dict):
                    rid = rid_entry.get('id')
                    hexv = rid_entry.get('hex')
                else:
                    rid = int(rid_entry)
                    hexv = None
                emoji = emojis[idx] if idx < len(emojis) else None
                choices.append({'emoji': emoji, 'id': rid, 'hex': hexv, 'name': None})
        # send message and add reactions
        try:
            # build emoji->role mapping from choices list (preserves pairing)
            # We'll paginate the mapping across multiple embeds so none exceed Discord's 25-field limit.
            items = []  # list of (emoji, role_id, role_name)
            for c in choices:
                emoji = c.get('emoji')
                role_id = c.get('id')
                role = interaction.guild.get_role(role_id)
                if not role or not emoji:
                    continue
                items.append((emoji, role_id, role.name))

            if not items:
                # nothing to post (no valid roles/emojis)
                embed = discord.Embed(title='❌ Nothing to Post', description='No valid role/emojis found for this config.', color=discord.Color.orange())
                await interaction.edit_original_response(embed=embed)
                return

            # Discord limits: max 25 embed fields per embed, and max 20 distinct reactions per message.
            # We must ensure we never attempt to add more than 20 reactions per message, so page size
            # is set to 20 (safe for both embed and reaction limits).
            page_size = 20
            pages = [items[i:i+page_size] for i in range(0, len(items), page_size)]

            posted_entries = []
            for page_index, page_items in enumerate(pages, start=1):
                if page_index == 1:
                    # If a title is provided, use it; otherwise use a page counter as the title.
                    if title:
                        if message:
                            e = discord.Embed(title=title + f' ({page_index}/{len(pages)})', description=message, color=discord.Color.blurple())
                        else:
                            e = discord.Embed(title=title + f' ({page_index}/{len(pages)})', color=discord.Color.blurple())
                    else:
                        if message:
                            e = discord.Embed(description=message, color=discord.Color.blurple())
                            e.title = f'({page_index}/{len(pages)})'
                        else:
                            # No title and no message: use page counter as title and no description
                            e = discord.Embed(title=f'({page_index}/{len(pages)})', color=discord.Color.blurple())
                else:
                    e = discord.Embed(title=f'({page_index}/{len(pages)})', color=discord.Color.blurple())

                # add mapping fields (inline=True for compactness)
                for emoji, rid, rname in page_items:
                    e.add_field(name=f"{emoji} — {rname}", value='\u200b', inline=True)

                try:
                    sent = await channel.send(embed=e)
                except Exception:
                    logger.exception('[ReactionRoles] Failed to send paginated embed page')
                    # on failure, continue to attempt remaining pages but record nothing for this page
                    continue

                # add reactions for emojis on this page
                emoji_map_page = {}
                for emoji, rid, _ in page_items:
                    try:
                        await sent.add_reaction(emoji)
                    except Exception:
                        logger.exception(f'[ReactionRoles] Failed to add reaction {emoji} to message {sent.id}')
                    emoji_map_page[emoji] = rid

                # persist mapping for this posted message
                mapping = {
                    'guild_id': interaction.guild.id,
                    'channel_id': channel.id,
                    'message_id': sent.id,
                    'emoji_map': emoji_map_page,
                    'config_id': config_id
                }
                self.configs.setdefault(str(interaction.guild.id), []).append({'posted': mapping})
                posted_entries.append(mapping)

            # save all posted mappings (if any)
            try:
                save_reaction_configs(self.configs)
            except Exception:
                logger.exception('[ReactionRoles] Failed to save posted mappings')

            # confirmation embed
            if posted_entries:
                embed = discord.Embed(title='✅ Reaction Roles Posted', description=f'Posted {len(posted_entries)} message(s) in {channel.mention}', color=discord.Color.green())
            else:
                embed = discord.Embed(title='❌ Failed to Post', description='Unable to send any pages to the channel.', color=discord.Color.red())

            await interaction.edit_original_response(embed=embed)
        except Exception:
            logger.exception('[ReactionRoles] Failed to post reaction roles message')
            embed = discord.Embed(title='❌ Failed to post message', description='Check my permissions in the channel.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='reactionroles_remove', description='Remove a previously created color role set (deletes roles)')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(config_id='Config ID from reactionroles_create')
    async def remove_roles(self, interaction: Interaction, config_id: str):
        # Defer immediately (public response) so we can edit it later.
        await interaction.response.defer(thinking=True, ephemeral=False)
        debug_command('reactionroles_remove', interaction.user, guild=interaction.guild, config_id=config_id)
        is_admin = interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator
        app_owner = await self.bot.application_info()
        if not (is_admin or interaction.user.id == app_owner.owner.id):
            embed = discord.Embed(title='❌ Permission Denied', description='You do not have permission to use this command.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        cfg_index = None
        cfg = None
        for idx, c in enumerate(guild_cfgs):
            if c.get('id') == config_id:
                cfg_index = idx
                cfg = c
                break

        if cfg is None:
            embed = discord.Embed(title='❌ Config Not Found', description='Config ID not found for this server.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

    

        # Delete the roles created by this config
        failed = []
        # collect role ids from either legacy 'roles' or new 'choices'
        removed_role_ids = set()
        # new format: choices list with entries having 'id'
        for choice in cfg.get('choices', []):
            rid = choice.get('id') if isinstance(choice, dict) else None
            if rid:
                removed_role_ids.add(int(rid))
        # legacy format: roles may be list of ids or dicts
        for rid_entry in cfg.get('roles', []):
            if isinstance(rid_entry, dict):
                rid = rid_entry.get('id')
            else:
                try:
                    rid = int(rid_entry)
                except Exception:
                    rid = None
            if rid:
                removed_role_ids.add(int(rid))

        failed = []
        for rid in list(removed_role_ids):
            role = interaction.guild.get_role(rid)
            if role:
                try:
                    await role.delete(reason=f'ReactionRoles removal by {interaction.user}')
                except Exception:
                    logger.exception(f'[ReactionRoles] Failed to delete role {rid}')
                    failed.append(rid)

        # Update config and posted mappings based on which roles were actually deleted.
        try:
            # compute which roles were successfully deleted
            failed_set = set(failed)
            deleted_role_ids = {rid for rid in removed_role_ids if rid not in failed_set}

            if cfg_index is not None:
                if failed:
                    # Partial failure: remove only the successfully deleted roles from the stored config
                    # Update 'choices' to remove deleted ids
                    if isinstance(cfg, dict) and cfg.get('choices'):
                        cfg['choices'] = [ch for ch in cfg.get('choices', []) if int(ch.get('id')) not in deleted_role_ids]
                    # Update legacy 'roles' list as well
                    if isinstance(cfg, dict) and cfg.get('roles'):
                        new_roles = []
                        for r in cfg.get('roles', []):
                            try:
                                rid = r.get('id') if isinstance(r, dict) else int(r)
                            except Exception:
                                rid = None
                            if rid is None or rid not in deleted_role_ids:
                                new_roles.append(r)
                        cfg['roles'] = new_roles
                    # write back the updated cfg
                    guild_cfgs[cfg_index] = cfg
                else:
                    # All roles deleted successfully: remove the entire config
                    guild_cfgs.pop(cfg_index)

            # For posted mappings, remove emoji entries that referenced deleted roles; if a posted mapping has no emojis left,
            # attempt to delete the posted message and remove that mapping entry entirely.
            to_remove_entries = []
            for entry in list(guild_cfgs):
                if entry.get('posted'):
                    mapping = entry['posted']
                    emoji_map = mapping.get('emoji_map', {}) or {}
                    # keys where mapped role id is in deleted_role_ids
                    keys_to_remove = [k for k, v in list(emoji_map.items()) if (isinstance(v, int) and v in deleted_role_ids) or (isinstance(v, str) and v.isdigit() and int(v) in deleted_role_ids)]
                    for k in keys_to_remove:
                        emoji_map.pop(k, None)
                    if not emoji_map:
                        # no emojis left; best-effort delete the posted message then remove the mapping
                        try:
                            ch = self.bot.get_channel(mapping.get('channel_id'))
                            if ch:
                                msg = await ch.fetch_message(mapping.get('message_id'))
                                try:
                                    await msg.delete()
                                except Exception:
                                    logger.exception('[ReactionRoles] Failed to delete posted reaction roles message')
                        except Exception:
                            logger.exception('[ReactionRoles] Error while attempting to remove posted mapping')
                        to_remove_entries.append(entry)
                    else:
                        # update mapping's emoji_map to the pruned map
                        mapping['emoji_map'] = emoji_map

            for entry in to_remove_entries:
                try:
                    guild_cfgs.remove(entry)
                except ValueError:
                    pass

            # save updated configs
            self.configs[str(interaction.guild.id)] = guild_cfgs
            save_reaction_configs(self.configs)
        except Exception:
            logger.exception('[ReactionRoles] Failed to update config after role removal')

        # Inform the user of the result
        if failed:
            embed = discord.Embed(title='⚠️ Partial Failure', description=f'Failed to delete roles: {failed}', color=discord.Color.orange())
            embed.add_field(name='Note', value='Config updated to remove successfully deleted roles; entries for any remaining roles were preserved so you can retry removal after fixing permissions.', inline=False)
            await interaction.edit_original_response(embed=embed)
        else:
            embed = discord.Embed(title='✅ Removed', description=f'Removed roles for config `{config_id}`', color=discord.Color.green())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='reaction_list', description='List reaction-role configs and posted mappings for this server')
    @app_commands.checks.has_permissions(manage_roles=True)
    async def reaction_list(self, interaction: Interaction):
        # Defer immediately (public response)
        await interaction.response.defer(thinking=True, ephemeral=False)
        guild_cfgs = self.configs.get(str(interaction.guild.id), [])
        if not guild_cfgs:
            embed = discord.Embed(title='No Reaction Roles', description='No reaction role configs found for this server.', color=discord.Color.orange())
            await interaction.edit_original_response(embed=embed)
            return

        embed = discord.Embed(title='Reaction Role Configs', color=discord.Color.blurple())
        for c in guild_cfgs:
            # created configs
            if c.get('id'):
                cid = c.get('id')
                base = c.get('base_name') or ''
                # build a compact representation of choices
                choices = c.get('choices') or []
                if choices:
                    parts = []
                    for ch in choices:
                        emoji = ch.get('emoji') or ''
                        name = ch.get('name') or ''
                        # if name missing, try to resolve via guild
                        try:
                            rid = ch.get('id')
                            role = interaction.guild.get_role(rid) if rid else None
                            if role:
                                name = role.name
                        except Exception:
                            pass
                        parts.append(f"{emoji} {name}" if name else f"{emoji}")
                    # join with bullets, truncate if too long
                    summary = ' · '.join(parts)
                    if len(summary) > 500:
                        summary = summary[:497] + '...'
                else:
                    summary = '(no choices)'
                embed.add_field(name=f'Config {cid} — {base}', value=summary, inline=False)

            # posted mappings
            if c.get('posted'):
                posted = c['posted']
                ch = self.bot.get_channel(posted.get('channel_id'))
                chname = ch.mention if ch else f"Channel ID {posted.get('channel_id')}"
                # don't show numeric message id
                emoji_map = posted.get('emoji_map', {})
                # show emoji list only
                emojis = ', '.join(list(emoji_map.keys())) if emoji_map else '(no reactions)'
                embed.add_field(name=f'Posted in {chname}', value=f'Reactions: {emojis}', inline=False)

        await interaction.edit_original_response(embed=embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # handle role assignment
        try:
            guild_id = str(payload.guild_id)
            cfgs = self.configs.get(guild_id, [])
            # find a posted mapping containing this message
            mapping = None
            for c in cfgs:
                if c.get('posted') and c['posted'].get('message_id') == payload.message_id:
                    mapping = c['posted']
                    break
            if not mapping:
                return

            emoji = str(payload.emoji)
            role_id = mapping['emoji_map'].get(emoji)
            if not role_id:
                return
            guild = self.bot.get_guild(int(mapping['guild_id']))
            if not guild:
                return
            member = guild.get_member(payload.user_id)
            if not member or member.bot:
                return
            role = guild.get_role(role_id)
            if not role:
                return
            await member.add_roles(role, reason='Reaction role added')
        except Exception:
            logger.exception('[ReactionRoles] Error in on_raw_reaction_add')

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # handle role removal when reaction removed
        try:
            guild_id = str(payload.guild_id)
            cfgs = self.configs.get(guild_id, [])
            mapping = None
            for c in cfgs:
                if c.get('posted') and c['posted'].get('message_id') == payload.message_id:
                    mapping = c['posted']
                    break
            if not mapping:
                return
            emoji = str(payload.emoji)
            role_id = mapping['emoji_map'].get(emoji)
            if not role_id:
                return
            guild = self.bot.get_guild(int(mapping['guild_id']))
            if not guild:
                return
            member = guild.get_member(payload.user_id)
            if not member or member.bot:
                return
            role = guild.get_role(role_id)
            if not role:
                return
            await member.remove_roles(role, reason='Reaction role removed')
        except Exception:
            logger.exception('[ReactionRoles] Error in on_raw_reaction_remove')


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
