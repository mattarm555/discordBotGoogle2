import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed, ui
import json
import os
from datetime import datetime, timedelta
from utils.economy import (
    get_balance,
    add_currency,
    remove_currency,
    reset_guild_balances,
    can_claim_daily,
    set_daily_claim,
    daily_time_until_next,
)
import random
import re
from utils.debug import debug_command

SHOP_FILE = "shop.json"
INV_FILE = "shop_inventory.json"
GUILD_ITEMS_FILE = "shop_guild_items.json"  # per-guild custom items
SHOP_CONFIG_FILE = "shop_config.json"       # per-guild payout interval and last payout

# Category ordering and name mapping for known default/extra items
CATEGORY_ORDER = [
    "Starter",
    "Small Business",
    "Corporate",
    "Empire",
    "Legendary",
    "Other",
]

# Map item names to categories when not explicitly set (covers extra items list)
DEFAULT_CATEGORY_MAP = {
    # Starter
    "Lemonade Stand 🍋": "Starter",
    "Coffee Stand ☕": "Starter",
    "Newsstand 🗞️": "Starter",
    "Food Truck 🚚": "Starter",
    "Hotdog Cart 🌭": "Starter",
    "Bakery 🥐": "Starter",
    # Small Business
    "YouTube Channel 🎥": "Small Business",
    "Barbershop ✂️": "Small Business",
    "Gaming Café 🖥️": "Small Business",
    "Arcade 🎮": "Small Business",
    "Clothing Store 👕": "Small Business",
    "Car Wash 🚗": "Small Business",
    # Corporate
    "Tech Startup 💻": "Corporate",
    "Restaurant 🍽️": "Corporate",
    "Nightclub 🕺": "Corporate",
    "Movie Theater 🎬": "Corporate",
    "Hotel 🏨": "Corporate",
    "Casino 🎰": "Corporate",
    "Tech Company 🧠": "Corporate",
    # Empire
    "Theme Park 🎢": "Empire",
    "Luxury Hotel 🏰": "Empire",
    "Bank 🏦": "Empire",
    "Oil Rig 🛢️": "Empire",
    "TV Network 📺": "Empire",
    "Record Label 🎵": "Empire",
    "Airline ✈️": "Empire",
    "Crypto Exchange 🪙": "Empire",
    # Legendary
    "Space Mining Operation 🚀": "Legendary",
    "Intergalactic Shipping Co 🌌": "Legendary",
    "AI Corporation 🤖": "Legendary",
    "Mega City Developer 🏙️": "Legendary",
    "Time Travel Research Lab ⏳": "Legendary",
}

# Default items: incomes tuned for 30-minute cadence (smaller per payout)
DEFAULT_ITEMS = {
    "Coffee Stand ☕": {
        "cost": 2500,
        "income": 25,
        "description": "Small profits from morning customers."
    },
    "Food Truck 🚚": {
        "cost": 10000,
        "income": 120,
        "description": "Steady stream of hungry customers."
    },
    "YouTube Channel 🎥": {
        "cost": 25000,
        "income": 300,
        "description": "Ad revenue and sponsorship deals."
    },
    "Arcade 🎮": {
        "cost": 50000,
        "income": 600,
        "description": "Gamers can’t resist your machines!"
    },
    "Tech Startup 💻": {
        "cost": 100000,
        "income": 1500,
        "description": "Investors are impressed."
    },
    "Casino 🎰": {
        "cost": 250000,
        "income": 4000,
        "description": "The house always wins."
    }
}


def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure default shop exists
        self._ensure_shop()
        # Start passive loop
        self.passive_timer.start()
        # Category choices for guild-specific items
        self.CATEGORY_VALUES = [
            "Starter",
            "Small Business",
            "Corporate",
            "Empire",
            "Legendary",
            "Other",
        ]

    def cog_unload(self):
        try:
            self.passive_timer.cancel()
        except Exception:
            pass

    def _ensure_shop(self):
        data = _load_json(SHOP_FILE)
        if not data:
            _save_json(SHOP_FILE, DEFAULT_ITEMS)
            data = dict(DEFAULT_ITEMS)
        # Try to merge extended items if present in repo (optional file)
        try:
            extra_path = os.path.join(os.path.dirname(__file__), os.pardir, 'shop_extra_items.json')
            extra_path = os.path.abspath(extra_path)
            if os.path.exists(extra_path):
                with open(extra_path, 'r', encoding='utf-8') as f:
                    extra = json.load(f)
                # only add items that don't exist yet
                changed = False
                for k, v in extra.items():
                    if k not in data:
                        data[k] = v
                        changed = True
                if changed:
                    _save_json(SHOP_FILE, data)
        except Exception:
            pass

    # -------- Config and Guild Items Helpers --------
    def _get_shop_config(self, guild_id: str) -> dict:
        cfg = _load_json(SHOP_CONFIG_FILE)
        g = cfg.setdefault(str(guild_id), {})
        # default: 30 minutes interval, no last_payout yet
        g.setdefault("interval_seconds", 1800)
        # last_payout is stored as integer epoch seconds
        g.setdefault("last_payout", 0)
        return g

    def _save_shop_config(self, guild_id: str, gcfg: dict):
        cfg = _load_json(SHOP_CONFIG_FILE)
        cfg[str(guild_id)] = gcfg
        _save_json(SHOP_CONFIG_FILE, cfg)

    def _get_guild_items(self, guild_id: str) -> dict:
        data = _load_json(GUILD_ITEMS_FILE)
        return data.setdefault(str(guild_id), {})

    def _save_guild_items(self, guild_id: str, items: dict):
        data = _load_json(GUILD_ITEMS_FILE)
        data[str(guild_id)] = items
        _save_json(GUILD_ITEMS_FILE, data)

    def _merge_items_for_guild(self, guild_id: str) -> dict:
        base = _load_json(SHOP_FILE) or {}
        gitems = self._get_guild_items(guild_id)
        merged = dict(base)
        # guild items override by name if duplicate
        merged.update(gitems)
        return merged

    def _parse_duration(self, text: str) -> int:
        """Parse a duration string like '15m', '1h', '1h30m', '45' (minutes) into seconds.
        Returns 0 if invalid.
        """
        if not text:
            return 0
        text = text.strip().lower()
        # Accept combined tokens, e.g., 1h30m, 2h, 45m, 3600s; bare number = minutes
        pattern = re.compile(r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?$")
        m = pattern.match(text)
        if m:
            d, h, mi, s = m.groups()
            total = 0
            total += int(d) * 86400 if d else 0
            total += int(h) * 3600 if h else 0
            total += int(mi) * 60 if mi else 0
            total += int(s) if s else 0
            if total > 0:
                return total
        # fallback: if it's just a number, treat as minutes
        if text.isdigit():
            return int(text) * 60
        return 0

    def _fmt_interval(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s and not d and not h:
            parts.append(f"{s}s")
        return ' '.join(parts) if parts else '0s'

    def _get_inventory(self, guild_id: str):
        inv = _load_json(INV_FILE)
        return inv.setdefault(str(guild_id), {})

    def _save_inventory(self, guild_id: str, inv_guild: dict):
        inv = _load_json(INV_FILE)
        inv[str(guild_id)] = inv_guild
        _save_json(INV_FILE, inv)

    @app_commands.command(name="shop", description="View available items in the shop.")
    @app_commands.describe(page="Page number to view (1-based)")
    async def shop(self, interaction: Interaction, page: int = 1):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        gid = str(guild.id)
        items = self._merge_items_for_guild(gid)
        inv_guild = self._get_inventory(str(guild.id))
        user_inv = inv_guild.get(str(interaction.user.id), {})

        # Prepare pagination by category
        # Sort items by cost ascending, fallback to name
        sorted_items = sorted(items.items(), key=lambda kv: (int(kv[1].get('cost', 0)), kv[0].lower()))
        per_page = 8

        gcfg = self._get_shop_config(gid)
        interval = int(gcfg.get('interval_seconds', 1800))
        interval_str = self._fmt_interval(interval)

        if not items:
            await interaction.response.send_message(embed=Embed(title="🛒 Item Shop", description="No items available.", color=discord.Color.gold()))
            return

        # Build interactive paginator view
        view = ShopView(
            sorted_items=sorted_items,
            user_inv=user_inv,
            interval_str=interval_str,
            page_size=per_page,
            page=page,
        )
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    @app_commands.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item_name="Name of the shop item to purchase (exact match)", amount="Quantity to buy (default 1)")
    async def buy(self, interaction: Interaction, item_name: str, amount: int = 1):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        items = self._merge_items_for_guild(str(guild.id))
        if item_name not in items:
            await interaction.response.send_message(embed=Embed(title="❌ Not Found", description="That item doesn’t exist in the shop.", color=discord.Color.red()), ephemeral=True)
            return
        item = items[item_name]
        uid = str(interaction.user.id)
        gid = str(guild.id)
        bal = get_balance(uid, guild_id=gid)
        # Validate amount
        try:
            amount = int(amount)
        except Exception:
            amount = 1
        if amount <= 0:
            await interaction.response.send_message(embed=Embed(title="❌ Invalid Amount", description="Amount must be at least 1.", color=discord.Color.red()), ephemeral=True)
            return
        unit_cost = int(item.get('cost', 0))
        total_cost = unit_cost * amount
        if bal < total_cost:
            await interaction.response.send_message(embed=Embed(title="💸 Not Enough Coins", description=f"You need {total_cost:,} coins to buy {amount}× {item_name} (each {unit_cost:,}).", color=discord.Color.orange()), ephemeral=True)
            return
        # Deduct
        if not remove_currency(uid, total_cost, guild_id=gid):
            await interaction.response.send_message(embed=Embed(title="❌ Purchase Failed", description="Could not deduct coins.", color=discord.Color.red()), ephemeral=True)
            return
        # Update inv
        inv_guild = self._get_inventory(gid)
        user_inv = inv_guild.setdefault(uid, {})
        user_inv[item_name] = int(user_inv.get(item_name, 0)) + amount
        self._save_inventory(gid, inv_guild)
        await interaction.response.send_message(embed=Embed(title="✅ Purchase Successful", description=f"You bought **{amount}× {item_name}** for {total_cost:,} coins!", color=discord.Color.green()))

    @app_commands.command(name="daily", description="Claim your daily currency reward (once every 24 hours)")
    async def daily(self, interaction: Interaction):
        debug_command('daily', interaction.user, interaction.guild)
        uid = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        if not can_claim_daily(uid, guild_id=guild_id):
            remaining = daily_time_until_next(uid, guild_id=guild_id)
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            parts = []
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not hours and not minutes:
                parts.append(f"{seconds}s")
            time_str = " ".join(parts)
            desc = (
                "You already claimed your daily reward in this server.\n"
                f"Next claim available in **{time_str}** (midnight UTC reset)."
            )
            embed = discord.Embed(title="⏳ Daily Already Claimed", description=desc, color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        reward = random.randint(10000, 100000)
        add_currency(uid, reward, guild_id=guild_id)
        set_daily_claim(uid, guild_id=guild_id)
        embed = discord.Embed(
            title="🎁 Daily Reward",
            description=f"You received **{reward}** coins today! Come back after the next reset (midnight UTC).",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="See your owned items.")
    async def inventory(self, interaction: Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        inv_guild = self._get_inventory(str(guild.id))
        user_inv = inv_guild.get(str(interaction.user.id), {})
        if not user_inv:
            await interaction.response.send_message(embed=Embed(title="🪣 Empty Inventory", description="You don't own any passive items yet. Use /shop to browse.", color=discord.Color.blurple()))
            return
        items = _load_json(SHOP_FILE)
        # Use merged items for current incomes
        items = self._merge_items_for_guild(str(guild.id))
        gcfg = self._get_shop_config(str(guild.id))
        interval_str = self._fmt_interval(int(gcfg.get('interval_seconds', 1800)))
        embed = Embed(title=f"{interaction.user.display_name}'s Inventory", color=discord.Color.blue())
        for item, count in user_inv.items():
            inc = items.get(item, {}).get('income', 0)
            embed.add_field(name=item, value=f"Quantity: {count} • Income: {int(inc):,} per interval ({interval_str})", inline=False)
        await interaction.response.send_message(embed=embed)

    # -------- Admin: Set payout interval --------
    @app_commands.command(name="shop_set_interval", description="Admin: Set how often items pay out (e.g., 15m, 1h, 2h30m). Minimum 1 minute.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(duration="Interval between payouts, e.g., 15m, 1h, 2h30m")
    async def shop_set_interval(self, interaction: Interaction, duration: str):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        seconds = self._parse_duration(duration)
        if seconds < 60:
            await interaction.response.send_message(embed=Embed(title="❌ Invalid Duration", description="Please provide at least 1 minute (e.g., 1m).", color=discord.Color.red()), ephemeral=True)
            return
        gcfg = self._get_shop_config(str(guild.id))
        gcfg["interval_seconds"] = int(seconds)
        # do not reset last_payout; keep schedule continuity
        self._save_shop_config(str(guild.id), gcfg)
        await interaction.response.send_message(embed=Embed(title="✅ Interval Updated", description=f"Items will pay every {duration}.", color=discord.Color.green()))

    # -------- Admin: Guild-specific items --------
    @app_commands.command(name="item_add", description="Admin: Add a guild-specific shop item.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Item name (exact)", cost="Purchase cost (coins)", income="Income paid each interval", description="Short description", category="Category for grouping in /shop")
    @app_commands.choices(category=[
        app_commands.Choice(name="🌱 Starter", value="Starter"),
        app_commands.Choice(name="🏢 Small Business", value="Small Business"),
        app_commands.Choice(name="💼 Corporate", value="Corporate"),
        app_commands.Choice(name="🌆 Empire", value="Empire"),
        app_commands.Choice(name="🚀 Legendary", value="Legendary"),
        app_commands.Choice(name="Other", value="Other"),
    ])
    async def item_add(self, interaction: Interaction, name: str, cost: int, income: int, description: str, category: app_commands.Choice[str] = None):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        name = name.strip()
        if not name:
            await interaction.response.send_message(embed=Embed(title="❌ Invalid Name", description="Name cannot be empty.", color=discord.Color.red()), ephemeral=True)
            return
        if cost < 0 or income < 0:
            await interaction.response.send_message(embed=Embed(title="❌ Invalid Values", description="Cost and income must be non-negative integers.", color=discord.Color.red()), ephemeral=True)
            return
        items = self._get_guild_items(str(guild.id))
        items[name] = {
            "cost": int(cost),
            "income": int(income),
            "description": description,
            "category": (category.value if category else "Other")
        }
        self._save_guild_items(str(guild.id), items)
        cat_label = category.value if category else "Other"
        await interaction.response.send_message(embed=Embed(title="✅ Item Added", description=f"Added item {name} (cost {cost}, income {income}, category {cat_label}).", color=discord.Color.green()))

    @app_commands.command(name="item_delete", description="Admin: Delete a guild-specific shop item by name.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Item name to delete (exact)")
    async def item_delete(self, interaction: Interaction, name: str):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        name = name.strip()
        items = self._get_guild_items(str(guild.id))
        if name not in items:
            await interaction.response.send_message(embed=Embed(title="❌ Not Found", description="That item is not a guild-specific item.", color=discord.Color.red()), ephemeral=True)
            return
        items.pop(name, None)
        self._save_guild_items(str(guild.id), items)
        await interaction.response.send_message(embed=Embed(title="✅ Item Deleted", description=f"Removed guild-specific item {name}.", color=discord.Color.green()))

    @app_commands.command(name="item_list", description="List this server's guild-specific shop items.")
    async def item_list(self, interaction: Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        items = self._get_guild_items(str(guild.id))
        if not items:
            await interaction.response.send_message(embed=Embed(title="No Guild Items", description="This server hasn't added any custom items.", color=discord.Color.orange()), ephemeral=True)
            return
        e = Embed(title=f"🛒 {guild.name} — Custom Items", color=discord.Color.gold())
        for name, info in items.items():
            cat = info.get('category')
            cat_line = f"Category: {cat}\n" if cat else ""
            e.add_field(name=f"{name} — {info.get('cost', 0)} coins", value=f"💸 Income: {info.get('income', 0)} per interval\n{cat_line}{info.get('description', '')}", inline=False)
        await interaction.response.send_message(embed=e)

    # -------- Admin: Wipe coins and owned items (inventory) --------
    @app_commands.command(name="econ_wipe", description="Admin: Wipe all users' coins and their owned items for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def econ_wipe(self, interaction: Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(embed=Embed(title="Guild Only", description="Use this in a server.", color=discord.Color.red()), ephemeral=True)
            return
        gid = str(guild.id)
        # Wipe coin balances using existing economy helper
        try:
            reset_guild_balances(gid)
        except Exception:
            pass
        # Wipe owned items by clearing this guild's inventory bucket
        try:
            inv = _load_json(INV_FILE)
            if gid in inv:
                inv.pop(gid, None)
                _save_json(INV_FILE, inv)
        except Exception:
            pass
        embed = Embed(title="✅ Economy Wiped", description="All coin balances and owned items for this server have been wiped.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    # Switch to 1-minute cadence and check per-guild interval
    @tasks.loop(minutes=1)
    async def passive_timer(self):
        inv = _load_json(INV_FILE)
        now = int(datetime.utcnow().timestamp())
        any_changes = False
        # Iterate guilds with inventories
        for gid, users in list(inv.items()):
            # Load per-guild config
            gcfg = self._get_shop_config(gid)
            interval = int(gcfg.get('interval_seconds', 1800))
            last = int(gcfg.get('last_payout', 0))
            if interval < 60:
                interval = 60
            if last and (now - last) < interval:
                continue  # not time yet
            # Merge items for this guild
            items = self._merge_items_for_guild(gid)
            guild_paid = 0
            for uid, owned in list(users.items()):
                total_income = 0
                for item_name, count in owned.items():
                    info = items.get(item_name)
                    if not info:
                        continue
                    total_income += int(info.get('income', 0)) * int(count)
                if total_income > 0:
                    try:
                        add_currency(uid, total_income, guild_id=gid)
                        any_changes = True
                        guild_paid += total_income
                    except Exception:
                        pass
            # Update last payout time if we processed this guild (regardless of payment amount)
            gcfg['last_payout'] = now
            self._save_shop_config(gid, gcfg)
            if guild_paid > 0:
                print(f"[PASSIVE INCOME] Guild {gid}: paid {guild_paid} coins at {datetime.utcnow().isoformat()}Z (interval {interval}s)")

    @passive_timer.before_loop
    async def before_passive_timer(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))


# ---- Shop Paginator View with Buttons ----
class ShopView(ui.View):
    def __init__(self, sorted_items: list[tuple[str, dict]], user_inv: dict, interval_str: str, page_size: int = 8, page: int = 1, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.items = sorted_items
        self.user_inv = user_inv or {}
        self.interval_str = interval_str
        self.page_size = page_size
        # Build category pages: list of (category, items_chunk)
        self.pages = self._build_category_pages(sorted_items)
        self.total_pages = max(1, len(self.pages))
        self.page = max(1, min(page, self.total_pages))
        self._update_buttons()

    def _build_category_pages(self, items: list[tuple[str, dict]]):
        # Group by category (guild-specific category, default map fallback, then Other)
        buckets: dict[str, list[tuple[str, dict]]] = {c: [] for c in CATEGORY_ORDER}
        for name, info in items:
            cat = info.get('category') or DEFAULT_CATEGORY_MAP.get(name) or 'Other'
            if cat not in buckets:
                buckets['Other'].append((name, info))
            else:
                buckets[cat].append((name, info))
        # For each category, chunk into pages of page_size, keeping order by cost/name as provided
        pages: list[tuple[str, list[tuple[str, dict]]]] = []
        for cat in CATEGORY_ORDER:
            cat_items = buckets.get(cat, [])
            if not cat_items:
                continue
            # chunk
            for i in range(0, len(cat_items), self.page_size):
                pages.append((cat, cat_items[i:i + self.page_size]))
        return pages

    def make_embed(self) -> Embed:
        cat, chunk = self.pages[self.page - 1]
        embed = Embed(title=f"🛒 Item Shop — {cat}", color=discord.Color.gold())
        embed.description = f"Income is paid per interval (currently {self.interval_str}). Use /buy <item name> to purchase."
        for name, info in chunk:
            owned = int(self.user_inv.get(name, 0))
            owned_str = f" • You own: {owned}" if owned > 0 else ""
            cost = int(info.get('cost', 0))
            income = int(info.get('income', 0))
            desc = info.get('description', '')
            cat = info.get('category')
            cat_line = f"Category: {cat}\n" if cat else ""
            embed.add_field(
                name=f"{name}",
                value=f"Cost: {cost:,} coins\n💸 Income: {income:,} per interval\n{cat_line}{desc}{owned_str}",
                inline=False
            )
        total_items = len(self.items)
        embed.set_footer(text=f"Page {self.page}/{self.total_pages} • {total_items} item(s) total")
        return embed

    def _update_buttons(self):
        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == 'shop_prev':
                    child.disabled = self.page <= 1
                elif child.custom_id == 'shop_next':
                    child.disabled = self.page >= self.total_pages
                elif child.custom_id == 'shop_back5':
                    child.disabled = self.page <= 1
                elif child.custom_id == 'shop_fwd5':
                    child.disabled = self.page >= self.total_pages

    @ui.button(label="⏮ -5", style=discord.ButtonStyle.gray, custom_id='shop_back5')
    async def back5(self, interaction: Interaction, button: ui.Button):
        old = self.page
        self.page = max(1, self.page - 5)
        if self.page == old:
            await interaction.response.defer()
            return
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="⬅️ Prev", style=discord.ButtonStyle.blurple, custom_id='shop_prev')
    async def prev(self, interaction: Interaction, button: ui.Button):
        if self.page <= 1:
            await interaction.response.defer()
            return
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="Next ➡️", style=discord.ButtonStyle.blurple, custom_id='shop_next')
    async def next(self, interaction: Interaction, button: ui.Button):
        if self.page >= self.total_pages:
            await interaction.response.defer()
            return
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="+5 ⏭", style=discord.ButtonStyle.gray, custom_id='shop_fwd5')
    async def fwd5(self, interaction: Interaction, button: ui.Button):
        old = self.page
        self.page = min(self.total_pages, self.page + 5)
        if self.page == old:
            await interaction.response.defer()
            return
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)
