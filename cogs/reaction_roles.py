import discord
from discord.ext import commands
from discord import app_commands, Interaction
import os
import json
import logging
import hashlib
from typing import Optional
import random
from utils.debug import debug_command

logger = logging.getLogger('jeng.reactionroles')
logger.setLevel(logging.INFO)

REACTION_FILE = 'reaction_roles.json'

# Curated palette from the user's provided list with emoji mappings.
# Length must match between COLOR_EMOJIS and COLOR_PALETTE so indexes stay paired.
COLOR_EMOJIS = [
    # --- original standard colors (preserved) ---

    '⬜',  # White
    '🟧',  # Orange (orange square)
    '▫️',  # Sand (small pale square)
    '⬛',  # Black
    '🟥',  # Red
    '🍷',  # Maroon (wine glass)
    '🟨',  # Yellow
    '🌿',  # Olive (leaf)
    '🟩',  # Lime
    '💚',  # Green
    '🌊',  # Aqua
    '🔹',  # Teal-ish diamond
    '💙',  # Blue
    '🔵',  # Navy (blue circle)
    '💖',  # Pink

    # --- previously added curated colors (kept) ---
    '🟪',  # Zero (deep blue / unique purple square)
    '🟩',  # Acid green (lime square as closest)
    '🔷',  # Aero (light blue diamond)
    '💜',  # African violet
    '💧',  # Air superiority blue (droplet)
    '🩸',  # Alizarin (red droplet)
    '🟫',  # Almond (brown square)
    '🟠',  # Amber (orange square)
    '🔮',  # Amethyst (purple / crystal)
    '🤖',  # Android green (fun robot)
    '🕊️',  # Antique white (off-white / dove)
    '🧿',  # Azure (nazar)
    '🐬',  # Baby blue (dolphin)
    '🧡',  # Coral
    '🌲',  # Forest green
    '❤️',  # Crimson

    # --- batch 2 additions from the new list ---
    '⚪',  # Gainsboro
    '🔶',  # Gamboge
    '🌱',  # Generic viridian
    '✨',  # Ghost white (sparkle)
    '💠',  # Glaucous
    '🪴',  # GO green (plant)
    '🥇',  # Gold (web)
    '🌾',  # Goldenrod
    '🪨',  # Granite gray
    '🍏',  # Granny Smith apple
    '🦎',  # Green Lizard
    '⚙️',  # Gunmetal
    '🌻',  # Harvest gold
    '🔥',  # Heat Wave
    '💮',  # Heliotrope
    '🌀',  # Honolulu blue (swirl)
]

# --- appended batch 3 (more from user's list, non-repeating) ---
COLOR_EMOJIS += [
    '🌸',  # Nadeshiko pink
    '🌕',  # Naples yellow
    '🥖',  # Navajo white (bread/tan)
    '🔵',  # Navy blue
    '🇳',  # Navy blue (Crayola) - letter N as fallback
    '💙',  # Neon blue
    '🟢',  # Neon green
    '💗',  # Neon fuchsia
    '🚗',  # New Car
    '🌆',  # New York pink
    '🔩',  # Nickel
    '💧',  # Non-photo blue
    '🍃',  # Nyanza
    '🟤',  # Ocher (Ochre)
    '🍷',  # Old burgundy
    '🥇',  # Old gold
]

# 16 curated color names and hex codes taken from the user's list (subset)
COLOR_PALETTE = [
    # --- original standard colors (preserved) ---
    ("White", "#FFFFFF"),
    ("Orange", "#FF8C00"),
    ("Sand", "#EDC9AF"),
    ("Black", "#020202"),
    ("Red", "#FF0000"),
    ("Maroon", "#800000"),
    ("Yellow", "#FFFF00"),
    ("Olive", "#808000"),
    ("Lime", "#00FF00"),
    ("Green", "#008000"),
    ("Aqua", "#00FFFF"),
    ("Teal", "#008080"),
    ("Blue", "#0000FF"),
    ("Navy", "#000080"),
    ("Pink", "#FF00FF"),

    # --- previously added curated colors (kept) ---
    ("Zero", "#0048BA"),
    ("Acid green", "#B0BF1A"),
    ("Aero", "#7CB9E8"),
    ("African violet", "#B284BE"),
    ("Air superiority blue", "#72A0C1"),
    ("Alizarin", "#DB2D43"),
    ("Almond", "#EED9C4"),
    ("Amber", "#FFBF00"),
    ("Amethyst", "#9966CC"),
    ("Android green", "#3DDC84"),
    ("Antique white", "#FAEBD7"),
    ("Azure", "#007FFF"),
    ("Baby blue", "#89CFF0"),
    ("Coral", "#FF7F50"),
    ("Forest green", "#228B22"),
    ("Crimson", "#DC143C"),

    # --- batch 2 additions from the user's list ---
    ("Gainsboro", "#DCDCDC"),
    ("Gamboge", "#E49B0F"),
    ("Generic viridian", "#007F66"),
    ("Ghost white", "#F8F8FF"),
    ("Glaucous", "#6082B6"),
    ("GO green", "#00AB66"),
    ("Gold (web)", "#FFD700"),
    ("Goldenrod", "#DAA520"),
    ("Granite gray", "#676767"),
    ("Granny Smith apple", "#A8E4A0"),
    ("Green Lizard", "#A7F432"),
    ("Gunmetal", "#2a3439"),
    ("Harvest gold", "#DA9100"),
    ("Heat Wave", "#FF7A00"),
    ("Heliotrope", "#DF73FF"),
    ("Honolulu blue", "#006DB0"),
]

# --- appended batch 3 palette entries (non-repeating) ---
COLOR_PALETTE += [
    ("Nadeshiko pink", "#F6ADC6"),
    ("Naples yellow", "#FADA5E"),
    ("Navajo white", "#FFDEAD"),
    ("Navy blue", "#000080"),
    ("Navy blue (Crayola)", "#1974D2"),
    ("Neon blue", "#4666FF"),
    ("Neon green", "#39FF14"),
    ("Neon fuchsia", "#FE4164"),
    ("New Car", "#214FC6"),
    ("New York pink", "#D7837F"),
    ("Nickel", "#727472"),
    ("Non-photo blue", "#A4DDED"),
    ("Nyanza", "#E9FFDB"),
    ("Ocher (Ochre)", "#CC7722"),
    ("Old burgundy", "#43302E"),
    ("Old gold", "#CFB53B"),
]

# --- appended extra batch 4 (user-requested, no repeats) ---
COLOR_EMOJIS += [
    '🍇',  # Plum
    '🟣',  # Plum (web)
    '🦄',  # Plump Purple
    '🎍',  # Polished Pine
    '👑',  # Pomp and Power
    '🌟',  # Popstar
    '🟠',  # Portland Orange
    '🧊',  # Powder blue
    '🎓',  # Princeton orange
    '🧪',  # Process Cyan
    '🟦',  # Prussian blue
    '🌈',  # Psychedelic purple
]

COLOR_PALETTE += [
    ("Plum", "#8E4585"),
    ("Plum (web)", "#DDA0DD"),
    ("Plump Purple", "#5946B2"),
    ("Polished Pine", "#5DA493"),
    ("Pomp and Power", "#86608E"),
    ("Popstar", "#BE4F62"),
    ("Portland Orange", "#FF5A36"),
    ("Powder blue", "#B0E0E6"),
    ("Princeton orange", "#F58025"),
    ("Process Cyan", "#00B9F2"),
    ("Prussian blue", "#003153"),
    ("Psychedelic purple", "#DF00FF"),
]

# --- appended extra batch 5 (Red..Rose) ---
COLOR_EMOJIS += [
    '🌶️',  # Red Salsa
    '🔺',  # Red-violet
    '🎨',  # Red-violet (Crayola)
    '🟥',  # Red-violet (Color wheel)
    '🌲',  # Redwood
    '🔷',  # Resolution blue
    '🎵',  # Rhythm
    '⬛',  # Rich black
    '⚫',  # Rich black (FOGRA29)
    '◾',  # Rich black (FOGRA39)
    '🥒',  # Rifle green
    '🥚',  # Robin egg blue
    '🚀',  # Rocket metallic
    '🚩',  # Rojo Spanish red
    '🪙',  # Roman silver
    '🌹',  # Rose
]

COLOR_PALETTE += [
    ("Red Salsa", "#FF2400"),
    ("Red-violet", "#C71585"),
    ("Red-violet (Crayola)", "#C0448F"),
    ("Red-violet (Color wheel)", "#922B3E"),
    ("Redwood", "#A45A52"),
    ("Resolution blue", "#002387"),
    ("Rhythm", "#777696"),
    ("Rich black", "#004040"),
    ("Rich black (FOGRA29)", "#010B13"),
    ("Rich black (FOGRA39)", "#010203"),
    ("Rifle green", "#444C38"),
    ("Robin egg blue", "#00CCCC"),
    ("Rocket metallic", "#8A7F80"),
    ("Rojo Spanish red", "#A91101"),
    ("Roman silver", "#838996"),
    ("Rose", "#FF007F"),
]

# --- appended extra batch 6 (Safety..Seal) ---
COLOR_EMOJIS += [
    '🟨',  # Safety yellow
    '🟡',  # Saffron
    '🌿',  # Sage
    '🇮',  # St. Patrick's blue (I as fallback)
    '🍣',  # Salmon
    '🌸',  # Salmon pink
    '🏖️',  # Sand
    '🏜️',  # Sand dune
    '🟤',  # Sandy brown
    '🌾',  # Sap green
    '🔷',  # Sapphire
    '🔵',  # Sapphire blue
    '🔵',  # Sapphire (Crayola)
    '🥇',  # Satin sheen gold
    '🚩',  # Scarlet
    '💗',  # Schauss pink
    '🚌',  # School bus yellow
    '💚',  # Screamin' Green
    '🌊',  # Sea green
    '🩵',  # Sea green (Crayola)
    '🔮',  # Seance
    '🟫',  # Seal brown
]

COLOR_PALETTE += [
    ("Safety yellow", "#EED202"),
    ("Saffron", "#F4C430"),
    ("Sage", "#BCB88A"),
    ("St. Patrick's blue", "#23297A"),
    ("Salmon", "#FA8072"),
    ("Salmon pink", "#FF91A4"),
    ("Sand", "#C2B280"),
    ("Sand dune", "#967117"),
    ("Sandy brown", "#F4A460"),
    ("Sap green", "#507D2A"),
    ("Sapphire", "#0F52BA"),
    ("Sapphire blue", "#0067A5"),
    ("Sapphire (Crayola)", "#2D5DA1"),
    ("Satin sheen gold", "#CBA135"),
    ("Scarlet", "#FF2400"),
    ("Schauss pink", "#FF91AF"),
    ("School bus yellow", "#FFD800"),
    ("Screamin' Green", "#66FF66"),
    ("Sea green", "#2E8B57"),
    ("Sea green (Crayola)", "#00FFCD"),
    ("Seance", "#612086"),
    ("Seal brown", "#59260B"),
]

# --- appended final batch 7 (Tyrian..Zomp) ---
COLOR_EMOJIS += [
    '🟪',  # Tyrian purple
    '🔵',  # UA blue
    '🔴',  # UA red
    '🔮',  # Ultramarine
    '🔷',  # Ultramarine blue
    '🌸',  # Ultra pink
    '🍒',  # Ultra red
    '🌰',  # Umber
    '🧴',  # Unbleached silk
    '🌐',  # United Nations blue
    '🎓',  # University of Pennsylvania red
    '🟨',  # Unmellow yellow
    '🌲',  # UP Forest green
    '🟥',  # UP maroon
    '🚩',  # Upsdell red
    '🌊',  # Uranian blue
    '🛩️', # USAFA blue
    '🟫',  # Van Dyke brown
    '🍦',  # Vanilla
    '🍨',  # Vanilla ice
    '🔵',  # Vantg blue
    '🥇',  # Vegas gold
    '🚗',  # Venetian red
    '🪙',  # Verdigris
    '🔶',  # Vermilion
    '🔶',  # Vermilion (alt)
    '🟪',  # Veronica
    '🟣',  # Violet
    '🟣',  # Violet (color wheel)
    '🟪',  # Violet (crayola)
    '🟪',  # Violet (RYB)
    '💜',  # Violet (web)
    '🔵',  # Violet-blue
    '🔵',  # Violet-blue (Crayola)
    '🌺',  # Violet-red
    '🌺',  # Violet-red(PerBang)
    '🫧',  # Viridian
    '🟩',  # Viridian green
    '🟥',  # Vivid burgundy
    '🔵',  # Vivid sky blue
    '🟠',  # Vivid tangerine
    '🟪',  # Vivid violet
    '⚡',  # Volt
    '⬛',  # Warm black
    '🔵',  # Weezy Blue
    '🌾',  # Wheat
    '⬜',  # White
    '🔵',  # Wild blue yonder
    '🌸',  # Wild orchid
    '🍓',  # Wild Strawberry
    '🍉',  # Wild watermelon
    '🍊',  # Willpower orange
    '🟫',  # Windsor tan
    '🍷',  # Wine
    '🟥',  # Wine Red
    '🟫',  # Wine dregs
    '❄️',  # Winter Sky
    '🟩',  # Wintergreen Dream
    '🌸',  # Wisteria
    '🟫',  # Wood brown
    '🟫',  # Xanadu
    '🟨',  # Xanthic
    '🟨',  # Xanthous
    '🔵',  # Yale Blue
    '🟨',  # Yellow
    '🟨',  # Yellow (Crayola)
    '🟨',  # Yellow (Munsell)
    '🟨',  # Yellow (NCS)
    '🟨',  # Yellow (Pantone)
    '🟨',  # Yellow (process)
    '🟨',  # Yellow (RYB)
    '🟩',  # Yellow-green
    '🟩',  # Yellow-green (Crayola)
    '🟩',  # Yellow-green (Color Wheel)
    '🟠',  # Yellow Orange
    '🟠',  # Yellow Orange (Color Wheel)
    '🟨',  # Yellow Rose
    '🟨',  # Yellow Sunshine
    '🔵',  # YInMn Blue
    '🟦',  # Zaffer (Zaffre)
    '🟠',  # Zarqa
    '⬜',  # Zebra White
    '⬜',  # Zinc white
    '🟫',  # Zinnwaldite brown
    '🟪',  # Zinzolin
    '🟩',  # Zomp
]

COLOR_PALETTE += [
    ("Tyrian purple", "#66023C"),
    ("UA blue", "#0033AA"),
    ("UA red", "#D9004C"),
    ("Ultramarine", "#3F00FF"),
    ("Ultramarine blue", "#4166F5"),
    ("Ultra pink", "#FF6FFF"),
    ("Ultra red", "#FC6C85"),
    ("Umber", "#635147"),
    ("Unbleached silk", "#FFDDCA"),
    ("United Nations blue", "#009EDB"),
    ("University of Pennsylvania red", "#A50021"),
    ("Unmellow yellow", "#FFFF66"),
    ("UP Forest green", "#014421"),
    ("UP maroon", "#7B1113"),
    ("Upsdell red", "#AE2029"),
    ("Uranian blue", "#AFDBF5"),
    ("USAFA blue", "#004F98"),
    ("Van Dyke brown", "#664228"),
    ("Vanilla", "#F3E5AB"),
    ("Vanilla ice", "#F38FA9"),
    ("Vantg blue", "#5271FF"),
    ("Vegas gold", "#C5B358"),
    ("Venetian red", "#C80815"),
    ("Verdigris", "#43B3AE"),
    ("Vermilion", "#E34234"),
    ("Vermilion (alt)", "#D9381E"),
    ("Veronica", "#A020F0"),
    ("Violet", "#8F00FF"),
    ("Violet (color wheel)", "#7F00FF"),
    ("Violet (crayola)", "#963D7F"),
    ("Violet (RYB)", "#8601AF"),
    ("Violet (web)", "#EE82EE"),
    ("Violet-blue", "#324AB2"),
    ("Violet-blue (Crayola)", "#766EC8"),
    ("Violet-red", "#F75394"),
    ("Violet-red(PerBang)", "#F0599C"),
    ("Viridian", "#40826D"),
    ("Viridian green", "#009698"),
    ("Vivid burgundy", "#9F1D35"),
    ("Vivid sky blue", "#00CCFF"),
    ("Vivid tangerine", "#FFA089"),
    ("Vivid violet", "#9F00FF"),
    ("Volt", "#CEFF00"),
    ("Warm black", "#004242"),
    ("Weezy Blue", "#189BCC"),
    ("Wheat", "#F5DEB3"),
    ("White", "#FFFFFF"),
    ("Wild blue yonder", "#A2ADD0"),
    ("Wild orchid", "#D470A2"),
    ("Wild Strawberry", "#FF43A4"),
    ("Wild watermelon", "#FC6C85"),
    ("Willpower orange", "#FD5800"),
    ("Windsor tan", "#A75502"),
    ("Wine", "#722F37"),
    ("Wine Red", "#B11226"),
    ("Wine dregs", "#673147"),
    ("Winter Sky", "#FF007C"),
    ("Wintergreen Dream", "#56887D"),
    ("Wisteria", "#C9A0DC"),
    ("Wood brown", "#C19A6B"),
    ("Xanadu", "#738678"),
    ("Xanthic", "#EEED09"),
    ("Xanthous", "#F1B42F"),
    ("Yale Blue", "#00356B"),
    ("Yellow", "#FFFF00"),
    ("Yellow (Crayola)", "#FCE883"),
    ("Yellow (Munsell)", "#EFCC00"),
    ("Yellow (NCS)", "#FFD300"),
    ("Yellow (Pantone)", "#FEDF00"),
    ("Yellow (process)", "#FFEF00"),
    ("Yellow (RYB)", "#FEFE33"),
    ("Yellow-green", "#9ACD32"),
    ("Yellow-green (Crayola)", "#C5E384"),
    ("Yellow-green (Color Wheel)", "#30B21A"),
    ("Yellow Orange", "#FFAE42"),
    ("Yellow Orange (Color Wheel)", "#FF9505"),
    ("Yellow Rose", "#FFF000"),
    ("Yellow Sunshine", "#FFF700"),
    ("YInMn Blue", "#2E5090"),
    ("Zaffer (Zaffre)", "#0014A8"),
    ("Zarqa", "#FF4500"),
    ("Zebra White", "#F5F5F5"),
    ("Zinc white", "#FDF8FF"),
    ("Zinnwaldite brown", "#2C1608"),
    ("Zinzolin", "#6C0277"),
    ("Zomp", "#39A78E"),
]

# Normalize palette: remove minor/name-variant duplicates for specific canonical bases
# Keep the first occurrence for each canonical base (e.g., 'Yellow', 'Violet'). This removes
# entries like 'Yellow (Crayola)', 'Violet (color wheel)' while preserving the main 'Yellow' and 'Violet'.
def _dedupe_by_base(palette, emojis, canonical_bases=None):
    if canonical_bases is None:
        canonical_bases = {'Yellow', 'Violet'}
    keep = []
    keep_emojis = []
    seen_base = set()
    for (name, hexv), emoji in zip(palette, emojis):
        base = name.split('(', 1)[0].strip()
        # if this base is canonical and we've already kept one, skip this variant
        if base in canonical_bases:
            if base in seen_base:
                continue
            seen_base.add(base)
            keep.append((name, hexv))
            keep_emojis.append(emoji)
        else:
            keep.append((name, hexv))
            keep_emojis.append(emoji)
    return keep, keep_emojis

# Apply dedupe in-place
COLOR_PALETTE, COLOR_EMOJIS = _dedupe_by_base(COLOR_PALETTE, COLOR_EMOJIS, canonical_bases={'Yellow', 'Violet'})

# Maximum number of available colors (dynamic)
MAX_COLOR_COUNT = min(len(COLOR_PALETTE), 75)


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


class ReactionRoles(commands.Cog):
    """Create color roles and post reaction-role messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.configs = load_reaction_configs()  # guild_id -> list of configs

    async def cog_unload(self):
        pass

    def _make_config_id(self, guild_id: int, base_name: str) -> str:
        h = hashlib.sha1(f"{guild_id}:{base_name}:{os.urandom(8)}".encode('utf-8')).hexdigest()
        return h[:8]

    @app_commands.command(name='reactionroles_create', description='Create 1..N color roles under the bot\'s top role')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(count=f'Number of color roles to create (1-{MAX_COLOR_COUNT})', base_name='Base name for the roles')
    async def create_roles(self, interaction: Interaction, count: int, base_name: Optional[str] = 'Color'):
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

        guild = interaction.guild
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            await interaction.edit_original_response(content='❌ Could not determine bot member in this guild.')
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
            # sample indices so emojis remain tied to their matching colors
            indices = random.sample(range(len(COLOR_PALETTE)), k=count)
            color_choices = [COLOR_PALETTE[i] for i in indices]
            emoji_choices = [COLOR_EMOJIS[i] for i in indices]
            for idx, (color_name, hexcode) in enumerate(color_choices):
                name = f"{color_name}"
                # parse hex to int for discord.Color
                try:
                    v = int(hexcode.lstrip('#'), 16)
                    colour = discord.Color(v)
                except Exception:
                    colour = discord.Color.default()
                role = await guild.create_role(name=name, colour=colour, reason=f'Reaction roles created by {interaction.user}')
                created.append(role)

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

            # persist this role set as a config. store choices as paired entries
            cfg_id = self._make_config_id(guild.id, base_name)
            cfg = {
                'id': cfg_id,
                'base_name': base_name,
                # choices is a list of {'emoji', 'id', 'hex', 'name'} so emoji/color/role stay together
                'choices': [
                    {
                        'emoji': emoji_choices[idx],
                        'id': r.id,
                        'hex': color_choices[idx][1],
                        'name': color_choices[idx][0]
                    }
                    for idx, r in enumerate(created)
                ]
            }
            self.configs.setdefault(str(guild.id), []).append(cfg)
            save_reaction_configs(self.configs)

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
        except Exception:
            logger.exception('[ReactionRoles] Failed to create roles')
            embed = discord.Embed(title='❌ Failed to create roles', description='Check my permissions and role hierarchy.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='reactionroles_post', description='Post a reaction-roles message for a previously created role set')
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(config_id='Config ID from reactionroles_create', channel='Channel to post in', message='Message to post', title='Optional title for the posted embed')
    async def post_message(self, interaction: Interaction, config_id: str, channel: discord.TextChannel, message: str, title: Optional[str] = None):
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
                # Only show (x/y) if more than one page
                if len(pages) > 1:
                    if page_index == 1:
                        if title:
                            e = discord.Embed(title=title + f' ({page_index}/{len(pages)})', description=message, color=discord.Color.blurple())
                        else:
                            e = discord.Embed(description=message, color=discord.Color.blurple())
                            e.title = f'({page_index}/{len(pages)})'
                    else:
                        e = discord.Embed(title=f'({page_index}/{len(pages)})', color=discord.Color.blurple())
                else:
                    if title:
                        e = discord.Embed(title=title, description=message, color=discord.Color.blurple())
                    else:
                        e = discord.Embed(description=message, color=discord.Color.blurple())

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

        # remove config and any posted mappings that referenced the removed roles
        try:
            if cfg_index is not None:
                guild_cfgs.pop(cfg_index)

            # remove posted entries that reference the removed role ids
            to_remove = []
            for idx, entry in enumerate(list(guild_cfgs)):
                if entry.get('posted'):
                    mapping = entry['posted']
                    emoji_map = mapping.get('emoji_map', {})
                    # if any role id in emoji_map matches removed roles, remove this posted mapping
                    mapped_role_ids = {int(v) for v in emoji_map.values() if isinstance(v, int) or (isinstance(v, str) and v.isdigit())}
                    if removed_role_ids & mapped_role_ids:
                        # attempt to delete the posted message from the channel (best-effort)
                        try:
                            ch = self.bot.get_channel(mapping.get('channel_id'))
                            if ch:
                                msg = await ch.fetch_message(mapping.get('message_id'))
                                try:
                                    await msg.delete()
                                except Exception:
                                    # ignore delete failures
                                    logger.exception('[ReactionRoles] Failed to delete posted reaction roles message')
                        except Exception:
                            # ignore fetch/delete failures and continue to remove mapping
                            logger.exception('[ReactionRoles] Error while attempting to remove posted mapping')
                        to_remove.append(entry)

            for entry in to_remove:
                try:
                    guild_cfgs.remove(entry)
                except ValueError:
                    pass

            self.configs[str(interaction.guild.id)] = guild_cfgs
            save_reaction_configs(self.configs)
        except Exception:
            logger.exception('[ReactionRoles] Failed to remove config')

        if failed:
            embed = discord.Embed(title='⚠️ Partial Failure', description=f'Failed to delete roles: {failed}', color=discord.Color.orange())
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
